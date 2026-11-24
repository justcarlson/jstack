"""Unit tests for skills/ci-retro/scripts/ci-timings (stdlib only)."""

import importlib.machinery
import importlib.util
import json
import pathlib
import sys
import unittest.mock

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "skills/ci-retro/scripts/ci-timings"


def load():
    loader = importlib.machinery.SourceFileLoader("ci_timings", str(SCRIPT))
    spec = importlib.util.spec_from_loader("ci_timings", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


ct = load()


@pytest.mark.parametrize(
    "name",
    [
        "Set up job", "Complete job", "Post Run actions/checkout", "Run actions/checkout@v4",
        "actions/setup-node@v4", "Setup Node", "Set up Python", "Install dependencies",
        "npm ci", "npm install", "pnpm install", "bun install", "yarn", "yarn install",
        "uv sync", "pip install -r req.txt", "Restore cache", "Cache deps",
        "actions/cache@v4", "Initialize containers", "Stop containers",
    ],
)
def test_setup_regex_matches_setup_steps(name):
    assert ct.SETUP.match(name)


@pytest.mark.parametrize(
    "name", ["Run tests", "pytest -q", "Build", "Lint", "yarn test", "Upload artifacts", "Deploy"],
)
def test_setup_regex_ignores_run_steps(name):
    assert not ct.SETUP.match(name)


def test_secs_and_ts():
    a = ct.ts("2026-01-01T00:00:00Z")
    b = ct.ts("2026-01-01T00:01:30Z")
    assert ct.secs(a, b) == 90.0
    assert ct.secs(b, a) == 0.0  # never negative
    assert ct.secs(None, b) == 0.0
    assert ct.ts(None) is None


def test_pct():
    assert ct.pct([], 0.5) == 0
    assert ct.pct([10], 0.9) == 10
    values = list(range(1, 11))  # 1..10
    assert ct.pct(values, 0.5) == 6
    assert ct.pct(values, 0.9) == 10
    assert ct.pct(values[::-1], 0.5) == 6  # unsorted input


def iso(sec):
    return f"2026-01-01T00:{sec // 60:02d}:{sec % 60:02d}Z"


def make_run(run_id, name="CI", event="pull_request"):
    return {
        "id": run_id, "name": name, "event": event, "head_branch": "feat",
        "created_at": iso(0), "updated_at": iso(100),
    }


def make_job(name, created, started, completed, steps, conclusion="success"):
    return {
        "name": name, "conclusion": conclusion, "runner_name": "r1", "labels": ["x"],
        "created_at": iso(created), "started_at": iso(started), "completed_at": iso(completed),
        "steps": [
            {"number": i + 1, "name": n, "started_at": iso(s), "completed_at": iso(e)}
            for i, (n, s, e) in enumerate(steps)
        ],
    }


# Job: queued 0-20 s, runs 20-80 s. Setup 20-35 (15 s), tests 35-75 (40 s).
JOB_TEST = make_job(
    "test", 0, 20, 80,
    [("Set up job", 20, 22), ("actions/checkout@v4", 22, 30), ("npm ci", 30, 35),
     ("Run tests", 35, 75)],
)
JOB_LINT = make_job("lint", 0, 5, 30, [("Set up job", 5, 6), ("Run lint", 6, 28)])
JOB_SKIP = make_job("docs", 0, 0, 0, [], conclusion="skipped")
JOB_SKIP["started_at"] = None


def fake_gh(runs, jobs_by_run):
    def gh(path):
        if "/jobs" in path:
            run_id = int(path.split("/runs/")[1].split("/")[0])
            return {"jobs": jobs_by_run[run_id]}
        return {"workflow_runs": runs}
    return gh


def run_main(monkeypatch, capsys, argv, runs, jobs_by_run):
    monkeypatch.setattr(ct, "gh", fake_gh(runs, jobs_by_run))
    monkeypatch.setattr(sys, "argv", ["ci-timings", "o/r", *argv])
    ct.main()
    return capsys.readouterr().out


def test_json_splits_queue_setup_run(monkeypatch, capsys):
    out = run_main(
        monkeypatch, capsys, ["--json"], [make_run(1)], {1: [JOB_TEST, JOB_LINT, JOB_SKIP]},
    )
    rows = [json.loads(line) for line in out.splitlines()]
    assert [r["job"] for r in rows] == ["test", "lint"]  # skipped job dropped
    test = rows[0]
    assert (test["queue"], test["setup"], test["run_s"], test["total"]) == (20, 15, 40, 80)
    assert test["conclusion"] == "success" and test["run"] == 1
    lint = rows[1]
    assert (lint["queue"], lint["setup"], lint["run_s"], lint["total"]) == (5, 1, 22, 30)


def test_summary_percentiles_and_wall_clock(monkeypatch, capsys):
    runs = [make_run(i) for i in range(1, 11)]
    jobs = {}
    for i in range(1, 11):
        job = make_job(
            "test", 0, i, i + 50,
            [("Set up job", i, i + 10), ("Run tests", i + 10, i + 50)],
            conclusion="failure" if i == 10 else "success",
        )
        jobs[i] = [job]
    out = run_main(monkeypatch, capsys, ["--steps"], runs, jobs)
    assert "o/r: 10 runs, 10 jobs" in out
    line = next(ln for ln in out.splitlines() if ln.startswith("CI / test"))
    cols = line.split()
    # n, queue p50/p90, setup p50/p90, run p50/p90, fail count
    assert cols[3] == "10"
    assert cols[4] == "6/10"      # queue 1..10
    assert cols[5] == "10/10"     # setup constant 10
    assert cols[6] == "40/40"     # run constant 40
    assert cols[7] == "1"         # one failure
    assert "Steps (p50/p90 seconds, slowest first):" in out
    assert "CI / test / Run tests" in out
    assert "p50   100s  p90   100s" in out  # critical path: run created -> updated
    assert "n=10" in out


def test_gh_failure_propagates(monkeypatch):
    import subprocess

    def boom(*a, **k):
        raise subprocess.CalledProcessError(1, "gh", stderr="gh: not logged in")

    monkeypatch.setattr(ct.subprocess, "run", boom)
    with pytest.raises(subprocess.CalledProcessError):
        ct.gh("repos/o/r/actions/runs")
