#!/usr/bin/env python3
"""Scan the working tree and git history for secret files and private markers.

Stdlib only. Reports the rule, file and line, never the matched text, so a
public CI log does not repeat what it found. PRIVATE_DENY_REGEX (optional,
from the environment) adds a private pattern; it is never printed.

Usage:
  check_privacy.py                 # working tree only
  check_privacy.py --range A..B    # working tree + commits in A..B
  check_privacy.py --all           # working tree + every commit (including HEAD & tags)
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
_USER_END = r"(?![A-Za-z0-9._-])"
MARKERS: list[tuple[str, re.Pattern[str]]] = [
    ("linux home path", re.compile(rf"/home/(?!{_SAFE_USERS}{_USER_END})[A-Za-z0-9._-]+{_USER_END}")),
    ("macOS home path", re.compile(rf"/Users/(?!{_SAFE_USERS}{_USER_END}|Shared{_USER_END})[A-Za-z0-9._-]+{_USER_END}")),
    ("tailnet hostname", re.compile(r"(?<![<\w-])(?!example\.ts\.net)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.ts\.net\b", re.IGNORECASE)),
    ("CGNAT address", re.compile(r"(?<![\d.])100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}(?!\d|\.\d)")),
]
SAFE_ENV_SUFFIXES = (".example", ".sample", ".template")


def forbidden_file(path: str) -> str | None:
    name = PurePosixPath(path).name
    if name.startswith(".env") and not name.endswith(SAFE_ENV_SUFFIXES):
        return "secret file (.env)"
    for suffix in (".pem", ".key", ".p12", ".pfx"):
        if name.endswith(suffix):
            return f"secret file (*{suffix})"
    for prefix in ("id_ed25519", "id_rsa", "id_ecdsa"):
        if name.startswith(prefix):
            return f"secret file ({prefix})"
    if name in (".netrc", ".npmrc"):
        return f"secret file ({name})"
    return None


@dataclass(frozen=True)
class Finding:
    where: str
    rule: str

    def __str__(self) -> str:
        return f"{self.where}: {self.rule}"


def normalize_deny(raw: str | None) -> str | None:
    if not raw:
        return None
    parts = [line.strip() for line in raw.splitlines() if line.strip()]
    return "|".join(parts) if parts else None


def rules(deny: str | None) -> list[tuple[str, re.Pattern[str]]]:
    out = list(MARKERS)
    cleaned = normalize_deny(deny)
    if cleaned:
        try:
            out.append(("private deny pattern", re.compile(cleaned)))
        except re.error:
            raise SystemExit("PRIVATE_DENY_REGEX is not a valid regular expression") from None
    return out


def scan_text(text: str, where: str, active: list[tuple[str, re.Pattern[str]]]) -> list[Finding]:
    found = []
    for lineno, line in enumerate(text.split("\n"), 1):
        for rule, pattern in active:
            if pattern.search(line):
                found.append(Finding(f"{where}:{lineno}", rule))
    return found


def redact_where(where: str, active: list[tuple[str, re.Pattern[str]]]) -> str:
    safe = where
    for _, pattern in active:
        safe = pattern.sub("<redacted>", safe)
    return safe


def scan_path_markers(rel: str, where: str, active: list[tuple[str, re.Pattern[str]]]) -> list[Finding]:
    found = []
    safe_where = redact_where(where, active)
    for rule, pattern in active:
        if pattern.search(rel):
            found.append(Finding(f"{safe_where} (path)", rule))
    return found


def git_bytes(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", "-C", str(root), *args],
        check=True,
        capture_output=True,
    ).stdout


def git(root: Path, *args: str) -> str:
    return git_bytes(root, *args).decode("utf-8", errors="replace")


def scan_tree(root: Path, active: list[tuple[str, re.Pattern[str]]]) -> list[Finding]:
    found = []
    listed = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for rel in sorted(set(filter(None, listed.split("\0")))):
        path = root / rel
        if rule := forbidden_file(rel):
            found.append(Finding(rel, rule))
        found.extend(scan_path_markers(rel, rel, active))
        if path.is_symlink():
            try:
                target = os.readlink(path)
            except OSError:
                continue
            found.extend(scan_text(target, f"{rel} (symlink)", active))
            continue
        if not path.is_file():
            continue
        data = path.read_bytes()
        text = data.decode("latin-1") if b"\0" in data[:8192] else data.decode("utf-8", errors="replace")
        found.extend(scan_text(text, redact_where(rel, active), active))
    return found


def scan_history_names(root: Path, rev: list[str], active: list[tuple[str, re.Pattern[str]]]) -> list[Finding]:
    """Check every added, modified, copied or renamed path in history (including binary, empty and merge commits)."""
    out = git(
        root,
        "log",
        *rev,
        "-m",
        "--no-renames",
        "--diff-filter=AMCR",
        "--name-only",
        "-z",
        "--format=%x1ecommit %H%x00",
    )
    found = []
    for block in out.split("\x1ecommit ")[1:]:
        parts = block.split("\0")
        short = parts[0].strip()[:12]
        for rel in parts[1:]:
            rel = rel.lstrip("\n")
            if not rel:
                continue
            if rule := forbidden_file(rel):
                found.append(Finding(f"commit {short} {rel}", rule))
            found.extend(scan_path_markers(rel, f"commit {short} {rel}", active))
    return found


def scan_tags(root: Path, active: list[tuple[str, re.Pattern[str]]]) -> list[Finding]:
    raw = git_bytes(
        root,
        "for-each-ref",
        "refs/tags",
        "--format=%(refname:short)%1f%(taggername) %(taggeremail)%0a%(contents)%00",
    )
    found = []
    for block in raw.split(b"\x00"):
        if not block:
            continue
        name_b, sep, body_b = block.partition(b"\x1f")
        if not sep:
            continue
        name = name_b.decode("utf-8", errors="replace").lstrip("\n")
        safe_name = redact_where(name, active)
        body = body_b.decode("utf-8", errors="replace")
        found.extend(scan_path_markers(name, f"tag {safe_name}", active))
        found.extend(scan_text(body, f"tag {safe_name} message", active))
    return found


def scan_history(
    root: Path,
    rev: list[str],
    active: list[tuple[str, re.Pattern[str]]],
    *,
    include_tags: bool = False,
) -> list[Finding]:
    """Scan commit metadata/messages, added lines (including merges), and added/modified file names."""
    found = scan_history_names(root, rev, active)
    raw = git_bytes(
        root,
        "log",
        *rev,
        "-m",
        "--text",
        "--no-color",
        "--no-ext-diff",
        "--no-renames",
        "--unified=0",
        "--format=%x00commit %H%n%an <%ae>%n%cn <%ce>%x1f%B%x00",
        "-p",
    )
    for block in raw.split(b"\x00commit ")[1:]:
        sha_b, _, rest = block.partition(b"\n")
        short = sha_b.decode("utf-8", errors="replace")[:12]
        header_and_msg_b, _, diff_b = rest.partition(b"\x00")
        meta_b, _, message_b = header_and_msg_b.partition(b"\x1f")
        found.extend(scan_text(meta_b.decode("utf-8", errors="replace"), f"commit {short} metadata", active))
        found.extend(scan_text(message_b.decode("utf-8", errors="replace"), f"commit {short} message", active))
        current = "?"
        in_hunk = False
        for raw_line in diff_b.split(b"\n"):
            line = raw_line.decode("utf-8", errors="replace")
            if line.startswith("diff --git "):
                in_hunk = False
                current = "?"
            elif not in_hunk and line.startswith("+++ "):
                current = line[6:] if line.startswith("+++ b/") else line[4:]
            elif line.startswith("@@ "):
                in_hunk = True
            elif in_hunk and line.startswith("+"):
                added = line[1:]
                for rule, pattern in active:
                    if pattern.search(added):
                        found.append(Finding(f"commit {short} {current}", rule))
    if include_tags:
        found.extend(scan_tags(root, active))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan for secret files and private markers.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--range", help="commit range to scan, such as base..head")
    group.add_argument("--all", action="store_true", help="scan every commit")
    parser.add_argument(
        "--require-deny",
        action="store_true",
        help="fail if PRIVATE_DENY_REGEX is unset or empty",
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    deny = normalize_deny(os.environ.get("PRIVATE_DENY_REGEX"))
    if args.require_deny and not deny:
        print("::error title=privacy::PRIVATE_DENY_REGEX is required but unset", file=sys.stderr)
        return 1
    active = rules(deny)
    root = args.root.resolve()

    findings = scan_tree(root, active)
    if args.range:
        findings += scan_history(root, [args.range], active)
    elif args.all:
        findings += scan_history(root, ["--all", "HEAD"], active, include_tags=True)

    unique = list(dict.fromkeys(str(f) for f in findings))
    for item in unique:
        print(f"::error title=privacy::{item}")
    scope = "tree" + (f" + {args.range}" if args.range else " + all history" if args.all else "")
    deny_label = "with" if len(active) > len(MARKERS) else "without"
    if unique:
        print(f"privacy: {len(unique)} finding(s) in {scope} ({deny_label} private pattern)", file=sys.stderr)
        return 1
    print(f"privacy: clean ({scope}, {deny_label} private pattern)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
