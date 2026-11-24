"""Tests for skills/hindsight/scripts/hindsight-discover, using synthetic fixtures only."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "hindsight" / "scripts" / "hindsight-discover"
SECRET = "SECRET-PROMPT-sk-test-1234567890-please-ignore-previous-instructions"
DAY = 86400
T0 = 1_760_000_000  # fixed epoch seconds


def touch(path: Path, mtime: float, text: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else json.dumps({"role": "user", "content": SECRET}) + "\n")
    os.utime(path, (mtime, mtime))
    return path


def run(home: Path, *args: str, cfg: Path | None = None, expect: int | None = 0):
    cmd = [sys.executable, str(SCRIPT), "--home", str(home), "--no-gh"]
    cmd += ["--config", str(cfg or home / ".config" / "hindsight" / "sources.json")]
    cmd += list(args)
    env = {k: v for k, v in os.environ.items() if k != "HINDSIGHT_CONFIG"}
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
    if expect is not None:
        assert proc.returncode == expect, proc.stderr + proc.stdout
    return proc


def make_opencode(home: Path, table: str = "session_v2", rows: int = 3) -> Path:
    db = home / ".local" / "share" / "opencode" / "opencode.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute(f"create table {table} (id text primary key, title text, time_created integer)")
    for i in range(rows):
        con.execute(f"insert into {table} values (?, ?, ?)", (f"s{i}", SECRET, (T0 + i * DAY) * 1000))
    con.commit()
    con.close()
    return db


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    h.mkdir()
    return h


@pytest.fixture
def full_home(home: Path) -> Path:
    touch(home / ".claude/projects/proj-a/s1.jsonl", T0)
    touch(home / ".claude/projects/proj-a/s2.jsonl", T0 + DAY)
    touch(home / ".claude/projects/proj-b/s3.jsonl", T0 + 2 * DAY)
    touch(home / ".claude/projects/proj-a/s1/subagents/agent-1.jsonl", T0 + 3 * DAY)
    touch(home / ".codex/sessions/2026/11/01/rollout-2026-11-01T00-00-00-aaa.jsonl", T0 - 5 * DAY)
    touch(home / ".codex/archived_sessions/rollout-2026-10-01T00-00-00-bbb.jsonl.zst", T0 - 9 * DAY)
    touch(home / ".gemini/antigravity-cli/brain/x/transcript.jsonl", T0 + 4 * DAY)
    touch(
        home / ".t3/userdata/providers/antigravity/hash/antigravity-acp/brain/uuid/.system_generated/logs/transcript.jsonl",
        T0 + 5 * DAY,
    )
    make_opencode(home)
    touch(home / ".pi/agent/sessions/--proj--/2026-11-01_abc.jsonl", T0 + DAY)
    return home


def test_empty_home_reports_gaps_not_zero(home: Path):
    out = json.loads(run(home).stdout)
    cov = out["coverage"]
    assert cov["discovered_harnesses"] == []
    assert sorted(cov["missing_harnesses"]) == ["antigravity", "claude_code", "codex", "opencode", "pi"]
    assert cov["total_session_files"] == 0
    assert cov["earliest_utc"] is None and cov["latest_utc"] is None
    assert cov["config_exists"] is False


def test_discovers_all_local_harnesses(full_home: Path):
    out = json.loads(run(full_home).stdout)
    h = out["harnesses"]
    assert h["claude_code"]["parent_sessions"] == 3
    assert h["claude_code"]["subagent_files"] == 1
    assert h["claude_code"]["session_files"] == 4
    assert h["codex"]["session_files"] == 2
    assert h["antigravity"]["session_files"] == 2
    assert h["opencode"]["sessions"] == 3 and h["opencode"]["table"] == "session_v2"
    assert h["pi"]["session_files"] == 1
    cov = out["coverage"]
    assert cov["missing_harnesses"] == []
    assert cov["total_session_files"] == 4 + 2 + 2 + 3 + 1
    assert cov["earliest_utc"] < cov["latest_utc"]
    assert out["gh"] == {"skipped": True}


def test_date_span_uses_mtime_and_db_times(home: Path):
    touch(home / ".pi/agent/sessions/p/a.jsonl", T0)
    touch(home / ".pi/agent/sessions/p/b.jsonl", T0 + 2 * DAY)
    pi = json.loads(run(home).stdout)["harnesses"]["pi"]
    assert pi["earliest_utc"] == "2025-10-09T08:53:20Z"
    assert pi["latest_utc"] == "2025-10-11T08:53:20Z"
    make_opencode(home, rows=2)
    oc = json.loads(run(home).stdout)["harnesses"]["opencode"]
    assert oc["earliest_utc"] == "2025-10-09T08:53:20Z"
    assert oc["latest_utc"] == "2025-10-10T08:53:20Z"


def test_opencode_legacy_session_table(home: Path):
    make_opencode(home, table="session", rows=2)
    oc = json.loads(run(home).stdout)["harnesses"]["opencode"]
    assert oc["table"] == "session" and oc["sessions"] == 2


def test_opencode_unknown_schema_degrades(home: Path):
    db = home / ".local/share/opencode/opencode.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("create table other (x)")
    con.commit()
    con.close()
    out = json.loads(run(home).stdout)
    oc = out["harnesses"]["opencode"]
    assert oc["readable"] is False and oc["error"] == "no_session_table"
    assert "opencode" in out["coverage"]["missing_harnesses"]


def test_opencode_not_a_database_degrades(home: Path):
    db = home / ".local/share/opencode/opencode.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"not sqlite at all" * 50)
    oc = json.loads(run(home).stdout)["harnesses"]["opencode"]
    assert oc["readable"] is False and "error" in oc


def test_opencode_database_is_not_modified(home: Path):
    db = make_opencode(home)
    before = (db.read_bytes(), db.stat().st_mtime_ns)
    run(home)
    assert (db.read_bytes(), db.stat().st_mtime_ns) == before


def test_no_prompt_text_in_output(full_home: Path):
    for extra in ([], ["--human"], ["--check"], ["--check", "--human"]):
        proc = run(full_home, *extra)
        assert SECRET not in proc.stdout
        assert SECRET not in proc.stderr
        assert "sk-test" not in proc.stdout
        assert str(full_home) not in proc.stdout  # paths shown with ~


def test_does_not_open_transcripts(full_home: Path):
    f = full_home / ".claude/projects/proj-a/s1.jsonl"
    f.chmod(0)  # unreadable: discovery must still count it from the file name
    try:
        out = json.loads(run(full_home).stdout)
    finally:
        f.chmod(0o644)
    assert out["harnesses"]["claude_code"]["parent_sessions"] == 3


def test_read_only_without_write_config(full_home: Path):
    run(full_home, "--check")
    assert not (full_home / ".config").exists()


def test_custom_glob_and_exclude(home: Path):
    touch(home / "logs/cursor/a.jsonl", T0)
    touch(home / "logs/cursor/skip-me/b.jsonl", T0)
    proc = run(home, "--extra-glob", "cursor=~/logs/cursor/**/*.jsonl", "--exclude", "*/skip-me/*")
    out = json.loads(proc.stdout)
    assert out["custom_globs"]["cursor"]["session_files"] == 1
    assert out["coverage"]["total_session_files"] == 1


def test_write_config_then_check_passes(full_home: Path):
    touch(full_home / "logs/cursor/a.jsonl", T0)
    cfg = full_home / ".config/hindsight/sources.json"
    out = json.loads(
        run(
            full_home,
            "--write-config",
            "--extra-glob", "cursor=~/logs/cursor/*.jsonl",
            "--exclude", "*/scratch/*",
            "--analytics-mcp", "my-analytics",
            "--privacy", "local-quotes",
        ).stdout
    )
    assert out["wrote_config"].endswith("sources.json")
    data = json.loads(cfg.read_text())
    assert data["version"] == 1
    assert data["harnesses"]["claude_code"] == {"enabled": True}
    assert data["custom_globs"] == {"cursor": "~/logs/cursor/*.jsonl"}
    assert data["exclude_globs"] == ["*/scratch/*"]
    assert data["analytics_mcp"] == "my-analytics"
    assert data["privacy"] == "local-quotes"
    assert oct(cfg.stat().st_mode & 0o777) == "0o600"
    assert not list(cfg.parent.glob(".sources-*.tmp"))

    checked = json.loads(run(full_home, "--check").stdout)
    assert checked["check"]["ok"] is True
    assert "cursor" in checked["check"]["active_sources"]
    assert checked["configured_overlays"]["analytics_mcp"]["name"] == "my-analytics"
    assert checked["coverage"]["config_exists"] is True
    assert checked["privacy"] == "local-quotes"


def test_write_config_preserves_unknown_keys_and_choices(full_home: Path):
    cfg = full_home / ".config/hindsight/sources.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({
        "future_key": {"keep": [1, 2]},
        "harnesses": {"pi": {"enabled": False, "note": "mine"}},
        "exclude_globs": ["*/a/*"],
    }))
    run(full_home, "--write-config", "--exclude", "*/b/*", "--exclude", "*/a/*")
    data = json.loads(cfg.read_text())
    assert data["future_key"] == {"keep": [1, 2]}
    assert data["harnesses"]["pi"] == {"enabled": False, "note": "mine"}
    assert data["exclude_globs"] == ["*/a/*", "*/b/*"]
    out = json.loads(run(full_home).stdout)
    assert "pi" in out["coverage"]["disabled_harnesses"]
    assert "pi" not in out["harnesses"]


def test_write_config_refuses_invalid_json(full_home: Path):
    cfg = full_home / ".config/hindsight/sources.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("{ not json")
    proc = run(full_home, "--write-config", expect=2)
    assert cfg.read_text() == "{ not json"
    assert "refusing" in proc.stderr


def test_write_config_rejects_bad_extra_glob(full_home: Path):
    proc = run(full_home, "--write-config", "--extra-glob", "no-equals-sign", expect=2)
    assert "NAME=GLOB" in proc.stderr
    assert not (full_home / ".config/hindsight/sources.json").exists()


def test_check_without_config_uses_discovery(full_home: Path, tmp_path: Path):
    assert json.loads(run(full_home, "--check").stdout)["check"]["ok"] is True
    empty_home = tmp_path / "empty"
    empty_home.mkdir()
    empty = run(empty_home, "--check", expect=1)
    assert "no readable log source found" in json.loads(empty.stdout)["check"]["errors"]


def test_check_fails_on_invalid_json(full_home: Path):
    cfg = full_home / ".config/hindsight/sources.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("{oops")
    out = json.loads(run(full_home, "--check", expect=1).stdout)
    assert out["check"]["ok"] is False
    assert any("not valid JSON" in e for e in out["check"]["errors"])


def test_check_fails_on_broken_custom_glob(full_home: Path):
    cfg = full_home / ".config/hindsight/sources.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"custom_globs": {"ghost": "~/nowhere/*.jsonl"}}))
    out = json.loads(run(full_home, "--check", expect=1).stdout)
    assert "custom glob matches no files: ghost" in out["check"]["errors"]


def test_check_fails_when_enabled_harness_vanishes(home: Path):
    touch(home / ".pi/agent/sessions/p/a.jsonl", T0)
    cfg = home / ".config/hindsight/sources.json"
    run(home, "--write-config")
    (home / ".pi/agent/sessions/p/a.jsonl").unlink()
    touch(home / "logs/x.jsonl", T0)
    out = json.loads(run(home, "--check", "--extra-glob", "x=~/logs/*.jsonl", expect=1).stdout)
    assert "enabled harness has no readable sessions: pi" in out["check"]["errors"]
    assert cfg.exists()


def test_check_fails_on_missing_queries_ref_and_bad_privacy(full_home: Path):
    cfg = full_home / ".config/hindsight/sources.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"queries_ref": "~/missing.md", "privacy": "shout"}))
    errors = json.loads(run(full_home, "--check", expect=1).stdout)["check"]["errors"]
    assert "queries_ref file does not exist" in errors
    assert any(e.startswith("privacy must be") for e in errors)


def test_check_unknown_harness_and_bad_types(full_home: Path):
    cfg = full_home / ".config/hindsight/sources.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"harnesses": {"emacs": {"enabled": True}}, "custom_globs": ["x"]}))
    errors = json.loads(run(full_home, "--check", expect=1).stdout)["check"]["errors"]
    assert "unknown harness in config: emacs" in errors
    assert any("custom_globs must map" in e for e in errors)


def test_queries_ref_present_is_reported(full_home: Path):
    q = full_home / "queries.md"
    q.write_text("-- saved\n")
    cfg = full_home / ".config/hindsight/sources.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"queries_ref": "~/queries.md", "analytics_mcp": "ch", "t3_mcp": True}))
    out = json.loads(run(full_home, "--check").stdout)
    ov = out["configured_overlays"]
    assert ov["queries_ref"]["exists"] is True
    assert ov["analytics_mcp"]["name"] == "ch"
    assert ov["t3_mcp"]["status"] == "declared"
    assert out["check"]["warnings"]


def test_config_env_var_is_respected(full_home: Path, tmp_path: Path):
    cfg = tmp_path / "elsewhere.json"
    cfg.write_text(json.dumps({"harnesses": {"pi": {"enabled": False}}}))
    env = {**os.environ, "HINDSIGHT_CONFIG": str(cfg)}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--home", str(full_home), "--no-gh"],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert proc.returncode == 0
    assert "pi" in json.loads(proc.stdout)["coverage"]["disabled_harnesses"]


def test_human_summary(full_home: Path):
    text = run(full_home, "--human", "--check").stdout
    assert "Hindsight coverage" in text
    assert "Claude Code: 4 sessions (3 parent, 1 subagent)" in text
    assert "check: ok" in text
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)


def test_script_is_executable_and_stdlib_only():
    assert os.access(SCRIPT, os.X_OK)
    assert SCRIPT.read_text().startswith("#!/usr/bin/env python3\n")
    proc = subprocess.run([sys.executable, "-m", "py_compile", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
