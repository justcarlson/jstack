"""Tests for the patched pr-wait behaviors (patches 06, 07, 08)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "skills" / "babysit-pr" / "scripts" / "pr-wait"


@pytest.fixture
def prw(tmp_path, monkeypatch):
    """Load pr-wait as a module, with state in tmp_path and no real sleeping."""
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    loader = importlib.machinery.SourceFileLoader("pr_wait_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    monkeypatch.setattr(module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    return module


def make_watcher(prw, gating_seen=False):
    watcher = prw.Watcher("o/r", 7, "ready", 5)
    watcher.state["gating_seen"] = gating_seen
    watcher.required = {"ci"}
    return watcher


def stub_poll_inputs(prw, watcher, monkeypatch, *, merge_state="CLEAN", reviews=None, check_bucket="pass"):
    pr = {
        "state": "OPEN",
        "url": "https://github.com/o/r/pull/7",
        "headRefOid": "a" * 40,
        "baseRefName": "main",
        "mergeStateStatus": merge_state,
        "author": {"login": "me"},
        "viewer": "me",
        "baseRef": {"target": {"oid": "b" * 40}},
        "comments": {"nodes": []},
        "reviews": {"nodes": list(reviews or [])},
        "reviewThreads": {"nodes": []},
    }
    checks = {"ci": {"name": "ci", "bucket": check_bucket, "link": "https://x/ci", "description": ""}}
    monkeypatch.setattr(watcher, "fetch_pr", lambda: pr)
    monkeypatch.setattr(watcher, "fetch_checks", lambda: checks)
    monkeypatch.setattr(watcher, "behind", lambda *_args: "")


# --- patch 06: a gh call that times out is a transient failure -------------


def test_timeout_retries_then_succeeds(prw, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(kwargs["timeout"])
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(prw.subprocess, "run", fake_run)
    assert prw.gh(["api", "x"]).stdout == "ok"
    assert calls == [120, 120]


def test_repeated_timeouts_raise_transient_error(prw, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(prw.subprocess, "run", fake_run)
    with pytest.raises(prw.GhError) as caught:
        prw.gh(["api", "x"])
    assert caught.value.transient is True
    assert prw.GH_TIMEOUT_SECONDS == 120


def test_required_checks_reraises_transient_error(prw, monkeypatch):
    def boom(_args):
        raise prw.GhError("HTTP 502 Bad Gateway", True)

    monkeypatch.setattr(prw, "gh_lines", boom)
    with pytest.raises(prw.GhError) as caught:
        prw.required_checks("o/r", "main")
    assert caught.value.transient is True


@pytest.mark.parametrize("msg", ["HTTP 404 Not Found", "HTTP 403 Forbidden"])
def test_required_checks_skips_non_transient_errors(prw, monkeypatch, msg):
    def non_transient(_args):
        raise prw.GhError(msg, False)

    monkeypatch.setattr(prw, "gh_lines", non_transient)
    assert prw.required_checks("o/r", "main") == set()


# --- patch 07: a failed first baseline must not save empty state -----------


def test_failed_baseline_does_not_save_state(prw, monkeypatch):
    watcher = make_watcher(prw)
    assert watcher.baseline is True

    def boom():
        raise prw.GhError("HTTP 502", True)

    monkeypatch.setattr(watcher, "poll", boom)
    with pytest.raises(SystemExit) as caught:
        watcher.run()
    assert caught.value.code == 1
    assert not watcher.path.exists()


def test_recorded_baseline_saves_state(prw, monkeypatch):
    watcher = make_watcher(prw)
    assert watcher.baseline is True
    stub_poll_inputs(prw, watcher, monkeypatch, merge_state="DIRTY")
    with pytest.raises(SystemExit) as caught:
        watcher.poll()
    assert caught.value.code == 1
    assert watcher.recorded is True
    assert watcher.path.exists()


# --- patch 08: --until ready with and without a gating bot -----------------


def test_ready_finishes_when_no_gating_bot_ever_reviewed(prw, monkeypatch, capsys):
    watcher = make_watcher(prw, gating_seen=False)
    stub_poll_inputs(prw, watcher, monkeypatch)
    watcher.poll()  # first poll: checks not yet stable
    with pytest.raises(SystemExit) as caught:
        watcher.poll()
    assert caught.value.code == 0
    out = capsys.readouterr().out
    assert "ready on aaaaaaa" in out
    assert "no Greptile or Macroscope on this PR" in out


def test_ready_keeps_waiting_when_gating_bot_was_seen(prw, monkeypatch, capsys):
    watcher = make_watcher(prw, gating_seen=False)
    prior_review = {
        "id": "r1",
        "author": {"login": "greptile-apps"},
        "state": "COMMENTED",
        "commit": {"oid": "0" * 40},
        "body": "earlier review",
        "url": "https://github.com/o/r/pull/7#pullrequestreview-1",
    }
    stub_poll_inputs(prw, watcher, monkeypatch, reviews=[prior_review])
    watcher.poll()
    assert watcher.state["gating_seen"] is True
    watcher.poll()  # no SystemExit: still waiting for the bot to review this head
    assert "ready on" not in capsys.readouterr().out
