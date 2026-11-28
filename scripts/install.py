#!/usr/bin/env python3
"""Install jstack skills into agent clients' user skill folders.

Stdlib only. Links (or copies) each skills/<name> folder into the client's
skills folder. It never puts a binary on $PATH, and uninstall removes only
entries this checkout owns.

Rig rendering: when ~/.config/jstack/rig.json (or --rig PATH) exists, every
skill whose SKILL.md holds a `<!-- jstack:slot:NAME -->` block is rendered into
~/.local/share/jstack/rendered/skills/<name>/ (or --render-dir) and installed
from there. The slot grows by at most 1,024 bytes. Without a rig, installs are
the plain links or copies of skills/<name>.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO / "skills"
MARKER = ".jstack-install.json"
RIG_TOOL = REPO / "skills" / "jstack-setup" / "scripts" / "jstack-rig.py"
RIG_SCHEMA = "jstack.rig/1"
OVERLAY_CAP = 1024
SLOT = re.compile(r"<!-- jstack:slot:([a-z0-9][a-z0-9-]*) -->(.*?)<!-- /jstack:slot:\1 -->", re.DOTALL)
HOOK_MARK = "# jstack:managed-hook"
HOOKS = ("post-merge", "post-checkout")
CLIENTS = ("claude", "codex", "antigravity", "opencode")
# Never touch these names, even if a stray marker or link claims them.
PROTECTED = frozenset({"synced"})
COPY_IGNORE = ("__pycache__", "*.py[cod]", ".DS_Store")

# Sibling skills each skill calls. Resolved transitively.
DEPS: dict[str, tuple[str, ...]] = {
    "full-send": ("sol-loop", "file-pr", "babysit-pr", "leaving-pr-comments", "pr"),
    "full-stop": ("full-send",),
    "file-pr": ("babysit-pr", "leaving-pr-comments"),
    "babysit-pr": ("leaving-pr-comments",),
    "modernize": ("leaving-pr-comments",),
    "takeover": ("modernize", "file-pr", "babysit-pr", "leaving-pr-comments"),
    "bug": ("council", "leaving-pr-comments"),
    "epic": (
        "full-send",
        "council",
        "sol-loop",
        "file-pr",
        "babysit-pr",
        "pr",
        "hindsight",
        "t3-launch-worktrees",
    ),
    "hindsight-setup": ("hindsight",),
    "jstack-setup": ("prove",),
}


def available_skills() -> list[str]:
    return sorted(p.name for p in SKILLS_DIR.iterdir() if (p / "SKILL.md").is_file())


def resolve(selected: list[str], with_deps: bool = True) -> list[str]:
    known = set(available_skills())
    unknown = [s for s in selected if s not in known]
    if unknown:
        raise SystemExit(f"unknown skill(s): {', '.join(unknown)}")
    out: set[str] = set()
    stack = list(selected)
    while stack:
        name = stack.pop()
        if name in out:
            continue
        out.add(name)
        if with_deps:
            stack.extend(DEPS.get(name, ()))
    return sorted(out)


@dataclass(frozen=True)
class Target:
    client: str
    path: Path


def client_dirs(home: Path, client: str, env: dict[str, str]) -> list[Path]:
    """Skill folders for one client. `env` is empty when --home is explicit."""
    if client == "claude":
        return [home / ".claude" / "skills"]
    if client == "codex":
        return [Path(env.get("CODEX_HOME") or home / ".codex") / "skills"]
    if client == "antigravity":
        # Antigravity reads ~/.gemini/config/skills. T3-managed Antigravity
        # keeps a per-provider config folder; when its skills entry is a link
        # it already points here, so only add real folders.
        dirs = [home / ".gemini" / "config" / "skills"]
        t3 = home / ".t3" / "userdata" / "providers" / "antigravity"
        if t3.is_dir():
            for provider in sorted(t3.iterdir()):
                skills = provider / "config" / "skills"
                if skills.is_dir() and not skills.is_symlink():
                    dirs.append(skills)
        return dirs
    if client == "opencode":
        config = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
        return [config / "opencode" / "skills"]
    raise ValueError(client)


def detected(home: Path, client: str, env: dict[str, str]) -> bool:
    if client == "claude":
        return (home / ".claude").exists()
    if client == "codex":
        return Path(env.get("CODEX_HOME") or home / ".codex").exists()
    if client == "antigravity":
        return (home / ".gemini").exists() or (
            home / ".t3" / "userdata" / "providers" / "antigravity"
        ).exists()
    if client == "opencode":
        return (Path(env.get("XDG_CONFIG_HOME") or home / ".config") / "opencode").exists()
    raise ValueError(client)


def targets(home: Path, client: str, env: dict[str, str]) -> list[Target]:
    if client == "all":
        chosen = [c for c in CLIENTS if detected(home, c, env)]
        if not chosen:
            raise SystemExit(f"no supported client found under {home}; pass --client")
    else:
        chosen = [client]
    return [Target(c, d) for c in chosen for d in client_dirs(home, c, env)]


def tree_digest(src: Path, follow: bool = False) -> str:
    """Deterministic SHA-256 of a skill folder, ignoring install markers, bytecode and Finder noise.

    With follow=True, symlinks are read through, so a rendered folder that links
    its static subfolders hashes like a real copy of itself.
    """
    h = hashlib.sha256()
    if follow:
        paths = sorted(
            Path(dirpath) / name for dirpath, _dirs, files in os.walk(src, followlinks=True) for name in files
        )
    else:
        paths = sorted(src.rglob("*"))
    for path in paths:
        rel = path.relative_to(src)
        if any(part in ("__pycache__", ".DS_Store", MARKER) for part in rel.parts):
            continue
        if path.suffix in (".pyc", ".pyo", ".pyd"):
            continue
        if path.is_symlink() and not follow:
            h.update(b"L" + rel.as_posix().encode("utf-8") + b"\0")
            h.update(os.readlink(path).encode("utf-8", errors="surrogateescape") + b"\0")
            continue
        if path.is_file():
            h.update(rel.as_posix().encode("utf-8") + b"\0")
            h.update(path.read_bytes() + b"\0")
    return h.hexdigest()


def is_rendered_dir(path: Path, name: str) -> bool:
    """True for a folder this checkout rendered: a real folder with our non-symlink render marker."""
    marker = path / MARKER
    if path.is_symlink() or not path.is_dir() or marker.is_symlink() or not marker.is_file():
        return False
    try:
        data = json.loads(marker.read_text())
        raw_source = data["source"]
        if not isinstance(raw_source, str) or not Path(raw_source).is_absolute():
            return False
        return bool(data.get("rendered")) and data.get("skill") == name and Path(raw_source).resolve() == REPO.resolve()
    except (OSError, ValueError, KeyError, TypeError):
        return False


def owns_link(entry: Path) -> bool:
    """True only for entries this checkout installed.

    A symlink must point directly at the same-named child of this repo's skills/
    tree. A real folder must hold a non-symlink marker naming this repo's
    absolute path and matching entry.name. Anything else belongs to the user.
    """
    if entry.name in PROTECTED:
        return False
    if entry.is_symlink():
        try:
            dest = entry.resolve(strict=False)
        except (OSError, RuntimeError):
            return False
        if dest.name != entry.name:
            return False
        return dest.parent == SKILLS_DIR.resolve() or is_rendered_dir(dest, entry.name)
    marker = entry / MARKER
    if entry.is_dir() and not marker.is_symlink() and marker.is_file():
        try:
            data = json.loads(marker.read_text())
            raw_source = data["source"]
            if not isinstance(raw_source, str) or not Path(raw_source).is_absolute():
                return False
            if data.get("skill") != entry.name:
                return False
            source = Path(raw_source).resolve()
        except (OSError, ValueError, KeyError, TypeError):
            return False
        return source == REPO.resolve()
    return False


def is_modified_copy(entry: Path) -> bool:
    """True when an owned copy-mode folder has local edits relative to its installed digest."""
    if entry.is_symlink() or not entry.is_dir():
        return False
    marker = entry / MARKER
    if marker.is_symlink() or not marker.is_file():
        return False
    try:
        recorded = json.loads(marker.read_text()).get("digest")
    except (OSError, ValueError):
        return True
    return not recorded or tree_digest(entry) != recorded


def status(entry: Path, name: str, mode: str, rendered: Path | None = None) -> str:
    """State of one installed entry. `rendered` is the folder it must come from, when a rig renders this skill."""
    src = (rendered if rendered is not None else SKILLS_DIR / name).resolve()
    if not entry.exists() and not entry.is_symlink():
        return "missing"
    if not owns_link(entry):
        return "conflict"
    if entry.is_symlink():
        if not entry.exists():
            return "broken"
        if entry.resolve() != src:
            return "stale"
        return "ok" if mode == "symlink" else "mode"
    data = json.loads((entry / MARKER).read_text())
    recorded = data.get("digest")
    current = tree_digest(entry)
    target = tree_digest(src, follow=rendered is not None)
    if not recorded or (current != recorded and current != target):
        return "modified"
    if data.get("version") != version() or recorded != target or current != target or data.get("skill") != name:
        return "stale"
    return "ok" if mode == "copy" else "mode"


def version() -> str:
    return json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())["version"]


def remove(entry: Path) -> None:
    if entry.is_symlink() or entry.is_file():
        entry.unlink()
    else:
        shutil.rmtree(entry)


def place(entry: Path, name: str, mode: str, rendered: Path | None = None) -> None:
    src = rendered if rendered is not None else SKILLS_DIR / name
    if mode == "symlink":
        entry.symlink_to(src.resolve(), target_is_directory=True)
        return
    shutil.copytree(src, entry, symlinks=False, ignore=shutil.ignore_patterns(*COPY_IGNORE))
    marker = {
        "source": str(REPO.resolve()),
        "skill": name,
        "version": version(),
        "digest": tree_digest(src, follow=rendered is not None),
    }
    if rendered is not None:
        recorded = json.loads((rendered / MARKER).read_text())
        for key in ("source_digest", "rig_digest", "rendered_digest"):
            marker[key] = recorded.get(key)
    (entry / MARKER).write_text(json.dumps(marker, indent=2) + "\n")


# Rig rendering ------------------------------------------------------------


def rig_tool():
    """Load the rig validator from jstack-setup without leaving bytecode in the checkout."""
    loader = importlib.machinery.SourceFileLoader("jstack_rig", str(RIG_TOOL))
    spec = importlib.util.spec_from_loader("jstack_rig", loader)
    module = importlib.util.module_from_spec(spec)
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = keep
    return module


def load_rig(path: Path) -> dict:
    """Read and validate a rig file. Exits with a clear message when it is unusable."""
    try:
        rig = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"rig {path.name}: cannot read as JSON ({exc.__class__.__name__}); fix or remove it") from None
    problems = rig_tool().validate(rig)
    if problems:
        raise SystemExit("rig file is invalid:\n  " + "\n  ".join(problems))
    return rig


def rig_digest(rig: dict) -> str:
    return hashlib.sha256(json.dumps(rig, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def render_slot_body(slot: str, rig: dict) -> str | None:
    """Replacement text for one slot, or None to keep the stock text. Only the `rig` slot is known."""
    if slot != "rig":
        return None
    lines = []
    fallback = rig.get("fallback")
    if isinstance(fallback, dict):
        lines.append(f"- Fallback model: `{fallback['provider']}/{fallback['model']}`")
    if rig.get("media_uploader"):
        lines.append(f"- Media uploader: `{rig['media_uploader']}`")
    for lane, tools in sorted((rig.get("lanes") or {}).items()):
        if tools:
            lines.append(f"- Lane {lane}: " + ", ".join(f"`{t}`" for t in tools))
    if not lines:
        return None
    return "\nLocal rig, rendered by jstack from the rig file. Edit the rig file, not this skill.\n" + "\n".join(lines) + "\n"


def render_text(text: str, rig: dict) -> str:
    def swap(match: re.Match[str]) -> str:
        body = render_slot_body(match.group(1), rig)
        if body is None:
            return match.group(0)
        return f"<!-- jstack:slot:{match.group(1)} -->{body}<!-- /jstack:slot:{match.group(1)} -->"

    return SLOT.sub(swap, text)


def has_slot(name: str) -> bool:
    skill_md = SKILLS_DIR / name / "SKILL.md"
    return skill_md.is_file() and SLOT.search(skill_md.read_text(encoding="utf-8")) is not None


def render_state(name: str, rig_dig: str, render_root: Path) -> str | None:
    """None when the rendered folder is current; otherwise why it is not."""
    out = render_root / name
    if not is_rendered_dir(out, name):
        return "not rendered"
    try:
        marker = json.loads((out / MARKER).read_text())
    except (OSError, ValueError):
        return "render marker unreadable"
    if marker.get("source_digest") != tree_digest(SKILLS_DIR / name):
        return "skill source changed"
    if marker.get("rig_digest") != rig_dig:
        return "rig changed"
    if marker.get("rendered_digest") != tree_digest(out):
        return "rendered folder edited"
    return None


def render_skill(name: str, rig: dict, rig_dig: str, render_root: Path) -> None:
    """Write render_root/<name>/ from the stock skill and the rig. Raises ValueError over the overlay cap."""
    src = SKILLS_DIR / name
    stock = (src / "SKILL.md").read_text(encoding="utf-8")
    text = render_text(stock, rig)
    growth = len(text.encode("utf-8")) - len(stock.encode("utf-8"))
    if growth > OVERLAY_CAP:
        raise ValueError(f"overlay adds {growth} bytes, over the {OVERLAY_CAP}-byte cap; trim the rig")
    out = render_root / name
    if (out.exists() or out.is_symlink()) and not is_rendered_dir(out, name):
        raise ValueError(f"{out.name} exists in the render folder and was not rendered by jstack")
    render_root.mkdir(parents=True, exist_ok=True)
    tmp = render_root / f".{name}.tmp"
    if tmp.exists() or tmp.is_symlink():
        remove(tmp)
    tmp.mkdir()
    (tmp / "SKILL.md").write_text(text, encoding="utf-8")
    for child in sorted(src.iterdir()):
        if child.name in ("SKILL.md", "__pycache__", ".DS_Store", MARKER):
            continue
        (tmp / child.name).symlink_to(child.resolve(), target_is_directory=child.is_dir())
    marker = {
        "source": str(REPO.resolve()),
        "skill": name,
        "version": version(),
        "rendered": True,
        "source_digest": tree_digest(src),
        "rig_digest": rig_dig,
        "rendered_digest": tree_digest(tmp),
    }
    (tmp / MARKER).write_text(json.dumps(marker, indent=2) + "\n")
    if out.exists() or out.is_symlink():
        remove(out)
    tmp.rename(out)


def hooks_dir(override: Path | None) -> Path:
    if override:
        return override
    proc = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--git-path", "hooks"], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SystemExit("cannot find this checkout's git hooks folder; pass --hooks-dir")
    path = Path(proc.stdout.strip())
    return path if path.is_absolute() else REPO / path


def install_hooks(folder: Path, reconcile_args: list[str] | None = None) -> int:
    """Opt-in post-merge and post-checkout hooks that run --reconcile. Never replaces a hook it did not write."""
    rc = 0
    folder.mkdir(parents=True, exist_ok=True)
    extra = "".join(f" {shlex.quote(arg)}" for arg in (reconcile_args or []))
    script = (
        f"#!/bin/sh\n{HOOK_MARK}\n"
        f"python3 {shlex.quote(str(REPO / 'scripts' / 'install.py'))} --reconcile{extra} >/dev/null 2>&1 || true\n"
    )
    for name in HOOKS:
        hook = folder / name
        if hook.exists() and HOOK_MARK not in hook.read_text(errors="replace"):
            print(f"hook {name}: skipped, a hook this checkout did not write already exists", file=sys.stderr)
            rc = 1
            continue
        hook.write_text(script)
        hook.chmod(0o755)
        print(f"hook {name}: installed")
    return rc


def run(argv: list[str] | None = None, environ: dict[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="Install jstack skills into Claude Code, Codex, Antigravity or OpenCode.",
    )
    parser.add_argument("--client", choices=(*CLIENTS, "all"), default="all")
    parser.add_argument("--only", help="comma-separated skill names (dependencies are added)")
    parser.add_argument("--no-deps", action="store_true", help="do not add sibling skills")
    parser.add_argument("--mode", choices=("symlink", "copy"), default="symlink")
    parser.add_argument("--check", action="store_true", help="report state; change nothing")
    parser.add_argument("--uninstall", action="store_true", help="remove entries this checkout owns")
    parser.add_argument("--home", type=Path, help="home folder to install into (default: $HOME)")
    parser.add_argument("--rig", type=Path, help="rig file to render slots from (default: ~/.config/jstack/rig.json)")
    parser.add_argument("--render-dir", type=Path, help="where rendered skills go (default: ~/.local/share/jstack/rendered/skills)")
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="re-render and repair entries this checkout already installed; install nothing new",
    )
    parser.add_argument("--install-hook", action="store_true", help="also add post-merge and post-checkout hooks that run --reconcile")
    parser.add_argument("--hooks-dir", type=Path, help="git hooks folder for --install-hook (default: this checkout's)")
    args = parser.parse_args(argv)
    exclusive = [flag for flag, on in (("--check", args.check), ("--uninstall", args.uninstall), ("--reconcile", args.reconcile)) if on]
    if len(exclusive) > 1:
        parser.error(f"{' and '.join(exclusive)} are exclusive")
    if args.install_hook and exclusive:
        parser.error(f"--install-hook cannot combine with {exclusive[0]}")

    env = dict(os.environ if environ is None else environ)
    if args.home:
        home = args.home.expanduser().resolve()
        env = {}
    else:
        home = Path(env.get("HOME") or Path.home())
    config_home = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
    data_home = Path(env.get("XDG_DATA_HOME") or home / ".local" / "share")
    rig_path = args.rig.expanduser() if args.rig else config_home / "jstack" / "rig.json"
    render_root = args.render_dir.expanduser() if args.render_dir else data_home / "jstack" / "rendered" / "skills"
    if args.rig and not rig_path.is_file():
        parser.error(f"--rig {rig_path.name} does not exist")

    if args.only is not None:
        picked = [s.strip() for s in args.only.split(",") if s.strip()]
        if not picked:
            parser.error("--only requires at least one skill")
        # Uninstall removes only the named skills (including ones removed from the repo).
        if args.uninstall:
            names = sorted(set(picked))
        else:
            names = resolve(picked, with_deps=not args.no_deps)
            added = sorted(set(names) - set(picked))
            if added:
                print(f"adding dependencies: {', '.join(added)}")
    else:
        names = available_skills()

    rc = 0
    # Slot rendering. With no rig file, nothing here runs and installs stay stock.
    renders: dict[str, Path] = {}
    reasons: dict[str, str] = {}
    if rig_path.is_file() and not args.uninstall:
        rig = load_rig(rig_path)
        rig_dig = rig_digest(rig)
        for name in names:
            if not has_slot(name):
                continue
            why = render_state(name, rig_dig, render_root)
            if why and not args.check:
                try:
                    render_skill(name, rig, rig_dig, render_root)
                    why = None
                except ValueError as exc:
                    print(f"{name}: not rendered, {exc}; installing stock", file=sys.stderr)
                    rc = 1
                    continue
            renders[name] = render_root / name
            if why:
                reasons[name] = why

    for target in targets(home, args.client, env):
        label = f"{target.client}: {target.path}"
        if args.reconcile:
            for name in names:
                entry = target.path / name
                if not (entry.exists() or entry.is_symlink()) or not owns_link(entry):
                    continue
                mode = "symlink" if entry.is_symlink() else "copy"
                state = status(entry, name, mode, renders.get(name))
                if state == "ok":
                    continue
                if state in ("conflict", "modified"):
                    print(f"{label}/{name}: skipped, {state}", file=sys.stderr)
                    rc = 1
                    continue
                remove(entry)
                place(entry, name, mode, renders.get(name))
                print(f"{label}/{name}: reconciled ({mode})")
            continue
        if args.uninstall:
            if not target.path.is_dir():
                continue
            for entry in sorted(target.path.iterdir()):
                if args.only is not None and entry.name not in names:
                    continue
                if owns_link(entry):
                    if is_modified_copy(entry):
                        print(f"{label}/{entry.name}: skipped, modified locally; remove it manually", file=sys.stderr)
                        rc = 1
                        continue
                    remove(entry)
                    print(f"{label}/{entry.name}: removed")
            continue
        for name in names:
            entry = target.path / name
            state = status(entry, name, args.mode, renders.get(name))
            if state == "ok" and name in reasons:
                state = "drift"
            if args.check:
                print(f"{label}/{name}: {state}" + (f" ({reasons[name]})" if state == "drift" else ""))
                rc |= state != "ok"
                continue
            if state in ("conflict", "modified"):
                reason = "modified locally; remove it first to replace" if state == "modified" else "not installed by jstack"
                print(f"{label}/{name}: skipped, {reason}", file=sys.stderr)
                rc = 1
                continue
            if state == "ok":
                print(f"{label}/{name}: ok")
                continue
            try:
                target.path.mkdir(parents=True, exist_ok=True)
            except (FileExistsError, NotADirectoryError):
                print(f"{label}: skills path is not a directory", file=sys.stderr)
                rc = 1
                break
            if state != "missing":
                remove(entry)
            place(entry, name, args.mode, renders.get(name))
            print(f"{label}/{name}: installed ({args.mode}{', rendered' if name in renders else ''})")
    if args.install_hook:
        reconcile_args: list[str] = []
        if args.client != "all":
            reconcile_args += ["--client", args.client]
        if args.mode != "symlink":
            reconcile_args += ["--mode", args.mode]
        if args.home:
            reconcile_args += ["--home", str(home)]
        if args.rig:
            reconcile_args += ["--rig", str(args.rig.expanduser().resolve())]
        if args.render_dir:
            reconcile_args += ["--render-dir", str(args.render_dir.expanduser().resolve())]
        rc |= install_hooks(hooks_dir(args.hooks_dir), reconcile_args)
    return rc


if __name__ == "__main__":
    sys.exit(run())
