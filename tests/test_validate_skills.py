"""Tests for scripts/validate_skills.py and scripts/check_privacy.py."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"jstack_{name}", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


vs = load("validate_skills")
cp = load("check_privacy")

# Built by concatenation so this file does not trip the scanner itself.
HOME_PATH = "/ho" + "me/alice/projects"
MAC_PATH = "/Us" + "ers/bob/code"
TAILNET = "box.tail1234" + ".ts.net"
CGNAT = "100" + ".100.1.2"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A copy of the files the validator reads."""
    dst = tmp_path / "repo"
    for rel in ("skills", ".agents", ".claude-plugin", ".codex-plugin", ".github/workflows", "scripts"):
        shutil.copytree(ROOT / rel, dst / rel, symlinks=True)
    for rel in ("README.md", "size-budget.json"):
        shutil.copy2(ROOT / rel, dst / rel)
    return dst


def errors(root: Path) -> list[str]:
    return vs.validate(root)


# validate_skills ----------------------------------------------------------


def test_repo_is_valid():
    assert vs.validate(ROOT) == []
    assert len(vs.skill_dirs(ROOT)) == 17


def test_cli_ok():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_skills.py")], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    assert "17 skills valid" in proc.stdout


def test_parser_matches_pyyaml():
    yaml = pytest.importorskip("yaml")
    for d in vs.skill_dirs(ROOT):
        fm, _ = vs.split_frontmatter((d / "SKILL.md").read_text())
        assert vs.parse_frontmatter(fm) == yaml.safe_load(fm), d.name


@pytest.mark.parametrize(
    "fm",
    [
        'name: x\ndescription: "a: b"\n',
        "name: x\ndescription: >-\n  folded\n  text\n",
        "name: x\ndescription: |\n  line one\n  line two\n",
        "name: x\ndescription: 'it''s'\nmetadata:\n  credits:\n    a: b\n",
        "name: x\ndescription: plain # comment\n",
    ],
)
def test_parser_subset_matches_pyyaml(fm: str):
    yaml = pytest.importorskip("yaml")
    assert vs.parse_frontmatter(fm) == yaml.safe_load(fm)


@pytest.mark.parametrize(
    "fm",
    ["name: x\ndescription: a: b\n", "name: x\nname: y\n", "name: [x]\n", "- item\n", 'name: "x\n'],
)
def test_parser_rejects(fm: str):
    with pytest.raises(vs.FrontmatterError):
        vs.parse_frontmatter(fm)


def test_missing_frontmatter(repo: Path):
    (repo / "skills/pr/SKILL.md").write_text("# no frontmatter\n")
    assert any("frontmatter" in e for e in errors(repo))


def test_name_must_match_folder(repo: Path):
    p = repo / "skills/pr/SKILL.md"
    p.write_text(p.read_text().replace("name: pr", "name: prs", 1))
    assert any("must equal folder" in e for e in errors(repo))


def test_empty_description(repo: Path):
    p = repo / "skills/council/SKILL.md"
    p.write_text("---\nname: council\ndescription: \"\"\n---\nbody\n")
    assert any("non-empty" in e for e in errors(repo))


def test_symlink_rejected(repo: Path):
    (repo / "skills/pr/alias.md").symlink_to(repo / "skills/pr/SKILL.md")
    assert any("symlinks are not allowed" in e for e in errors(repo))


def test_link_escape_rejected(repo: Path):
    p = repo / "skills/council/SKILL.md"
    p.write_text(p.read_text() + "\nSee [notes](../../NOTICE.md).\n")
    assert any("leaves skills/council/" in e for e in errors(repo))


def test_link_to_non_dependency_sibling_rejected(repo: Path):
    p = repo / "skills/council/SKILL.md"
    p.write_text(p.read_text() + "\nSee [pr](../pr/SKILL.md).\n")
    assert any("leaves skills/council/" in e for e in errors(repo))


