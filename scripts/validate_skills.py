#!/usr/bin/env python3
"""Validate jstack skills, manifests and size budgets. Stdlib only.

Checks:
- every skills/<name>/SKILL.md has frontmatter with name == folder and a
  non-empty description;
- no symlinks under skills/;
- relative Markdown links resolve and stay inside their own skills/<name>/,
  or point into a sibling that scripts/install.py declares as a dependency;
- plugin manifests share one version;
- .github/workflows/pr-body.yml matches skills/pr/templates/pr-body.yml;
- no CLAUDE.md at the repo root;
- every skill appears in README.md;
- description and body sizes stay within size-budget.json.

Run with --write-budget to regenerate size-budget.json from the current tree.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESCRIPTION_CAP = 250
BODY_CAP = 6144
BUDGET_FILE = "size-budget.json"
METRICS = ("description_bytes", "body_bytes")


class FrontmatterError(ValueError):
    pass


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter, body). Body is everything after the closing ---."""
    if not text.startswith("---\n"):
        raise FrontmatterError("file must start with a --- frontmatter line")
    end = re.search(r"(?m)^---[ \t]*\n", text[4:])
    if not end:
        raise FrontmatterError("frontmatter has no closing --- line")
    return text[4 : 4 + end.start()], text[4 + end.end() :]


def _scalar(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    if raw[0] == '"':
        if not raw.endswith('"') or len(raw) < 2:
            raise FrontmatterError(f"unterminated double-quoted value: {raw}")
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise FrontmatterError(f"bad double-quoted value: {raw}") from exc
    if raw[0] == "'":
        if not raw.endswith("'") or len(raw) < 2:
            raise FrontmatterError(f"unterminated single-quoted value: {raw}")
        return raw[1:-1].replace("''", "'")
    if raw[0] in "[{&*!|>%@`":
        raise FrontmatterError(f"unsupported YAML value: {raw}")
    if re.search(r"(^|\s)#", raw):
        raw = re.split(r"(?:^|\s)#", raw, maxsplit=1)[0].rstrip()
    if ": " in raw:
        raise FrontmatterError(f"plain value contains ': ' (quote it): {raw}")
    return raw


def parse_frontmatter(fm: str) -> dict:
    """Parse the YAML subset skills use: mappings, scalars, and > or | blocks."""
    lines = fm.split("\n")
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise FrontmatterError("tabs are not allowed for indentation")
        indent = len(line) - len(line.lstrip(" "))
        match = re.match(r"^\s*([A-Za-z0-9_-]+):(?:\s+(.*))?$", line)
        if not match:
            raise FrontmatterError(f"cannot parse line: {line!r}")
        key, value = match.group(1), match.group(2) or ""
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if key in parent:
            raise FrontmatterError(f"duplicate key: {key}")
        i += 1
        block = re.fullmatch(r"([>|])([+-]?)", value.strip())
        if block:
            style, chomp = block.groups()
            chunk: list[str] = []
            while i < len(lines) and (
                not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip(" ")) > indent
            ):
                chunk.append(lines[i])
                i += 1
            body = [ln.strip() for ln in chunk]
            while body and not body[-1]:
                body.pop()
            if style == ">":
                text = re.sub(r"(?<!\n)\n(?!\n)", " ", "\n".join(body))
                text = re.sub(r"\n(\n+)", r"\1", text)
            else:
                text = "\n".join(body)
            parent[key] = text if chomp == "-" else text + "\n"
        elif value.strip() == "":
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _scalar(value)
    return root


def skill_dirs(root: Path) -> list[Path]:
    return sorted(p for p in (root / "skills").iterdir() if p.is_dir() and not p.name.startswith("."))


def measure(root: Path) -> dict[str, dict[str, int]]:
    sizes = {}
    for d in skill_dirs(root):
        skill_md = d / "SKILL.md"
        if not skill_md.is_file():
            raise FileNotFoundError(f"skills/{d.name}/SKILL.md is missing")
        text = skill_md.read_text(encoding="utf-8")
        fm, body = split_frontmatter(text)
        meta = parse_frontmatter(fm)
        sizes[d.name] = {
            "description_bytes": len(str(meta.get("description", "")).encode("utf-8")),
            "body_bytes": len(body.encode("utf-8")),
        }
    return sizes


def build_budget(sizes: dict[str, dict[str, int]]) -> dict:
    caps = {"description_bytes": DESCRIPTION_CAP, "body_bytes": BODY_CAP}
    grandfathered = {}
    for name, size in sorted(sizes.items()):
        over = {m: size[m] for m in METRICS if size[m] > caps[m]}
        if over:
            grandfathered[name] = over
    return {
        "_comment": (
            "Caps are UTF-8 bytes. Grandfathered ceilings are exact current sizes and only "
            "ratchet down: shrink a skill, then run scripts/validate_skills.py --write-budget."
        ),
        "caps": caps,
        "grandfathered": grandfathered,
    }


