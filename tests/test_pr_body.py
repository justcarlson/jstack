"""Tests for the PR-body validator embedded in skills/pr/templates/pr-body.yml."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "skills" / "pr" / "templates" / "pr-body.yml"
WORKFLOW = ROOT / ".github" / "workflows" / "pr-body.yml"


def extract_validator() -> str:
    text = TEMPLATE.read_text()
    match = re.search(r"python3 - <<'PY'\n(.*?)\n\s*PY\n", text, re.DOTALL)
    assert match, "validator heredoc not found"
    return textwrap.dedent(match.group(1))


def lint(body: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-I", "-c", extract_validator()],
        env={"PR_BODY": body, "PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


VALID = """## Summary

One sentence.

```text
src/
└── thing.py
```

## Evidence

- **Before:** test_x failed
  **After:** test_x passed

## Merge Danger

**Door:** two-way

**Blast Radius:** tiny
"""


def test_template_matches_workflow():
    assert TEMPLATE.read_bytes() == WORKFLOW.read_bytes()


def test_valid_body_passes():
    code, out = lint(VALID)
    assert code == 0, out


def test_two_way_door_passes_and_one_way_passes():
    assert lint(VALID.replace("two-way", "Two-way"))[0] == 0
    assert lint(VALID.replace("two-way", "one-way"))[0] == 0


def test_missing_visual_fails():
    body = VALID.replace("```text\nsrc/\n└── thing.py\n```\n", "")
    code, out = lint(body)
    assert code == 1
    assert "Summary needs a visual" in out


def test_preamble_fails():
    code, out = lint("Hello!\n\n" + VALID)
    assert code == 1
    assert "no preamble" in out


def test_wrong_heading_order_fails():
    body = VALID.replace("## Evidence", "## TMP").replace("## Merge Danger", "## Evidence").replace("## TMP", "## Merge Danger")
    code, out = lint(body)
    assert code == 1
    assert "once each and in that order" in out


def test_placeholder_fails():
    code, out = lint(VALID.replace("tiny", "tiny\n\n<optional: more>"))
    assert code == 1
    assert "Replace template placeholders" in out


@pytest.mark.parametrize("label", ["Before", "After"])
def test_empty_evidence_label_fails(label):
    body = VALID.replace("test_x failed", "").replace("test_x passed", "") if label == "Before" else VALID.replace("test_x passed", "")
    code, out = lint(body)
    assert code == 1
    assert f"**{label}:**" in out