def test_link_to_declared_dependency_allowed():
    # full-stop links ../full-send/SKILL.md upstream; full-send is a declared dependency.
    assert vs.check_links(ROOT / "skills/full-stop", ("full-send",)) == []
    assert vs.check_links(ROOT / "skills/full-stop", ()) != []


def test_absolute_and_broken_links(repo: Path):
    p = repo / "skills/council/SKILL.md"
    p.write_text(p.read_text() + "\n[a](/etc/passwd) [b](missing.md) [c](https://example.com) [d](#top)\n")
    errs = errors(repo)
    assert any("is absolute" in e for e in errs)
    assert any("missing.md does not resolve" in e for e in errs)
    assert not any("example.com" in e or "#top" in e for e in errs)


def test_links_in_code_are_ignored(repo: Path):
    p = repo / "skills/council/SKILL.md"
    p.write_text(p.read_text() + "\n```md\n[x](../../outside.md)\n```\n`[y](../../z.md)`\n")
    assert errors(repo) == []


def test_manifest_version_mismatch(repo: Path):
    p = repo / ".codex-plugin/plugin.json"
    data = json.loads(p.read_text())
    data["version"] = "9.9.9"
    p.write_text(json.dumps(data))
    assert any("manifest versions differ" in e for e in errors(repo))


def test_manifests_share_version():
    assert set(vs.manifest_versions(ROOT).values()) == {"0.2.0"}


def test_pr_body_workflow_must_match(repo: Path):
    p = repo / ".github/workflows/pr-body.yml"
    p.write_bytes(p.read_bytes() + b"\n")
    assert any("byte for byte" in e for e in errors(repo))


def test_root_claude_md_rejected(repo: Path):
    (repo / "CLAUDE.md").write_text("# roster\n")
    assert any("CLAUDE.md" in e for e in errors(repo))


def test_readme_must_list_every_skill(repo: Path):
    p = repo / "README.md"
    p.write_text(p.read_text().replace("`t3-launch-worktrees`", "t3 launch"))
    assert any("t3-launch-worktrees" in e for e in errors(repo))


# size budget --------------------------------------------------------------


def test_budget_file_matches_tree():
    built = vs.build_budget(vs.measure(ROOT))
    on_disk = json.loads((ROOT / "size-budget.json").read_text())
    assert built == on_disk


def test_budget_lists_only_skills_over_a_cap():
    sizes = vs.measure(ROOT)
    grand = json.loads((ROOT / "size-budget.json").read_text())["grandfathered"]
    for name, size in sizes.items():
        over = {m for m in vs.METRICS if size[m] > {"description_bytes": 250, "body_bytes": 6144}[m]}
        assert set(grand.get(name, {})) == over, name


def test_measures_utf8_bytes(repo: Path):
    p = repo / "skills/pr/SKILL.md"
    text = p.read_text()
    p.write_text(text.replace('description: "Use when writing a PR body."', 'description: "é"', 1))
    assert vs.measure(repo)["pr"]["description_bytes"] == 2
    _, body = vs.split_frontmatter(p.read_text())
    assert vs.measure(repo)["pr"]["body_bytes"] == len(body.encode())


def test_growth_past_ceiling_fails(repo: Path):
    p = repo / "skills/epic/SKILL.md"
    p.write_text(p.read_text() + "x\n")
    assert any("epic: body_bytes" in e and "grandfathered ceiling" in e for e in errors(repo))


def test_new_skill_over_cap_fails(repo: Path):
    p = repo / "skills/council/SKILL.md"
    p.write_text(p.read_text() + "y" * 7000 + "\n")
    assert any("council: body_bytes" in e and "> cap 6144" in e for e in errors(repo))


def test_long_description_fails(repo: Path):
    p = repo / "skills/council/SKILL.md"
    _, body = vs.split_frontmatter(p.read_text())
    p.write_text(f"---\nname: council\ndescription: {'z' * 251}\n---\n{body}")
    assert any("council: description_bytes 251 > cap 250" in e for e in errors(repo))


