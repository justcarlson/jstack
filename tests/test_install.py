"""Tests for scripts/install.py."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "install.py"
SKILLS = ROOT / "skills"

spec = importlib.util.spec_from_file_location("jstack_install", SCRIPT)
install = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = install
spec.loader.exec_module(install)

ALL = sorted(p.name for p in SKILLS.iterdir() if (p / "SKILL.md").is_file())


def run(home: Path, *args: str, env: dict[str, str] | None = None) -> int:
    return install.run(["--home", str(home), *args], environ=env or {})


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    (h / ".claude").mkdir(parents=True)
    return h


def entries(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_seventeen_skills_and_deps_exist():
    assert len(ALL) == 17
    for name, deps in install.DEPS.items():
        assert name in ALL
        assert set(deps) <= set(ALL), name


def test_resolve_is_transitive():
    assert install.resolve(["full-stop"]) == sorted(
        {"full-stop", "full-send", "sol-loop", "file-pr", "babysit-pr", "leaving-pr-comments", "pr"}
    )
    assert install.resolve(["hindsight-setup"]) == ["hindsight", "hindsight-setup"]
    assert install.resolve(["full-stop"], with_deps=False) == ["full-stop"]
    epic = install.resolve(["epic"])
    assert {"full-send", "council", "hindsight", "t3-launch-worktrees", "pr"} <= set(epic)


def test_resolve_rejects_unknown():
    with pytest.raises(SystemExit):
        install.resolve(["nope"])


def test_symlink_install_all(home: Path):
    assert run(home, "--client", "claude") == 0
    target = home / ".claude" / "skills"
    assert entries(target) == ALL
    for name in ALL:
        link = target / name
        assert link.is_symlink()
        assert link.resolve() == (SKILLS / name).resolve()
    # Idempotent.
    assert run(home, "--client", "claude") == 0
    assert run(home, "--client", "claude", "--check") == 0


def test_copy_mode_writes_marker(home: Path):
    assert run(home, "--client", "claude", "--mode", "copy", "--only", "council") == 0
    entry = home / ".claude" / "skills" / "council"
    assert entry.is_dir() and not entry.is_symlink()
    assert (entry / "SKILL.md").read_bytes() == (SKILLS / "council" / "SKILL.md").read_bytes()
    marker = json.loads((entry / install.MARKER).read_text())
    assert marker["source"] == str(ROOT.resolve())
    assert marker["skill"] == "council"
    assert marker["version"] == install.version()
    assert run(home, "--client", "claude", "--mode", "copy", "--only", "council", "--check") == 0
    # Switching modes replaces the owned copy with a link.
    assert run(home, "--client", "claude", "--only", "council", "--check") == 1
    assert run(home, "--client", "claude", "--only", "council") == 0
    assert entry.is_symlink()


def test_only_adds_deps(home: Path, capsys):
    assert run(home, "--client", "claude", "--only", "full-send") == 0
    assert entries(home / ".claude" / "skills") == sorted(
        ["full-send", "sol-loop", "file-pr", "babysit-pr", "leaving-pr-comments", "pr"]
    )
    assert "adding dependencies" in capsys.readouterr().out


def test_no_deps(home: Path):
    assert run(home, "--client", "claude", "--only", "full-send", "--no-deps") == 0
    assert entries(home / ".claude" / "skills") == ["full-send"]


def test_check_reports_missing_and_changes_nothing(home: Path, capsys):
    assert run(home, "--client", "claude", "--check", "--only", "pr") == 1
    assert "pr: missing" in capsys.readouterr().out
    assert not (home / ".claude" / "skills").exists()


def test_check_reports_stale_copy(home: Path, capsys):
    run(home, "--client", "claude", "--mode", "copy", "--only", "pr")
    marker = home / ".claude" / "skills" / "pr" / install.MARKER
    data = json.loads(marker.read_text())
    data["version"] = "0.0.0"
    marker.write_text(json.dumps(data))
    assert run(home, "--client", "claude", "--mode", "copy", "--only", "pr", "--check") == 1
    assert "pr: stale" in capsys.readouterr().out
    assert run(home, "--client", "claude", "--mode", "copy", "--only", "pr") == 0
    assert json.loads(marker.read_text())["version"] == install.version()


def test_conflict_is_skipped_not_overwritten(home: Path, tmp_path: Path):
    target = home / ".claude" / "skills"
    target.mkdir(parents=True)
    mine = target / "council"
    mine.mkdir()
    (mine / "SKILL.md").write_text("my own council\n")
    elsewhere = tmp_path / "other-tstack" / "pr"
    elsewhere.mkdir(parents=True)
    (target / "pr").symlink_to(elsewhere)
    assert run(home, "--client", "claude", "--only", "council,pr") == 1
    assert (mine / "SKILL.md").read_text() == "my own council\n"
    assert (target / "pr").resolve() == elsewhere.resolve()


def test_uninstall_keeps_user_folders_and_synced(home: Path, tmp_path: Path):
    target = home / ".claude" / "skills"
    run(home, "--client", "claude")
    run(home, "--client", "claude", "--mode", "copy", "--only", "council", "--no-deps")
    # The user's own entries.
    synced = target / "synced"
    synced.mkdir()
    (synced / "keep.md").write_text("keep\n")
    own = target / "my-skill"
    own.mkdir()
    (own / "SKILL.md").write_text("mine\n")
    other = tmp_path / "elsewhere" / "skill"
    other.mkdir(parents=True)
    (target / "linked-elsewhere").symlink_to(other)
    # A copied folder whose marker names another checkout.
    foreign = target / "foreign-copy"
    foreign.mkdir()
    (foreign / install.MARKER).write_text(json.dumps({"source": str(tmp_path / "fork")}))
    # A bad marker is not ownership.
    broken = target / "bad-marker"
    broken.mkdir()
    (broken / install.MARKER).write_text("{not json")

    assert run(home, "--client", "claude", "--uninstall") == 0
    assert entries(target) == sorted(["synced", "my-skill", "linked-elsewhere", "foreign-copy", "bad-marker"])
    assert (synced / "keep.md").read_text() == "keep\n"


def test_uninstall_never_touches_synced_even_if_it_looks_owned(home: Path):
    target = home / ".claude" / "skills"
    target.mkdir(parents=True)
    (target / "synced").symlink_to(SKILLS / "pr")
    assert not install.owns_link(target / "synced")
    assert run(home, "--client", "claude", "--uninstall") == 0
    assert (target / "synced").is_symlink()


def test_uninstall_only_limits_scope(home: Path):
    run(home, "--client", "claude", "--only", "pr,council", "--no-deps")
    assert run(home, "--client", "claude", "--uninstall", "--only", "pr", "--no-deps") == 0
    assert entries(home / ".claude" / "skills") == ["council"]


def test_uninstall_only_keeps_dependencies(home: Path):
    run(home, "--client", "claude", "--only", "full-stop")
    assert run(home, "--client", "claude", "--uninstall", "--only", "full-stop") == 0
    left = entries(home / ".claude" / "skills")
    assert "full-stop" not in left
    assert "full-send" in left and "pr" in left


def test_owns_link_accepts_dangling_link_into_repo(home: Path):
    target = home / ".claude" / "skills"
    target.mkdir(parents=True)
    (target / "gone").symlink_to(SKILLS / "gone-skill")
    assert install.owns_link(target / "gone")
    run(home, "--client", "claude", "--uninstall")
    assert entries(target) == []


def test_all_detects_clients(tmp_path: Path):
    h = tmp_path / "h"
    (h / ".codex").mkdir(parents=True)
    (h / ".config" / "opencode").mkdir(parents=True)
    assert run(h, "--only", "pr") == 0
    assert (h / ".codex" / "skills" / "pr").is_symlink()
    assert (h / ".config" / "opencode" / "skills" / "pr").is_symlink()
    assert not (h / ".claude").exists()
    assert not (h / ".gemini").exists()


def test_all_with_no_clients_fails(tmp_path: Path):
    h = tmp_path / "empty"
    h.mkdir()
    with pytest.raises(SystemExit):
        run(h, "--only", "pr")


def test_t3_antigravity_detected_without_gemini(tmp_path: Path):
    h = tmp_path / "h"
    provider = h / ".t3" / "userdata" / "providers" / "antigravity" / "abc123"
    (provider / "config").mkdir(parents=True)
    assert install.detected(h, "antigravity", {})
    assert run(h, "--only", "pr") == 0
    assert (h / ".gemini" / "config" / "skills" / "pr").is_symlink()


def test_t3_antigravity_real_skills_folder_gets_installs(tmp_path: Path):
    h = tmp_path / "h"
    (h / ".gemini").mkdir(parents=True)
    real = h / ".t3" / "userdata" / "providers" / "antigravity" / "real" / "config" / "skills"
    real.mkdir(parents=True)
    linked = h / ".t3" / "userdata" / "providers" / "antigravity" / "linked" / "config"
    linked.mkdir(parents=True)
    (h / ".gemini" / "config" / "skills").mkdir(parents=True)
    (linked / "skills").symlink_to(h / ".gemini" / "config" / "skills")
    dirs = install.client_dirs(h, "antigravity", {})
    assert dirs == [h / ".gemini" / "config" / "skills", real]
    assert run(h, "--client", "antigravity", "--only", "pr") == 0
    assert (real / "pr").is_symlink()
    assert (h / ".gemini" / "config" / "skills" / "pr").is_symlink()


def test_env_overrides_without_home(tmp_path: Path):
    h = tmp_path / "h"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    env = {"HOME": str(h), "CODEX_HOME": str(codex_home)}
    assert install.run(["--client", "codex", "--only", "pr"], environ=env) == 0
    assert (codex_home / "skills" / "pr").is_symlink()


def test_check_and_uninstall_are_exclusive(home: Path):
    with pytest.raises(SystemExit):
        run(home, "--check", "--uninstall")


def test_install_sh_wraps_python(tmp_path: Path):
    h = tmp_path / "h"
    (h / ".claude").mkdir(parents=True)
    assert os.access(ROOT / "install.sh", os.X_OK)
    assert os.access(SCRIPT, os.X_OK)
    proc = subprocess.run(
        [str(ROOT / "install.sh"), "--home", str(h), "--client", "claude", "--only", "pr"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert (h / ".claude" / "skills" / "pr").is_symlink()


def test_installs_nothing_on_path(home: Path):
    run(home, "--client", "claude")
    created = {p.relative_to(home).parts[0] for p in home.rglob("*")}
    assert created == {".claude"}
    assert not any("bin" in p.parts for p in home.rglob("*"))


def test_help_lists_flags():
    proc = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    assert "--uninstall" in proc.stdout