def check_budget(root: Path, sizes: dict[str, dict[str, int]]) -> list[str]:
    path = root / BUDGET_FILE
    if not path.is_file():
        return [f"{BUDGET_FILE} is missing; run --write-budget"]
    budget = json.loads(path.read_text())
    caps = budget.get("caps", {})
    errors = []
    for metric, want in (("description_bytes", DESCRIPTION_CAP), ("body_bytes", BODY_CAP)):
        if caps.get(metric) != want:
            errors.append(f"{BUDGET_FILE}: caps.{metric} must be {want}")
    grand = budget.get("grandfathered", {})
    for name in sorted(set(grand) - set(sizes)):
        errors.append(f"{BUDGET_FILE}: grandfathered skill {name} does not exist")
    for name, size in sorted(sizes.items()):
        ceilings = grand.get(name, {})
        for metric in sorted(set(ceilings) - set(METRICS)):
            errors.append(f"{BUDGET_FILE}: {name}.{metric} is not a known metric")
        for metric in METRICS:
            cap = caps.get(metric, 0)
            actual = size[metric]
            ceiling = ceilings.get(metric)
            if ceiling is None:
                if actual > cap:
                    errors.append(f"skills/{name}: {metric} {actual} > cap {cap}")
            elif ceiling <= cap:
                errors.append(f"{BUDGET_FILE}: {name}.{metric} ceiling {ceiling} is not above the cap; remove it")
            elif actual > ceiling:
                errors.append(f"skills/{name}: {metric} {actual} > grandfathered ceiling {ceiling}")
            elif actual < ceiling:
                new = "remove the entry" if actual <= cap else f"lower it to {actual}"
                errors.append(f"{BUDGET_FILE}: {name}.{metric} shrank to {actual}; {new} (--write-budget)")
    return errors


LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
REFDEF = re.compile(r"(?m)^ {0,3}\[[^\]\n]+\]:\s*<?(\S+?)>?(?:\s|$)")


def strip_code(text: str) -> str:
    text = re.sub(r"(?ms)^ {0,3}(```|~~~).*?^ {0,3}\1[^\n]*$", "", text)
    return re.sub(r"`[^`\n]*`", "", text)


