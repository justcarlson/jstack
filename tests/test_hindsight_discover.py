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
NOW = T0 + 6 * DAY  # fixed "now": every fixture below sits inside the 30-day window


def touch(path: Path, mtime: float, text: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else json.dumps({"role": "user", "content": SECRET}) + "\n")
    os.utime(path, (mtime, mtime))
    return path


def run(home: Path, *args: str, cfg: Path | None = None, expect: int | None = 0):
    cmd = [sys.executable, str(SCRIPT), "--home", str(home), "--no-gh"]
    if "--now" not in args:
        cmd += ["--now", str(NOW)]
    cmd += ["--config", str(cfg or home / ".config" / "hindsight" / "sources.json")]
    cmd += list(args)
    env = {k: v for k, v in os.environ.items() if k != "HINDSIGHT_CONFIG"}
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True, env=env, timeout=60)
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
    touch(home / ".gemini/antigravity-cli/brain/x/.system_generated/logs/transcript.jsonl", T0 + 4 * DAY)
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
        check=False, capture_output=True, text=True, env=env, timeout=60,
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
    proc = subprocess.run([sys.executable, "-m", "py_compile", str(SCRIPT)], check=False, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_opencode_path_with_hash_stays_read_only(tmp_path: Path):
    special_home = tmp_path / "home#1"
    special_home.mkdir()
    make_opencode(special_home, rows=2)
    before = sorted(p.name for p in tmp_path.iterdir())
    out = json.loads(run(special_home).stdout)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert after == before
    assert out["harnesses"]["opencode"]["readable"] is True
    assert out["harnesses"]["opencode"]["sessions"] == 2


def test_opencode_bad_timestamps_degrade_gracefully(home: Path):
    db = home / ".local" / "share" / "opencode" / "opencode.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("create table session_v2 (id text primary key, time_created text)")
    con.execute("insert into session_v2 values ('s1', 'not-a-number')")
    con.execute("insert into session_v2 values ('s2', '9999999999999999999999')")
    con.commit()
    con.close()
    oc = json.loads(run(home).stdout)["harnesses"]["opencode"]
    assert oc["readable"] is True
    # Rows with no usable date cannot be shown to sit in the window: not counted.
    assert oc["sessions"] == 0 and oc["excluded_out_of_window_or_undated"] == 2
    assert oc["earliest_utc"] is None and oc["latest_utc"] is None


def test_opencode_locked_db_degrades_and_human_shows_unreadable(home: Path):
    db = make_opencode(home, rows=2)
    locker = sqlite3.connect(db, isolation_level=None)
    locker.execute("BEGIN EXCLUSIVE")
    try:
        out = json.loads(run(home).stdout)
        oc = out["harnesses"]["opencode"]
        assert oc["found"] is True and oc["readable"] is False
        assert "error" in oc
        human_out = run(home, "--human").stdout
        assert "[x] OpenCode" not in human_out
        assert "[!] OpenCode: unreadable (" in human_out
    finally:
        locker.execute("ROLLBACK")
        locker.close()


def test_tilde_path_boundary_and_queries_ref_redaction(tmp_path: Path):
    user_home = tmp_path / "user"
    sibling = tmp_path / "user-other"
    user_home.mkdir()
    sibling.mkdir()
    q = user_home / "queries.md"
    q.write_text("-- saved\n")
    cfg = sibling / "sources.json"
    cfg.write_text(json.dumps({"queries_ref": str(q)}))
    out = json.loads(run(user_home, cfg=cfg).stdout)
    assert out["config_path"] == str(cfg)
    assert out["configured_overlays"]["queries_ref"] == {"exists": True, "path": "~/queries.md"}


def test_extra_glob_validated_without_write_config_and_non_dict_harness_rejected(full_home: Path):
    proc = run(full_home, "--extra-glob", "missing-equals", expect=2)
    assert "NAME=GLOB" in proc.stderr
    cfg = full_home / ".config/hindsight/sources.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"harnesses": {"pi": False}}))
    errors = json.loads(run(full_home, "--check", expect=1).stdout)["check"]["errors"]
    assert "harness config entry must be an object: pi" in errors


# --- Google Workspace AI Tools Addendum 2b, 2c, 2f -------------------------------

WORKSPACE_NAMES = [
    "gmail",
    "mcp__claude_ai_Gmail__search_threads",
    "google-calendar",
    "google_drive",
    "https://gmailmcp.googleapis.com/mcp/v1",
    "calendarmcp.googleapis.com",
    "gmailmcp",
    "google-docs",
    "google-sheets",
    "google-slides",
    "google_tasks",
    "google-contacts",
    "drivemcp",
    "docsmcp",
    "sheetsmcp",
    "slidesmcp",
    "tasksmcp",
    "workspacemcp",
    "https://people.googleapis.com/v1/people/me",
    "https://drivemcp.googleapis.com/mcp/v1",
    "gwscli",
    "GWSCLI",
]


def jsonl(path: Path, events: list[dict], mtime: float = NOW - DAY) -> Path:
    return touch(path, mtime, "".join(json.dumps(e) + "\n" for e in events))


def filter_run(home: Path, f: Path, *extra: str, expect: int | None = None):
    cmd = [sys.executable, str(SCRIPT), "--filter-jsonl", str(f), "--now", str(NOW), *extra]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=60)
    if expect is not None:
        assert proc.returncode == expect, proc.stderr + proc.stdout
    return proc


