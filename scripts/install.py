#!/usr/bin/env python3
"""Install jstack skills into agent clients' user skill folders.

Stdlib only. Links (or copies) each skills/<name> folder into the client's
skills folder. It never puts a binary on $PATH, and uninstall removes only
entries this checkout owns.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO / "skills"
MARKER = ".jstack-install.json"
CLIENTS = ("claude", "codex", "antigravity", "opencode")
# Never touch these names, even if a stray marker or link claims them.
PROTECTED = frozenset({"synced"})

# Sibling skills each skill calls. Resolved transitively.
DEPS: dict[str, tuple[str, ...]] = {
    "full-send": ("sol-loop", "file-pr", "babysit-pr", "leaving-pr-comments", "pr"),
    "full-stop": ("full-send",),
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


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def owns_link(entry: Path) -> bool:
    """True only for entries this checkout installed.

    A symlink must resolve into this repo's skills/ tree. A real folder must
    hold a marker naming this repo. Anything else belongs to the user.
    """
    if entry.name in PROTECTED:
        return False
    if entry.is_symlink():
        try:
            dest = entry.resolve(strict=False)
        except (OSError, RuntimeError):
            return False
        return _within(dest, SKILLS_DIR.resolve())
    marker = entry / MARKER
    if entry.is_dir() and marker.is_file():
        try:
            data = json.loads(marker.read_text())
            source = Path(data["source"]).resolve()
        except (OSError, ValueError, KeyError, TypeError):
            return False
        return source == REPO.resolve()
    return False


def status(entry: Path, name: str, mode: str) -> str:
    src = (SKILLS_DIR / name).resolve()
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
    if data.get("version") != version():
        return "stale"
    return "ok" if mode == "copy" else "mode"


def version() -> str:
    return json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())["version"]


def remove(entry: Path) -> None:
    if entry.is_symlink() or entry.is_file():
        entry.unlink()
    else:
        shutil.rmtree(entry)


def place(entry: Path, name: str, mode: str) -> None:
    src = SKILLS_DIR / name
    if mode == "symlink":
        entry.symlink_to(src.resolve(), target_is_directory=True)
        return
    shutil.copytree(src, entry, symlinks=False)
    marker = {"source": str(REPO.resolve()), "skill": name, "version": version()}
    (entry / MARKER).write_text(json.dumps(marker, indent=2) + "\n")


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
    args = parser.parse_args(argv)
    if args.check and args.uninstall:
        parser.error("--check and --uninstall are exclusive")

    env = dict(os.environ if environ is None else environ)
    if args.home:
        home = args.home.expanduser().resolve()
        env = {}
    else:
        home = Path(env.get("HOME") or Path.home())

    if args.only:
        picked = [s.strip() for s in args.only.split(",") if s.strip()]
        # Uninstall removes only the named skills: other skills may still need their siblings.
        names = resolve(picked, with_deps=not (args.no_deps or args.uninstall))
        added = sorted(set(names) - set(picked))
        if added:
            print(f"adding dependencies: {', '.join(added)}")
    else:
        names = available_skills()

    rc = 0
    for target in targets(home, args.client, env):
        label = f"{target.client}: {target.path}"
        if args.uninstall:
            if not target.path.is_dir():
                continue
            for entry in sorted(target.path.iterdir()):
                if args.only and entry.name not in names:
                    continue
                if owns_link(entry):
                    remove(entry)
                    print(f"{label}/{entry.name}: removed")
            continue
        for name in names:
            entry = target.path / name
            state = status(entry, name, args.mode)
            if args.check:
                print(f"{label}/{name}: {state}")
                rc |= state != "ok"
                continue
            if state == "conflict":
                print(f"{label}/{name}: skipped, not installed by jstack", file=sys.stderr)
                rc = 1
                continue
            if state == "ok":
                print(f"{label}/{name}: ok")
                continue
            target.path.mkdir(parents=True, exist_ok=True)
            if state != "missing":
                remove(entry)
            place(entry, name, args.mode)
            print(f"{label}/{name}: installed ({args.mode})")
    return rc


if __name__ == "__main__":
    sys.exit(run())