def test_shrink_requires_ratchet(repo: Path):
    p = repo / "skills/sol-loop/SKILL.md"
    p.write_text(p.read_text()[:-10])
    assert any("sol-loop.body_bytes shrank" in e for e in errors(repo))
    assert vs.main(["--root", str(repo), "--write-budget"]) == 0
    assert errors(repo) == []


def test_unknown_grandfathered_skill_fails(repo: Path):
    p = repo / "size-budget.json"
    data = json.loads(p.read_text())
    data["grandfathered"]["ghost"] = {"body_bytes": 9000}
    p.write_text(json.dumps(data))
    assert any("ghost does not exist" in e for e in errors(repo))


def test_ceiling_at_or_below_cap_fails(repo: Path):
    p = repo / "size-budget.json"
    data = json.loads(p.read_text())
    data["grandfathered"]["pr"] = {"body_bytes": 6000}
    p.write_text(json.dumps(data))
    assert any("pr.body_bytes ceiling 6000 is not above the cap" in e for e in errors(repo))


def test_caps_cannot_be_raised(repo: Path):
    p = repo / "size-budget.json"
    data = json.loads(p.read_text())
    data["caps"]["body_bytes"] = 99999
    p.write_text(json.dumps(data))
    assert any("caps.body_bytes must be 6144" in e for e in errors(repo))


# check_privacy ------------------------------------------------------------


@pytest.mark.parametrize("text", [HOME_PATH, MAC_PATH, TAILNET, CGNAT])
def test_markers_detected(text: str):
    found = cp.scan_text(f"see {text} here", "f.md", cp.rules(None))
    assert found and found[0].where == "f.md:1"


@pytest.mark.parametrize(
    "text",
    [
        "/home/<user>/projects",
        "/Users/<user>/code",
        "~/.config/hindsight/sources.json",
        "/home/runner/work",
        "<host>.<tailnet>.ts.net",
        "100.63.1.1",
        "100.128.0.1",
        "1100.100.1.2",
        "/home/$USER/x",
    ],
)
def test_placeholders_allowed(text: str):
    assert cp.scan_text(text, "f.md", cp.rules(None)) == []


@pytest.mark.parametrize(
    "name,bad",
    [
        (".env", True),
        ("config/.env.local", True),
        (".env.example", False),
        ("certs/server.pem", True),
        ("tls.key", True),
        ("id_ed25519.pub", True),
        ("keyboard.md", False),
    ],
)
def test_forbidden_files(name: str, bad: bool):
    assert (cp.forbidden_file(name) is not None) == bad