def test_filter_passes_clean_in_window_session(home: Path):
    events = [{"role": "user", "content": "fix the lint error"}, {"role": "assistant", "content": "done"}]
    f = jsonl(home / "s.jsonl", events)
    proc = filter_run(home, f, expect=0)
    assert [json.loads(x) for x in proc.stdout.splitlines()] == events


@pytest.mark.parametrize("name", WORKSPACE_NAMES)
def test_filter_drops_whole_session_with_workspace_tool_call(home: Path, name: str):
    f = jsonl(
        home / "s.jsonl",
        [
            {"role": "user", "content": "clean first line"},
            {"type": "tool_use", "name": name, "input": {"q": "x"}},
            {"role": "assistant", "content": "clean last line"},
        ],
    )
    proc = filter_run(home, f, expect=3)
    assert proc.stdout == ""  # nothing from a tainted session, not even the clean lines
    assert "clean first line" not in proc.stdout + proc.stderr


@pytest.mark.parametrize("name", ["gmail", "google_drive_search", "gwscli"])
def test_filter_catches_taint_in_tool_output_and_nested_values(home: Path, name: str):
    f = jsonl(home / "a.jsonl", [{"role": "tool", "content": [{"text": f"ran {name} ok"}]}])
    filter_run(home, f, expect=3)
    g = jsonl(home / "b.jsonl", [{"a": {"b": [{"server": name}]}}])
    filter_run(home, g, expect=3)


def test_filter_catches_json_escaped_and_non_json_lines(home: Path):
    f = jsonl(home / "a.jsonl", [{"x": "ok"}])
    f.write_text('{"name": "g\\u006dail"}\n')  # JSON escape hides the word from a raw scan
    os.utime(f, (NOW - DAY, NOW - DAY))
    filter_run(home, f, expect=3)
    g = home / "b.jsonl"
    g.write_text("not json, but uses gwscli here\n")
    os.utime(g, (NOW - DAY, NOW - DAY))
    filter_run(home, g, expect=3)


def test_filter_is_case_insensitive(home: Path):
    f = jsonl(home / "a.jsonl", [{"name": "Google_Calendar_Agenda"}])
    filter_run(home, f, expect=3)


def test_filter_drops_workspace_named_path(home: Path):
    f = jsonl(home / "google-drive-session.jsonl", [{"x": "ok"}])
    filter_run(home, f, expect=3)


