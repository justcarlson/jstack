#!/usr/bin/env python3
"""Build and verify a mechanical proof packet. Stdlib only.

A packet is `<dir>/pack.json` (default dir: .proof) plus logs under `<dir>/logs/`.
Every record carries the git HEAD it was made at, so a packet goes stale when
the branch moves. Secrets are redacted before anything is stored.

Commands:
  init     start a packet for a task and required level (L0-L4)
  run      run one command, record argv, exit code, timing, HEAD and a log hash
  attach   record an artifact file (size, sha256, surface, level)
  block    record a blocked surface; refused until the rig's lanes are exhausted
  verify   re-check every record against disk and HEAD; --markdown for a PR

Exit codes: 0 ok, 1 verify failed, 2 usage or state error, 3 redaction gate
refused an artifact, 4 block refused as unexhausted. `run` returns the exit code
of the command it ran.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = "jstack.proof/1"
LEVELS = ("L0", "L1", "L2", "L3", "L4")
# Captures of these surfaces can show credentials, codes or private windows.
GATED_SURFACES = frozenset({"auth", "native_gui", "vnc", "desktop"})
# Blockers an agent must never work around: stop and ask the user.
GATE_CLASSES = ("captcha", "anti-bot", "2fa", "access-denied", "approval")
BLOCK_CLASSES = ("physical", "other", *GATE_CLASSES)
SURFACE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
REDACTED = "[REDACTED]"

TOKEN_PATTERNS = [
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{6,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"),
]
URL_USERINFO = re.compile(r"(://)[^/\s@]+@")
BEARER = re.compile(r"(?i)\bbearer\s+[^\s\"']+")
KEY_VALUE = re.compile(
    r"""(?i)(["']?)\b([A-Za-z0-9_-]*(?:password|passwd|secret|token|api[_-]?key|authorization))\b\1(\s*[:=]\s*)(?:(["'])(?:\\.|(?!\4).)*\4|([^\s"',;&}\]]+))"""
)
# Keep public packets free of the machine's identity.
HOME_PATH = re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+")
TAILNET = re.compile(r"\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.ts\.net\b", re.IGNORECASE)
CGNAT = re.compile(r"(?<![\d.])100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}(?!\d)")
ENV_SECRET = re.compile(
    r"(?i)^([A-Za-z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|CREDENTIAL|PRIVATE_?KEY|COOKIE)[A-Za-z0-9_]*)=(.*)$"
)
SECRET_WORDS = frozenset(
    {"token", "password", "passwd", "pass", "secret", "apikey", "authorization", "cookie", "bearer", "credential", "credentials", "auth"}
)


def redact_text(text: str) -> str:
    for pattern in TOKEN_PATTERNS:
        text = pattern.sub(REDACTED, text)
    text = URL_USERINFO.sub(rf"\1{REDACTED}@", text)
    text = BEARER.sub(f"Bearer {REDACTED}", text)
    text = KEY_VALUE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(1)}{m.group(3)}{m.group(4) or ''}{REDACTED}{m.group(4) or ''}",
        text,
    )
    text = HOME_PATH.sub("~", text)
    text = TAILNET.sub("<tailnet-host>", text)
    return CGNAT.sub("<cgnat-ip>", text)


def secret_flag(flag: str) -> bool:
    parts = set(re.split(r"[-_]+", flag.lstrip("-").lower()))
    return bool(
        parts & SECRET_WORDS
        or {"api", "key"} <= parts
        or {"private", "key"} <= parts
    )


def redact_argv(argv: list[str]) -> list[str]:
    out: list[str] = []
    hide_next = False
    for arg in argv:
        if hide_next and not arg.startswith("-"):
            out.append(REDACTED)
            hide_next = False
            continue
        hide_next = False
        pair = re.match(r"^(--?[A-Za-z0-9_-]+)=(.*)$", arg, re.DOTALL)
        if pair and secret_flag(pair.group(1)):
            out.append(f"{pair.group(1)}={REDACTED}")
            continue
        if arg.startswith("-") and secret_flag(arg):
            out.append(redact_text(arg))
            hide_next = True
            continue
        env = ENV_SECRET.match(arg)
        if env:
            out.append(f"{env.group(1)}={REDACTED}")
            continue
        out.append(redact_text(arg))
    return out


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git_head(repo: Path, override: str | None) -> str | None:
    if override:
        return override
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = proc.stdout.strip()
    return sha if proc.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", sha) else None


def detect_visibility(repo: Path) -> str:
    """public, private or unknown. Unknown is treated as public by the redaction gate."""
    try:
        proc = subprocess.run(
            ["gh", "repo", "view", "--json", "isPrivate", "--jq", ".isPrivate"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    answer = proc.stdout.strip()
    if proc.returncode == 0 and answer in ("true", "false"):
        return "private" if answer == "true" else "public"
    return "unknown"


def default_rig(env: dict[str, str] | None = None) -> Path:
    env = dict(os.environ if env is None else env)
    base = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME") or Path.home()) / ".config")
    return Path(base) / "jstack" / "rig.json"


def rig_lanes(rig_path: Path | None, surface: str) -> list[str]:
    """Lanes the rig configures for a surface. Empty when there is no rig or no lane."""
    path = rig_path or default_rig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        tools = data["lanes"][surface]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    return [t for t in tools if isinstance(t, str)] if isinstance(tools, list) else []


class Pack:
    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.file = directory / "pack.json"
        self.data: dict = {}

    def load(self) -> dict:
        try:
            self.data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise SystemExit(f"error: no readable packet at {self.file}; run init first") from None
        if not isinstance(self.data, dict) or self.data.get("schema") != SCHEMA:
            raise SystemExit(f"error: {self.file} is not a {SCHEMA} packet")
        return self.data

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".pack.", suffix=".tmp", dir=self.dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2, sort_keys=True)
                fh.write("\n")
            os.replace(tmp, self.file)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def next_id(self, prefix: str, key: str) -> str:
        return f"{prefix}{len(self.data.get(key, [])) + 1}"

    def rel(self, path: Path) -> str:
        return os.path.relpath(path.resolve(), self.dir.resolve().parent)

    def resolve(self, rel: str) -> Path:
        return (self.dir.resolve().parent / rel).resolve()


def cmd_init(args: argparse.Namespace, pack: Pack) -> int:
    if pack.file.exists() and not args.force:
        print(f"error: {pack.file} exists; pass --force to start over", file=sys.stderr)
        return 2
    visibility = args.visibility if args.visibility != "auto" else detect_visibility(args.repo)
    pack.data = {
        "schema": SCHEMA,
        "task": redact_text(args.task),
        "created": now(),
        "head_sha": git_head(args.repo, args.head),
        "required_level": args.level,
        "visibility": visibility,
        "steps": [],
        "artifacts": [],
        "blocks": [],
    }
    pack.save()
    print(f"packet started: {pack.file} (level {args.level}, repo {visibility}, head {short(pack.data['head_sha'])})")
    return 0


def cmd_run(args: argparse.Namespace, pack: Pack) -> int:
    pack.load()
    argv = list(args.cmd)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print("error: run needs a command after --", file=sys.stderr)
        return 2
    label = args.label or re.sub(r"[^A-Za-z0-9._-]+", "-", Path(argv[0]).name)[:40] or "step"
    step_id = pack.next_id("s", "steps")
    head = git_head(args.repo, args.head)
    started = now()
    t0 = time.monotonic()
    timed_out = False
    error = None
    try:
        proc = subprocess.run(
            argv, cwd=args.cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=args.timeout, check=False
        )
        code, raw = proc.returncode, proc.stdout
    except subprocess.TimeoutExpired as exc:
        code, raw, timed_out = 124, exc.stdout or b"", True
    except OSError as exc:
        code, raw, error = 127, b"", exc.__class__.__name__
    text = redact_text(raw.decode("utf-8", errors="replace"))
    logs = pack.dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    safe_label = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip(".-")[:40] or "step"
    log_path = logs / f"{len(pack.data['steps']) + 1:03d}-{safe_label}.log"
    log_path.write_text(text, encoding="utf-8")
    step = {
        "id": step_id,
        "label": label,
        "level": args.level,
        "argv": redact_argv(argv),
        "exit_code": code,
        "head_sha": head,
        "started": started,
        "finished": now(),
        "duration_s": round(time.monotonic() - t0, 2),
        "log": pack.rel(log_path),
        "log_sha256": sha256_file(log_path),
        "output_bytes": log_path.stat().st_size,
        "allow_empty": bool(args.allow_empty),
        "timed_out": timed_out,
    }
    if error:
        step["error"] = error
    pack.data["steps"].append(step)
    pack.save()
    sys.stdout.write(text)
    print(f"[proof-pack] {step_id} {label}: exit {code}, {step['output_bytes']} bytes logged", file=sys.stderr)
    return code


def cmd_attach(args: argparse.Namespace, pack: Pack) -> int:
    if not SURFACE_RE.fullmatch(args.surface):
        print(f"error: invalid surface {args.surface!r}; use lowercase letters, digits, hyphens or underscores", file=sys.stderr)
        return 2
    data = pack.load()
    path = Path(args.path)
    if not path.is_file():
        print(f"error: {path.name} is not a file", file=sys.stderr)
        return 2
    size = path.stat().st_size
    if size == 0:
        print(f"error: {path.name} is empty", file=sys.stderr)
        return 2
    if args.surface in GATED_SURFACES and data.get("visibility") != "private" and not args.redacted:
        print(
            f"refused: {args.surface} captures can show credentials or private windows, and this repo is "
            f"{data.get('visibility', 'unknown')}. Redact the file, then attach with --redacted.",
            file=sys.stderr,
        )
        return 3
    seq = int(data.get("seq", 0)) + 1
    data["seq"] = seq
    art = {
        "id": pack.next_id("a", "artifacts"),
        "seq": seq,
        "path": pack.rel(path),
        "sha256": sha256_file(path),
        "bytes": size,
        "surface": args.surface,
        "level": args.level,
        "kind": args.kind,
        "redacted": bool(args.redacted),
        "head_sha": git_head(args.repo, args.head),
        "added": now(),
    }
    if args.note:
        art["note"] = redact_text(args.note)
    data["artifacts"].append(art)
    pack.save()
    print(f"attached {art['id']}: {path.name} ({size} bytes, sha256 {art['sha256'][:12]}, {args.surface} {args.level})")
    return 0


def exhaustion_gaps(surface: str, tried: dict[str, str], lanes: list[str]) -> list[str]:
    """Reasons a block is not yet exhausted. Empty means every lane was tried with evidence."""
    gaps = [f"lane {lane} not tried" for lane in lanes if not tried.get(lane)]
    if not lanes and len(tried) < 2:
        gaps.append("no rig lanes for this surface; log at least two distinct methods tried")
    return gaps


def cmd_block(args: argparse.Namespace, pack: Pack) -> int:
    if not SURFACE_RE.fullmatch(args.surface):
        print(f"error: invalid surface {args.surface!r}; use lowercase letters, digits, hyphens or underscores", file=sys.stderr)
        return 2
    data = pack.load()
    tried: dict[str, str] = {}
    for item in args.tried or []:
        lane, sep, evidence = item.partition("=")
        if not sep or not lane.strip() or not evidence.strip():
            print("error: --tried must look like LANE=EVIDENCE", file=sys.stderr)
            return 2
        tried[lane.strip()] = redact_text(evidence.strip())
    gate = args.cls in GATE_CLASSES
    if args.human_only and args.cls != "physical" and not gate:
        print("error: --human-only is for physical blockers (touch, biometrics, presence)", file=sys.stderr)
        return 2
    lanes = rig_lanes(args.rig, args.surface)
    if not gate:
        gaps = exhaustion_gaps(args.surface, tried, lanes)
        if gaps:
            for gap in gaps:
                print(f"refused: {gap}", file=sys.stderr)
            print("refused: exhaust every configured lane before blocking", file=sys.stderr)
            return 4
    seq = int(data.get("seq", 0)) + 1
    data["seq"] = seq
    block = {
        "id": pack.next_id("b", "blocks"),
        "seq": seq,
        "surface": args.surface,
        "class": args.cls,
        "reason": redact_text(args.reason),
        "tried": tried,
        "human_only": bool(args.human_only or gate),
        "escalate": False if gate else None,
        "head_sha": git_head(args.repo, args.head),
        "added": now(),
    }
    data["blocks"].append(block)
    pack.save()
    print(f"blocked {block['id']}: {args.surface} ({args.cls}); stop and ask the user" if gate else f"blocked {block['id']}: {args.surface} ({args.cls})")
    return 0


def short(sha: str | None) -> str:
    return sha[:7] if sha else "none"


def level_index(level: str) -> int:
    return LEVELS.index(level)


def evaluate(pack: Pack, args: argparse.Namespace) -> dict:
    data = pack.load()
    head = git_head(args.repo, args.head)
    required = args.level or data.get("required_level", "L1")
    failures: list[str] = []
    rows: list[dict] = []
    reached = -1
    allow_blocked = args.allow_blocked

    def stale(kind: str, rec: dict) -> bool:
        if rec.get("head_sha") != head:
            failures.append(f"stale {kind} {rec.get('id')}: recorded at {short(rec.get('head_sha'))}, HEAD is {short(head)}")
            return True
        return False

    effective: dict[str, dict] = {}
    for step in data.get("steps", []):
        effective[step.get("label", step.get("id"))] = step
    for step in effective.values():
        ok = True
        if step.get("exit_code") != 0:
            failures.append(f"step {step['id']} ({step['label']}) exited {step.get('exit_code')}")
            ok = False
        log = pack.resolve(step.get("log", ""))
        if not log.is_file():
            failures.append(f"step {step['id']}: log is missing")
            ok = False
        elif sha256_file(log) != step.get("log_sha256"):
            failures.append(f"step {step['id']}: log hash mismatch")
            ok = False
        elif step.get("output_bytes", 0) == 0 and not step.get("allow_empty"):
            failures.append(f"step {step['id']} ({step['label']}): empty output; add --allow-empty if expected")
            ok = False
        if stale("step", step):
            ok = False
        if ok and step.get("level") in LEVELS:
            reached = max(reached, level_index(step["level"]))
        rows.append(
            {
                "id": step["id"],
                "level": step.get("level"),
                "what": " ".join(step.get("argv", [])),
                "result": f"exit {step.get('exit_code')}, {step.get('output_bytes', 0)} B, log sha256 {str(step.get('log_sha256', ''))[:12]}",
                "ok": ok,
            }
        )
    def order_key(rec: dict) -> tuple[int, str]:
        return (int(rec.get("seq", 0)), str(rec.get("added", "")))

    proven_after: dict[str, tuple[int, str]] = {}
    for art in data.get("artifacts", []):
        ok = True
        path = pack.resolve(art.get("path", ""))
        if not path.is_file():
            failures.append(f"artifact {art['id']}: file is missing")
            ok = False
        elif path.stat().st_size == 0:
            failures.append(f"artifact {art['id']}: file is empty")
            ok = False
        elif sha256_file(path) != art.get("sha256"):
            failures.append(f"artifact {art['id']}: sha256 mismatch")
            ok = False
        if art.get("surface") in GATED_SURFACES and data.get("visibility") != "private" and not art.get("redacted"):
            failures.append(f"artifact {art['id']}: unredacted {art['surface']} capture on a non-private repo")
            ok = False
        if stale("artifact", art):
            ok = False
        if ok:
            surface = art.get("surface", "")
            key = order_key(art)
            if surface not in proven_after or key > proven_after[surface]:
                proven_after[surface] = key
            if art.get("level") in LEVELS:
                reached = max(reached, level_index(art["level"]))
        rows.append(
            {
                "id": art["id"],
                "level": art.get("level"),
                "what": f"{art.get('surface')} {art.get('kind')} {Path(art.get('path', '')).name}",
                "result": f"{art.get('bytes')} B, sha256 {str(art.get('sha256', ''))[:12]}" + (", redacted" if art.get("redacted") else ""),
                "ok": ok,
            }
        )
    blocked: list[dict] = []
    for block in data.get("blocks", []):
        latest = proven_after.get(block.get("surface", ""))
        if latest is not None and latest > order_key(block):
            continue
        stale("block", block)
        if block.get("class") not in GATE_CLASSES:
            lanes = rig_lanes(args.rig, block.get("surface", ""))
            for gap in exhaustion_gaps(block.get("surface", ""), block.get("tried", {}), lanes):
                failures.append(f"block {block['id']}: {gap}")
        blocked.append(block)
        if not allow_blocked:
            failures.append(f"block {block['id']}: {block['surface']} is blocked ({block.get('class')}): {block.get('reason')}")
    if required not in LEVELS:
        failures.append(f"required level {required!r} is not one of {', '.join(LEVELS)}")
    elif reached < level_index(required):
        got = LEVELS[reached] if reached >= 0 else "none"
        failures.append(f"level {required} required, reached {got}")
    return {
        "task": data.get("task", ""),
        "head": head,
        "required": required,
        "reached": LEVELS[reached] if reached >= 0 else None,
        "rows": rows,
        "blocked": blocked,
        "failures": failures,
        "ok": not failures,
    }


def cell(text: object, limit: int = 90) -> str:
    out = str(text).replace("|", "\\|").replace("\n", " ")
    return out if len(out) <= limit else out[: limit - 1] + "…"


def markdown(report: dict) -> str:
    status = "PASS" if report["ok"] else "FAIL"
    lines = [
        "## Proof packet",
        "",
        f"**Task:** {cell(report['task'], 200)}",
        f"**Head:** `{short(report['head'])}` · **Level:** {report['reached'] or 'none'} reached, {report['required']} required · **{status}**",
        "",
        "| Id | Level | Evidence | Result |",
        "| --- | --- | --- | --- |",
    ]
    for row in report["rows"]:
        what = f"`{cell(row['what'])}`" if row["id"].startswith("s") else cell(row["what"])
        mark = "" if row["ok"] else " ✗"
        lines.append(f"| {row['id']} | {row['level']} | {what} | {cell(row['result'])}{mark} |")
    if not report["rows"]:
        lines.append("| - | - | no evidence recorded | - |")
    for block in report["blocked"]:
        lines += ["", f"**Blocked:** {block['surface']} ({block.get('class')}): {cell(block.get('reason', ''), 160)}"]
    if report["failures"]:
        lines += ["", "**Failures:**", *[f"- {cell(f, 200)}" for f in report["failures"]]]
    return "\n".join(lines) + "\n"


def cmd_verify(args: argparse.Namespace, pack: Pack) -> int:
    report = evaluate(pack, args)
    if args.markdown:
        sys.stdout.write(markdown(report))
    else:
        print(f"task: {report['task']}")
        print(f"head: {short(report['head'])}  level: {report['reached'] or 'none'} reached, {report['required']} required")
        for row in report["rows"]:
            print(f"{'ok  ' if row['ok'] else 'FAIL'} {row['id']} {row['level']} {cell(row['what'], 60)}: {row['result']}")
        for block in report["blocked"]:
            print(f"blocked {block['id']}: {block['surface']} ({block.get('class')})")
        for failure in report["failures"]:
            print(f"error: {failure}", file=sys.stderr)
        print("verified" if report["ok"] else "NOT verified")
    return 0 if report["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", type=Path, default=Path(os.environ.get("JSTACK_PROOF_DIR", ".proof")), help="packet folder (default: .proof)")
    common.add_argument("--repo", type=Path, default=Path("."), help="git checkout the packet is about (default: .)")
    common.add_argument("--head", help="override the git HEAD sha (for non-git work and tests)")
    common.add_argument("--rig", type=Path, help="rig file (default: ~/.config/jstack/rig.json)")

    parser = argparse.ArgumentParser(prog="proof-pack.py", description="Build and verify a mechanical proof packet.")
    sub = parser.add_subparsers(dest="command", required=True)

    i = sub.add_parser("init", parents=[common], help="start a packet")
    i.add_argument("--task", required=True)
    i.add_argument("--level", choices=LEVELS, default="L2", help="level the claim needs (default: L2)")
    i.add_argument("--visibility", choices=("public", "private", "auto"), default="auto", help="repo visibility; auto asks gh, unknown counts as public")
    i.add_argument("--force", action="store_true")
    i.set_defaults(func=cmd_init)

    r = sub.add_parser("run", parents=[common], help="run a command and record it")
    r.add_argument("--level", choices=LEVELS, default="L1")
    r.add_argument("--label", help="step name; a later step with the same label replaces an earlier one")
    r.add_argument("--timeout", type=int, default=900)
    r.add_argument("--cwd", type=Path)
    r.add_argument("--allow-empty", action="store_true", help="empty output is expected")
    r.add_argument("cmd", nargs=argparse.REMAINDER, help="-- COMMAND [ARGS...]")
    r.set_defaults(func=cmd_run)

    a = sub.add_parser("attach", parents=[common], help="record an artifact file")
    a.add_argument("path")
    a.add_argument("--surface", required=True)
    a.add_argument("--level", choices=LEVELS, default="L3")
    a.add_argument("--kind", default="screenshot")
    a.add_argument("--redacted", action="store_true", help="the file has no credentials, codes or private windows")
    a.add_argument("--note")
    a.set_defaults(func=cmd_attach)

    b = sub.add_parser("block", parents=[common], help="record a blocked surface")
    b.add_argument("--surface", required=True)
    b.add_argument("--reason", required=True)
    b.add_argument("--class", dest="cls", choices=BLOCK_CLASSES, default="other")
    b.add_argument("--tried", action="append", metavar="LANE=EVIDENCE", help="a lane tried, with what happened (repeatable)")
    b.add_argument("--human-only", action="store_true", help="physical blocker only")
    b.set_defaults(func=cmd_block)

    v = sub.add_parser("verify", parents=[common], help="re-check the packet")
    v.add_argument("--level", choices=LEVELS, help="override the required level")
    v.add_argument("--allow-blocked", action="store_true", help="list blocked surfaces without failing")
    v.add_argument("--markdown", action="store_true", help="print a PR-ready summary")
    v.set_defaults(func=cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args, Pack(args.dir))


if __name__ == "__main__":
    sys.exit(main())
