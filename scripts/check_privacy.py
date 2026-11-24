#!/usr/bin/env python3
"""Scan the working tree and git history for secret files and private markers.

Stdlib only. Reports the rule, file and line, never the matched text, so a
public CI log does not repeat what it found. PRIVATE_DENY_REGEX (optional,
from the environment) adds a private pattern; it is never printed.

Usage:
  check_privacy.py                 # working tree only
  check_privacy.py --range A..B    # working tree + commits in A..B
  check_privacy.py --all           # working tree + every commit
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent

# Generic placeholder names that are safe to show in docs.
_SAFE_USERS = r"(?:<[^>/\s]+>|\$USER|\$\{USER\}|user|username|you|me|example|runner|ubuntu)"
MARKERS: list[tuple[str, re.Pattern[str]]] = [
    ("linux home path", re.compile(rf"/home/(?!{_SAFE_USERS}/)[A-Za-z0-9._-]+/")),
    ("macOS home path", re.compile(rf"/Users/(?!{_SAFE_USERS}/|Shared/)[A-Za-z0-9._-]+/")),
    ("tailnet hostname", re.compile(r"(?<![<\w-])(?!example\.ts\.net)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.ts\.net\b")),
    ("CGNAT address", re.compile(r"(?<![\d.])100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}(?![\d.])")),
]
SAFE_ENV_SUFFIXES = (".example", ".sample", ".template")


def forbidden_file(path: str) -> str | None:
    name = PurePosixPath(path).name
    if name.startswith(".env") and not name.endswith(SAFE_ENV_SUFFIXES):
        return "secret file (.env)"
    if name.endswith(".pem"):
        return "secret file (*.pem)"
    if name.endswith(".key"):
        return "secret file (*.key)"
    if name.startswith("id_ed25519"):
        return "secret file (id_ed25519)"
    return None


@dataclass(frozen=True)
class Finding:
    where: str
    rule: str

    def __str__(self) -> str:
        return f"{self.where}: {self.rule}"


def rules(deny: str | None) -> list[tuple[str, re.Pattern[str]]]:
    out = list(MARKERS)
    if deny:
        try:
            out.append(("private deny pattern", re.compile(deny)))
        except re.error:
            raise SystemExit("PRIVATE_DENY_REGEX is not a valid regular expression") from None
    return out


def scan_text(text: str, where: str, active: list[tuple[str, re.Pattern[str]]]) -> list[Finding]:
    found = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for rule, pattern in active:
            if pattern.search(line):
                found.append(Finding(f"{where}:{lineno}", rule))
    return found


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True, errors="replace"
    ).stdout


def scan_tree(root: Path, active: list[tuple[str, re.Pattern[str]]]) -> list[Finding]:
    found = []
    listed = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for rel in sorted(set(filter(None, listed.split("\0")))):
        path = root / rel
        if path.is_symlink() or not path.is_file():
            continue
        if rule := forbidden_file(rel):
            found.append(Finding(rel, rule))
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        found.extend(scan_text(data.decode("utf-8", errors="replace"), rel, active))
    return found


def scan_history(root: Path, rev: list[str], active: list[tuple[str, re.Pattern[str]]]) -> list[Finding]:
    """Scan commit messages, added lines and added file names."""
    out = git(
        root,
        "log",
        *rev,
        "--no-color",
        "--no-ext-diff",
        "--no-renames",
        "--unified=0",
        "--format=%x00commit %H%n%B%x00",
        "-p",
    )
    found = []
    for block in out.split("\0commit ")[1:]:
        sha, _, rest = block.partition("\n")
        short = sha[:12]
        message, _, diff = rest.partition("\0")
        found.extend(scan_text(message, f"commit {short} message", active))
        current = "?"
        for line in diff.splitlines():
            if line.startswith("+++ "):
                current = line[6:] if line.startswith("+++ b/") else line[4:]
                if current != "/dev/null" and (rule := forbidden_file(current)):
                    found.append(Finding(f"commit {short} {current}", rule))
            elif line.startswith("+"):
                for rule, pattern in active:
                    if pattern.search(line[1:]):
                        found.append(Finding(f"commit {short} {current}", rule))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan for secret files and private markers.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--range", help="commit range to scan, such as base..head")
    group.add_argument("--all", action="store_true", help="scan every commit")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    active = rules(os.environ.get("PRIVATE_DENY_REGEX") or None)
    root = args.root.resolve()

    findings = scan_tree(root, active)
    if args.range:
        findings += scan_history(root, [args.range], active)
    elif args.all:
        findings += scan_history(root, ["--all"], active)

    unique = list(dict.fromkeys(str(f) for f in findings))
    for item in unique:
        print(f"::error title=privacy::{item}")
    scope = "tree" + (f" + {args.range}" if args.range else " + all history" if args.all else "")
    deny = "with" if len(active) > len(MARKERS) else "without"
    if unique:
        print(f"privacy: {len(unique)} finding(s) in {scope} ({deny} private pattern)", file=sys.stderr)
        return 1
    print(f"privacy: clean ({scope}, {deny} private pattern)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