def test_filter_does_not_overmatch_plain_google_and_mail(home: Path):
    f = jsonl(home / "a.jsonl", [{"content": "search google for email etiquette, use mail(1)"}])
    filter_run(home, f, expect=0)


def test_filter_drops_session_outside_30_days(home: Path):
    old = jsonl(home / "old.jsonl", [{"x": "ok"}], mtime=NOW - 31 * DAY)
    proc = filter_run(home, old, expect=4)
    assert proc.stdout == ""
    edge = jsonl(home / "edge.jsonl", [{"x": "ok"}], mtime=NOW - 29 * DAY)
    filter_run(home, edge, expect=0)


def test_filter_lookback_cannot_exceed_30_days(home: Path):
    old = jsonl(home / "old.jsonl", [{"x": "ok"}], mtime=NOW - 45 * DAY)
    for bad in ("31", "365", "0", "-1", "nan"):
        proc = filter_run(home, old, "--lookback-days", bad)
        assert proc.returncode == 2, bad
    filter_run(home, old, "--lookback-days", "7", expect=4)


def test_filter_reads_gzip_sessions(home: Path):
    import gzip

    f = home / "s.jsonl.gz"
    with gzip.open(f, "wt") as fh:
        fh.write(json.dumps({"name": "gwscli"}) + "\n")
    os.utime(f, (NOW - DAY, NOW - DAY))
    filter_run(home, f, expect=3)


def test_filter_missing_file_is_usage_error(home: Path):
    filter_run(home, home / "missing.jsonl", expect=2)


def test_discovery_skips_old_sessions(home: Path):
    touch(home / ".pi/agent/sessions/p/new.jsonl", NOW - DAY)
    touch(home / ".pi/agent/sessions/p/old.jsonl", NOW - 31 * DAY)
    out = json.loads(run(home).stdout)
    assert out["harnesses"]["pi"]["session_files"] == 1
    assert out["coverage"]["lookback_days"] == 30
    assert out["coverage"]["earliest_utc"] == out["coverage"]["latest_utc"]


def test_discovery_skips_workspace_named_paths(home: Path):
    touch(home / ".pi/agent/sessions/p/a.jsonl", NOW - DAY)
    touch(home / ".pi/agent/sessions/gmail-triage/b.jsonl", NOW - DAY)
    touch(home / ".pi/agent/sessions/p/google_drive_x.jsonl", NOW - DAY)
    touch(home / "logs/cursor/gwscli.jsonl", NOW - DAY)
    touch(home / "logs/cursor/ok.jsonl", NOW - DAY)
    out = json.loads(run(home, "--extra-glob", "cursor=~/logs/cursor/*.jsonl").stdout)
    assert out["harnesses"]["pi"]["session_files"] == 1
    assert out["custom_globs"]["cursor"]["session_files"] == 1


def test_discovery_lookback_is_capped_and_validated(home: Path):
    touch(home / ".pi/agent/sessions/p/a.jsonl", NOW - DAY)
    run(home, "--lookback-days", "31", expect=2)
    run(home, "--lookback-days", "0", expect=2)
    out = json.loads(run(home, "--lookback-days", "7").stdout)
    assert out["coverage"]["lookback_days"] == 7


def test_discovery_opencode_rows_filtered_by_window(home: Path):
    db = home / ".local/share/opencode/opencode.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("create table session_v2 (id text primary key, time_created integer)")
    con.execute("insert into session_v2 values ('new', ?)", ((NOW - DAY) * 1000,))
    con.execute("insert into session_v2 values ('old', ?)", ((NOW - 40 * DAY) * 1000,))
    con.commit()
    con.close()
    oc = json.loads(run(home).stdout)["harnesses"]["opencode"]
    assert oc["sessions"] == 1 and oc["excluded_out_of_window_or_undated"] == 1


def test_human_summary_states_window(full_home: Path):
    assert "last 30 days" in run(full_home, "--human").stdout