def test_deny_regex_never_printed(tmp_path: Path):
    repo = git_repo(tmp_path)
    (repo / "notes.md").write_text("codename sekrit-island\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "add notes")
    proc = run_privacy(repo, "--all", deny="sekrit-[a-z]+")
    assert proc.returncode == 1
    out = proc.stdout + proc.stderr
    assert "sekrit" not in out
    assert "private deny pattern" in out
    assert "notes.md:1" in out


def test_invalid_deny_regex(tmp_path: Path):
    repo = git_repo(tmp_path)
    proc = run_privacy(repo, deny="(unclosed")
    assert proc.returncode != 0
    assert "(unclosed" not in proc.stdout + proc.stderr


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout


def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("clean\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "init")
    return repo


def run_privacy(repo: Path, *args: str, deny: str | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "PRIVATE_DENY_REGEX"}
    if deny is not None:
        env["PRIVATE_DENY_REGEX"] = deny
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_privacy.py"), "--root", str(repo), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_history_catches_removed_leak(tmp_path: Path):
    repo = git_repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "doc.md").write_text(f"path {HOME_PATH}\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "leak")
    (repo / "doc.md").write_text("path ~/projects\n")
    git(repo, "commit", "-qam", "fix")
    assert run_privacy(repo).returncode == 0  # tree is clean
    proc = run_privacy(repo, "--range", f"{base}..HEAD")
    assert proc.returncode == 1
    assert "linux home path" in proc.stdout
    assert HOME_PATH not in proc.stdout
    assert run_privacy(repo, "--all").returncode == 1


def test_history_catches_commit_message_and_secret_file(tmp_path: Path):
    repo = git_repo(tmp_path)
    (repo / "server.pem").write_text("x\n")
    git(repo, "add", "-f", "server.pem")
    git(repo, "commit", "-qm", f"deploy to {TAILNET}")
    git(repo, "rm", "-q", "server.pem")
    git(repo, "commit", "-qm", "remove")
    proc = run_privacy(repo, "--all")
    assert proc.returncode == 1
    assert "message:1: tailnet hostname" in proc.stdout
    assert "server.pem: secret file (*.pem)" in proc.stdout


def test_tree_scan_includes_untracked(tmp_path: Path):
    repo = git_repo(tmp_path)
    (repo / "draft.md").write_text(f"ip {CGNAT}\n")
    proc = run_privacy(repo)
    assert proc.returncode == 1
    assert "draft.md:1: CGNAT address" in proc.stdout


def test_this_repo_is_clean():
    proc = run_privacy(ROOT)
    assert proc.returncode == 0, proc.stdout


def test_codex_marketplace_and_empty_version_validated(repo: Path):
    p = repo / ".agents/plugins/marketplace.json"
    data = json.loads(p.read_text())
    data["plugins"][0]["source"]["path"] = "./missing"
    p.write_text(json.dumps(data))
    assert any("source.path" in e for e in errors(repo))
    p.write_text((ROOT / ".agents/plugins/marketplace.json").read_text())
    for rel in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        m = json.loads((repo / rel).read_text())
        m["version"] = ""
        (repo / rel).write_text(json.dumps(m))
    cm = json.loads((repo / ".claude-plugin/marketplace.json").read_text())
    cm["plugins"][0]["version"] = ""
    (repo / ".claude-plugin/marketplace.json").write_text(json.dumps(cm))
    assert any("non-empty" in e for e in errors(repo))


def test_bare_home_paths_and_extended_secret_names_caught():
    assert cp.scan_text("HOME=/ho" + "me/alice\ncd /Us" + "ers/bob", "f.md", cp.rules(None))
    for name in ("id_rsa", "id_ecdsa.pub", "cert.p12", "bundle.pfx", ".netrc", ".npmrc"):
        assert cp.forbidden_file(name) is not None


def test_history_catches_binary_empty_nonascii_merge_plusplus_and_author(tmp_path: Path):
    repo = git_repo(tmp_path)
    # 1. Binary secret + empty .env + non-ASCII .pem + added line starting with "++ "
    (repo / "binary.key").write_bytes(b"\x00\x01\x02binary")
    (repo / ".env").write_bytes(b"")
    (repo / "cl\u00e9.pem").write_text("cert\n")
    (repo / "notes.md").write_text("++ " + HOME_PATH + "\n")
    git(repo, "add", "-f", "binary.key", ".env", "cl\u00e9.pem", "notes.md")
    git(repo, "commit", "-qm", "add leaks")
    git(repo, "rm", "-q", "binary.key", ".env", "cl\u00e9.pem")
    (repo / "notes.md").write_text("clean\n")
    git(repo, "commit", "-qam", "clean up")
    proc = run_privacy(repo, "--all")
    assert proc.returncode == 1
    assert "binary.key: secret file (*.key)" in proc.stdout
    assert ".env: secret file (.env)" in proc.stdout
    assert "cl\u00e9.pem: secret file (*.pem)" in proc.stdout
    assert "notes.md: linux home path" in proc.stdout

    # 2. Merge-introduced leak removed later
    repo2 = git_repo(tmp_path / "m")
    git(repo2, "checkout", "-qb", "side")
    (repo2 / "side.txt").write_text("ok\n")
    git(repo2, "add", ".")
    git(repo2, "commit", "-qm", "side")
    git(repo2, "checkout", "-q", "main")
    (repo2 / "main.txt").write_text("ok\n")
    git(repo2, "add", ".")
    git(repo2, "commit", "-qm", "main")
    git(repo2, "merge", "--no-ff", "--no-commit", "side")
    (repo2 / "evil.txt").write_text(f"merge {TAILNET}\n")
    git(repo2, "add", "evil.txt")
    git(repo2, "commit", "-qm", "merge side")
    git(repo2, "rm", "-q", "evil.txt")
    git(repo2, "commit", "-qm", "drop evil")
    proc2 = run_privacy(repo2, "--all")
    assert proc2.returncode == 1
    assert "tailnet hostname" in proc2.stdout

    # 3. Symlink target leak in tree + trailing-newline PRIVATE_DENY_REGEX + --require-deny
    repo3 = git_repo(tmp_path / "s")
    (repo3 / "badlink").symlink_to(HOME_PATH)
    proc3 = run_privacy(repo3)
    assert proc3.returncode == 1
    assert "badlink (symlink):1: linux home path" in proc3.stdout
    (repo3 / "badlink").unlink()
    (repo3 / "doc.md").write_text("codename moonbase\n")
    assert run_privacy(repo3, "--require-deny").returncode == 1
    assert run_privacy(repo3, "--require-deny", deny="alpha|moonbase\n").returncode == 1
    assert run_privacy(repo3, "--require-deny", deny="alpha\nmoonbase\n").returncode == 1
    assert run_privacy(repo3, "--require-deny", deny="\n").returncode == 1

    # 4. Pathname marker (redacted in output), binary leak, case-insensitive .ts.net, CGNAT sentence end, lone CR, and tag
    repo4 = git_repo(tmp_path / "p")
    bad_dir = repo4 / TAILNET
    bad_dir.mkdir()
    (bad_dir / "note.txt").write_text("clean\n")
    tree_proc = run_privacy(repo4)
    assert tree_proc.returncode == 1
    assert TAILNET not in tree_proc.stdout
    assert "<redacted>" in tree_proc.stdout
    git(repo4, "add", ".")
    git(repo4, "commit", "-qm", "add host folder")
    git(repo4, "rm", "-rq", TAILNET)
    (repo4 / "cr.txt").write_bytes(b"ok\r" + HOME_PATH.encode() + b"\n")
    (repo4 / "blob.bin").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00tEXt" + TAILNET.upper().encode() + b"\n")
    cgnat_ip = "100" + ".84.12.7"
    (repo4 / "sent.txt").write_text(f"ssh to {cgnat_ip}.\n")
    git(repo4, "add", "cr.txt", "blob.bin", "sent.txt")
    git(repo4, "commit", "-qm", "add leaks")
    git(repo4, "rm", "-q", "cr.txt", "blob.bin", "sent.txt")
    git(repo4, "commit", "-qm", "clean")
    git(repo4, "tag", "-a", "v0.0.1-test", "-m", f"release from {HOME_PATH}")
    proc4 = run_privacy(repo4, "--all")
    assert proc4.returncode == 1
    assert "(path): tailnet hostname" in proc4.stdout
    assert TAILNET not in proc4.stdout
    assert "cr.txt: linux home path" in proc4.stdout
    assert "blob.bin: tailnet hostname" in proc4.stdout
    assert "sent.txt: CGNAT address" in proc4.stdout
    assert "tag v0.0.1-test message:2: linux home path" in proc4.stdout


def test_comment_only_description_rejected():
    meta = vs.parse_frontmatter("name: demo\ndescription: # todo")
    assert meta["description"] == ""