def sibling_deps() -> dict[str, tuple[str, ...]]:
    """Dependencies declared in install.py; those siblings are always installed alongside."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from install import DEPS
    finally:
        sys.path.pop(0)
    return DEPS


def check_links(skill: Path, deps: tuple[str, ...] = ()) -> list[str]:
    """Relative links must stay inside the skill, except into a declared sibling dependency."""
    errors = []
    root = skill.resolve()
    allowed = [(skill.parent / dep).resolve() for dep in deps]
    for md in sorted(skill.rglob("*.md")):
        text = strip_code(md.read_text(encoding="utf-8"))
        targets = LINK.findall(text) + REFDEF.findall(text)
        for target in targets:
            if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target) or target.startswith("#"):
                continue
            path = target.split("#", 1)[0].split("?", 1)[0]
            if not path:
                continue
            rel = md.relative_to(skill.parent.parent)
            if path.startswith(("/", "~")):
                errors.append(f"{rel}: link {target} is absolute; use a path inside the skill")
                continue
            dest = (md.parent / path).resolve()
            inside = [r for r in (root, *allowed) if dest == r or r in dest.parents]
            if not inside:
                errors.append(f"{rel}: link {target} leaves skills/{skill.name}/")
            elif not dest.exists():
                errors.append(f"{rel}: link {target} does not resolve")
    return errors


def manifest_versions(root: Path) -> dict[str, str]:
    out = {}
    for rel in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        out[rel] = str(json.loads((root / rel).read_text()).get("version", "")).strip()
    market = json.loads((root / ".claude-plugin/marketplace.json").read_text())
    for i, plugin in enumerate(market.get("plugins", [])):
        if isinstance(plugin, dict):
            out[f".claude-plugin/marketplace.json plugins[{i}]"] = str(plugin.get("version", "")).strip()
    return out


def check_manifests(root: Path) -> list[str]:
    errors: list[str] = []
    try:
        claude_plugin = json.loads((root / ".claude-plugin/plugin.json").read_text())
        codex_plugin = json.loads((root / ".codex-plugin/plugin.json").read_text())
        claude_market = json.loads((root / ".claude-plugin/marketplace.json").read_text())
        codex_market = json.loads((root / ".agents/plugins/marketplace.json").read_text())
    except (OSError, ValueError) as exc:
        return [f"plugin manifest invalid: {exc}"]

    if not claude_market.get("plugins"):
        errors.append(".claude-plugin/marketplace.json: plugins must be non-empty")
    for i, plugin in enumerate(claude_market.get("plugins", [])):
        if not isinstance(plugin, dict):
            errors.append(f".claude-plugin/marketplace.json plugins[{i}]: must be an object")
            continue
        if plugin.get("name") != claude_plugin.get("name"):
            errors.append(f".claude-plugin/marketplace.json plugins[{i}]: name must match .claude-plugin/plugin.json")
        src_path = plugin.get("source")
        if not isinstance(src_path, str) or not src_path or not (root / src_path / ".claude-plugin/plugin.json").is_file():
            errors.append(
                f".claude-plugin/marketplace.json plugins[{i}]: source {src_path!r} must contain .claude-plugin/plugin.json"
            )
    if not codex_market.get("plugins"):
        errors.append(".agents/plugins/marketplace.json: plugins must be non-empty")
    for i, plugin in enumerate(codex_market.get("plugins", [])):
        if not isinstance(plugin, dict):
            errors.append(f".agents/plugins/marketplace.json plugins[{i}]: must be an object")
            continue
        if plugin.get("name") != codex_plugin.get("name"):
            errors.append(f".agents/plugins/marketplace.json plugins[{i}]: name must match .codex-plugin/plugin.json")
        src_obj = plugin.get("source")
        src_path = src_obj.get("path", "") if isinstance(src_obj, dict) else ""
        if not isinstance(src_path, str) or not src_path or not (root / src_path / ".codex-plugin/plugin.json").is_file():
            errors.append(
                f".agents/plugins/marketplace.json plugins[{i}]: source.path {src_path!r} must contain .codex-plugin/plugin.json"
            )
    for rel, data in ((".claude-plugin/plugin.json", claude_plugin), (".codex-plugin/plugin.json", codex_plugin)):
        skills_ref = data.get("skills")
        if not isinstance(skills_ref, str) or not skills_ref.strip() or not (root / skills_ref).is_dir():
            errors.append(f"{rel}: skills path {skills_ref!r} must be a non-empty existing directory")
    icon = root / ".claude-plugin/icon.png"
    if not icon.is_file():
        errors.append(".claude-plugin/icon.png is missing")
    iface = codex_plugin.get("interface")
    logo = iface.get("logo") if isinstance(iface, dict) else None
    if not isinstance(logo, str) or not logo.strip() or not (root / logo).is_file():
        errors.append(f".codex-plugin/plugin.json: interface.logo {logo!r} must be a non-empty existing file")

    versions = manifest_versions(root)
    if any(not v for v in versions.values()):
        errors.append("manifest versions must be non-empty: " + ", ".join(f"{k}={v!r}" for k, v in versions.items()))
    elif len(set(versions.values())) != 1:
        errors.append("manifest versions differ: " + ", ".join(f"{k}={v}" for k, v in versions.items()))
    return errors


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    skills = root / "skills"
    for path in sorted(skills.rglob("*")):
        if path.is_symlink():
            errors.append(f"{path.relative_to(root)}: symlinks are not allowed under skills/")
    deps = sibling_deps()
    skill_names = {d.name for d in skill_dirs(root)}
    for owner, needed in deps.items():
        if owner not in skill_names:
            errors.append(f"scripts/install.py: DEPS key {owner!r} has no folder under skills/")
        for dep in needed:
            if dep not in skill_names:
                errors.append(f"scripts/install.py: DEPS[{owner!r}] references unknown skill {dep!r}")
    readme = (root / "README.md").read_text(encoding="utf-8") if (root / "README.md").is_file() else ""
    for d in skill_dirs(root):
        rel = f"skills/{d.name}/SKILL.md"
        if not (d / "SKILL.md").is_file():
            errors.append(f"{rel}: missing")
            continue
        try:
            fm, _ = split_frontmatter((d / "SKILL.md").read_text(encoding="utf-8"))
            meta = parse_frontmatter(fm)
        except (FrontmatterError, UnicodeDecodeError) as exc:
            errors.append(f"{rel}: {exc}")
            continue
        if meta.get("name") != d.name:
            errors.append(f"{rel}: name {meta.get('name')!r} must equal folder {d.name!r}")
        desc = meta.get("description")
        if not isinstance(desc, str) or not desc.strip():
            errors.append(f"{rel}: description must be a non-empty string")
        errors.extend(check_links(d, deps.get(d.name, ())))
        if f"`{d.name}`" not in readme:
            errors.append(f"README.md: skill `{d.name}` is not listed")
    errors.extend(check_manifests(root))
    template = root / "skills/pr/templates/pr-body.yml"
    workflow = root / ".github/workflows/pr-body.yml"
    if not workflow.is_file() or workflow.read_bytes() != template.read_bytes():
        errors.append(".github/workflows/pr-body.yml must match skills/pr/templates/pr-body.yml byte for byte")
    if (root / "CLAUDE.md").exists():
        errors.append("CLAUDE.md must not exist at the repo root; keep rosters in your own config")
    if not errors:
        errors.extend(check_budget(root, measure(root)))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--write-budget", action="store_true", help=f"rewrite {BUDGET_FILE} and exit")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.write_budget:
        budget = build_budget(measure(root))
        (root / BUDGET_FILE).write_text(json.dumps(budget, indent=2) + "\n")
        print(f"wrote {BUDGET_FILE}: {len(budget['grandfathered'])} grandfathered skill(s)")
        return 0
    errors = validate(root)
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"ok: {len(skill_dirs(root))} skills valid, version {next(iter(manifest_versions(root).values()))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
