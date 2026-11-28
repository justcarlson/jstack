#!/usr/bin/env python3
"""Discover, write and check the jstack rig file. Stdlib only.

The rig file (default ~/.config/jstack/rig.json, schema jstack.rig/1) names the
local tools, endpoints and fallback model that `scripts/install.py` renders into
deployed skills. It holds names only, never secrets.

Discovery is read-only. It looks up program names on $PATH, checks that a few
config folders exist, tries a TCP connect to loopback ports, and runs
`gh auth status` for its exit code alone. It never opens a secret file, a
transcript or a credential store, and never prints a token.

Commands:
  discover   inventory this machine; print JSON, or a table with --human
  write      validate and write the rig file atomically with mode 0600
  check      validate an existing rig file and report problems

Exit codes: 0 ok, 1 check found a problem, 2 usage or validation error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

SCHEMA = "jstack.rig/1"
DISCOVER_SCHEMA = "jstack.discover/1"
TOP_KEYS = ("schema", "harnesses", "endpoints", "lanes", "media_uploader", "fallback")

# Verification lanes and the program names that can serve each one.
LANE_TOOLS: dict[str, tuple[str, ...]] = {
    "web": ("agent-browser", "browser-harness", "playwright", "chromium", "google-chrome-stable", "firefox"),
    "auth": ("oathtool", "ykman", "op", "bw"),
    "native_gui": ("cua-driver", "grim", "slurp", "wtype", "ydotool", "xdotool", "screencapture", "cliclick"),
    "vnc": ("vncviewer", "remmina", "wayvnc", "x11vnc"),
    "video": ("ffmpeg", "ffprobe", "wf-recorder"),
    "audio": ("whisper", "whisper-cli", "whisper-cpp", "arecord", "parecord", "pw-record", "sox", "say"),
    "vm": ("qemu-system-x86_64", "virsh", "limactl", "multipass", "quickemu", "docker", "podman"),
    "ssh": ("ssh", "mosh", "scp", "tailscale"),
    "secrets": ("op", "bw", "pass", "gopass", "vault", "sops"),
}
UPLOADER_TOOLS = ("gh", "rclone", "aws", "gcloud", "wrangler", "scp")
LOOPBACK_ENDPOINTS = {"opencode": 4096, "ollama": 11434, "llama_server": 8080}
# (name, config folder under $HOME or None, program on $PATH or None)
HARNESSES = (
    ("claude", ".claude", "claude"),
    ("codex", ".codex", "codex"),
    ("antigravity", ".gemini", None),
    ("opencode", ".config/opencode", "opencode"),
    ("pi", ".pi", "pi"),
    ("t3", ".t3", None),
)

NAME = r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,63}"
PLACEHOLDER = r"<[A-Za-z0-9._ -]{1,40}>"
NAME_RE = re.compile(rf"^(?:{NAME}|{PLACEHOLDER})\Z")
COMMAND_RE = re.compile(r"^(?:[A-Za-z0-9<][A-Za-z0-9._:/@+<>= ,-]{0,79})\Z")
LANE_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}\Z")
ENDPOINT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}\Z")
URL_RE = re.compile(
    r"^https?://(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\]|<[A-Za-z0-9._ -]{1,20}>)"
    r"(?::(?:\d{1,5}|<[A-Za-z0-9._ -]{1,20}>))?(?:/[A-Za-z0-9._/-]*)?\Z"
)
MAX_LANES = 16
MAX_TOOLS = 16

SECRET_PATTERNS = [
    re.compile(r"://[^/\s@]*@"),  # credentials in a URL
    re.compile(r"(?i)[?&;](?:access_?token|token|key|apikey|api_key|secret|password|pass|auth|sig|signature)="),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{6,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."),
    re.compile(r"-----BEGIN"),
    re.compile(r"(?i)\bbearer\s+\S{8,}"),
    re.compile(r"(?i)(?:password|passwd|secret|token|api[_-]?key|credential|authorization)\s*[:=]"),
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
]
LONG_TOKEN = re.compile(r"[A-Za-z0-9+_=]{32,}")


def looks_secret(value: str) -> bool:
    """True when a string resembles a token, password or credential URL."""
    if any(p.search(value) for p in SECRET_PATTERNS):
        return True
    for chunk in LONG_TOKEN.findall(value):
        if re.search(r"[A-Za-z]", chunk) and re.search(r"\d", chunk):
            return True
    return False


def _check(label: str, value: object, pattern: re.Pattern[str], errors: list[str]) -> None:
    """Record a problem for one string value. The value itself is never echoed."""
    if not isinstance(value, str) or not value:
        errors.append(f"{label}: must be a non-empty string")
    elif looks_secret(value):
        errors.append(f"{label}: value looks like a token, password or credential URL; rig files hold names only")
    elif not pattern.match(value):
        errors.append(f"{label}: value has characters outside the allowed set")


def validate(rig: object) -> list[str]:
    """Return problems with a rig document. Empty means valid."""
    if not isinstance(rig, dict):
        return ["rig must be a JSON object"]
    errors: list[str] = []
    if rig.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    for i, key in enumerate(rig):
        if key not in TOP_KEYS:
            errors.append(f"unknown top-level key #{i + 1}")
    harnesses = rig.get("harnesses", [])
    if not isinstance(harnesses, list):
        errors.append("harnesses: must be a list")
    else:
        for i, h in enumerate(harnesses):
            _check(f"harnesses[{i}]", h, NAME_RE, errors)
    endpoints = rig.get("endpoints", {})
    if not isinstance(endpoints, dict):
        errors.append("endpoints: must be an object")
    else:
        for i, (name, url) in enumerate(endpoints.items()):
            if not isinstance(name, str) or not ENDPOINT_NAME_RE.match(name) or looks_secret(name):
                errors.append(f"endpoints: name #{i + 1} is not a plain lowercase name")
                continue
            _check(f"endpoints.{name}", url, URL_RE, errors)
    lanes = rig.get("lanes", {})
    if not isinstance(lanes, dict):
        errors.append("lanes: must be an object")
    else:
        if len(lanes) > MAX_LANES:
            errors.append(f"lanes: at most {MAX_LANES} lanes")
        for i, (lane, tools) in enumerate(lanes.items()):
            if not isinstance(lane, str) or not LANE_RE.match(lane):
                errors.append(f"lanes: name #{i + 1} must match [a-z][a-z0-9_]*")
                continue
            if not isinstance(tools, list) or len(tools) > MAX_TOOLS:
                errors.append(f"lanes.{lane}: must be a list of at most {MAX_TOOLS} tool names")
                continue
            for j, tool in enumerate(tools):
                _check(f"lanes.{lane}[{j}]", tool, NAME_RE, errors)
    if "media_uploader" in rig:
        _check("media_uploader", rig["media_uploader"], COMMAND_RE, errors)
    if "fallback" in rig:
        fb = rig["fallback"]
        if not isinstance(fb, dict) or set(fb) != {"provider", "model"}:
            errors.append("fallback: must be an object with exactly provider and model")
        else:
            _check("fallback.provider", fb["provider"], NAME_RE, errors)
            _check("fallback.model", fb["model"], NAME_RE, errors)
    return errors


def default_path(env: dict[str, str] | None = None) -> Path:
    env = dict(os.environ if env is None else env)
    base = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME") or Path.home()) / ".config")
    return Path(base) / "jstack" / "rig.json"


def which(name: str, env: dict[str, str]) -> bool:
    return shutil.which(name, path=env.get("PATH")) is not None


def tcp_open(port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def gh_state(env: dict[str, str]) -> dict[str, object]:
    if not which("gh", env):
        return {"installed": False, "authenticated": None}
    try:
        proc = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, timeout=10, check=False, env=env
        )
    except (OSError, subprocess.SubprocessError):
        return {"installed": True, "authenticated": None}
    return {"installed": True, "authenticated": proc.returncode == 0}


def discover(home: Path, env: dict[str, str], net: bool = True, gh: bool = True) -> dict[str, object]:
    harnesses = {}
    for name, folder, program in HARNESSES:
        found = (home / folder).exists() or bool(program and which(program, env))
        harnesses[name] = found
    lanes = {lane: [t for t in tools if which(t, env)] for lane, tools in LANE_TOOLS.items()}
    uploaders = [t for t in UPLOADER_TOOLS if which(t, env)]
    endpoints = {}
    if net:
        for name, port in LOOPBACK_ENDPOINTS.items():
            if tcp_open(port):
                endpoints[name] = f"http://127.0.0.1:{port}"
    candidate: dict[str, object] = {
        "schema": SCHEMA,
        "harnesses": sorted(n for n, ok in harnesses.items() if ok),
        "endpoints": endpoints,
        "lanes": {lane: tools for lane, tools in lanes.items() if tools},
    }
    return {
        "schema": DISCOVER_SCHEMA,
        "harnesses": harnesses,
        "lanes": lanes,
        "uploader_candidates": uploaders,
        "endpoints": endpoints,
        "network_probed": net,
        "gh": gh_state(env) if gh else None,
        "rig": candidate,
    }


def human(report: dict[str, object]) -> str:
    rows = ["lane        tools found"]
    lanes = report["lanes"]
    assert isinstance(lanes, dict)
    for lane, tools in lanes.items():
        rows.append(f"{lane:<11} {', '.join(tools) if tools else '(none)'}")
    harnesses = report["harnesses"]
    assert isinstance(harnesses, dict)
    rows.append("")
    rows.append("harnesses   " + (", ".join(n for n, ok in harnesses.items() if ok) or "(none)"))
    endpoints = report["endpoints"]
    assert isinstance(endpoints, dict)
    probed = report["network_probed"]
    rows.append("endpoints   " + (", ".join(endpoints) or ("(none on loopback)" if probed else "(not probed)")))
    uploaders = report["uploader_candidates"]
    assert isinstance(uploaders, list)
    rows.append("uploaders   " + (", ".join(uploaders) or "(none)"))
    gh = report["gh"]
    if isinstance(gh, dict):
        auth = gh["authenticated"]
        rows.append("gh          " + ("not installed" if not gh["installed"] else "signed in" if auth else "not signed in"))
    return "\n".join(rows)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".rig.", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.chmod(path, 0o600)


def load_rig(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("rig must be a JSON object")
    return data


def read_input(source: str) -> dict:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    data = json.loads(raw)
    if isinstance(data, dict) and data.get("schema") == DISCOVER_SCHEMA:
        data = data.get("rig", {})
    if not isinstance(data, dict):
        raise TypeError("input must be a JSON object")
    return data


def split_pair(raw: str, what: str, *, allow_empty: bool = False) -> tuple[str, str]:
    key, sep, value = raw.partition("=")
    if not sep or not key or (not allow_empty and not value):
        raise ValueError(f"error: {what} must look like NAME=VALUE")
    return key, value


def cmd_discover(args: argparse.Namespace) -> int:
    env = dict(os.environ)
    home = args.home.expanduser().resolve() if args.home else Path(env.get("HOME") or Path.home())
    report = discover(home, env, net=not args.no_net, gh=not args.no_gh)
    print(human(report) if args.human else json.dumps(report, indent=2, sort_keys=True))
    return 0


def cmd_write(args: argparse.Namespace) -> int:
    path = args.path or default_path()
    rig: dict = {}
    try:
        if args.merge and path.is_file():
            rig.update(load_rig(path))
        if args.from_discover:
            found = discover(Path(os.environ.get("HOME") or Path.home()), dict(os.environ), net=not args.no_net, gh=False)["rig"]
            assert isinstance(found, dict)
            for key, value in found.items():
                if isinstance(value, dict) and isinstance(rig.get(key), dict):
                    rig[key] = {**rig[key], **value}
                else:
                    rig[key] = value
        if args.input:
            rig.update(read_input(args.input))
    except (OSError, TypeError, ValueError) as exc:
        print(f"error: cannot read rig input: {exc.__class__.__name__}", file=sys.stderr)
        return 2
    rig["schema"] = SCHEMA
    if args.fallback:
        provider, sep, model = args.fallback.partition("/")
        if not sep or not provider or not model:
            print("error: --fallback must look like PROVIDER/MODEL", file=sys.stderr)
            return 2
        rig["fallback"] = {"provider": provider, "model": model}
    if args.uploader:
        rig["media_uploader"] = args.uploader
    if args.harness:
        rig["harnesses"] = sorted(set(args.harness))
    try:
        for raw in args.lane or []:
            lane, tools = split_pair(raw, "--lane", allow_empty=True)
            lanes = dict(rig.get("lanes") or {})
            items = [t for t in tools.split(",") if t]
            if items:
                lanes[lane] = items
            else:
                lanes.pop(lane, None)
            rig["lanes"] = lanes
        for raw in args.endpoint or []:
            name, url = split_pair(raw, "--endpoint")
            endpoints = dict(rig.get("endpoints") or {})
            endpoints[name] = url
            rig["endpoints"] = endpoints
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    problems = validate(rig)
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        print("error: nothing written", file=sys.stderr)
        return 2
    text = json.dumps(rig, indent=2, sort_keys=True) + "\n"
    if args.dry_run:
        sys.stdout.write(text)
        return 0
    atomic_write(path, text)
    print(f"wrote {path} (mode 0600)")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    path = args.path or default_path()
    env = dict(os.environ)
    errors: list[str] = []
    warnings: list[str] = []
    if not path.is_file():
        print(f"error: {path} does not exist; run jstack-setup", file=sys.stderr)
        return 1
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        errors.append(f"mode is {mode:04o}; run chmod 600 on the rig file")
    try:
        rig = load_rig(path)
    except (OSError, TypeError, ValueError) as exc:
        print(f"error: rig is not valid JSON ({exc.__class__.__name__}); fix or rewrite it", file=sys.stderr)
        return 1
    errors.extend(validate(rig))
    lanes = rig.get("lanes") if isinstance(rig.get("lanes"), dict) else {}
    for lane, tools in sorted(lanes.items()):
        for tool in tools if isinstance(tools, list) else []:
            if isinstance(tool, str) and not tool.startswith("<") and not which(tool, env):
                warnings.append(f"lanes.{lane}: {tool} is not on PATH")
    if "fallback" not in rig:
        warnings.append("fallback: not set; a refused or avoided task will be reported as blocked")
    if "media_uploader" not in rig:
        warnings.append("media_uploader: not set; artifacts stay local")
    if args.strict:
        errors.extend(warnings)
        warnings = []
    for line in warnings:
        print(f"warn: {line}")
    for line in errors:
        print(f"error: {line}")
    if errors:
        return 1
    print(f"ok: {path} valid ({len(lanes)} lane(s))")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jstack-rig.py", description="Discover, write and check the jstack rig file.")
    sub = parser.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="inventory this machine (read-only)")
    d.add_argument("--human", action="store_true", help="print a table instead of JSON")
    d.add_argument("--no-net", action="store_true", help="skip loopback port probes")
    d.add_argument("--no-gh", action="store_true", help="skip the gh auth status check")
    d.add_argument("--home", type=Path, help="home folder to inspect (default: $HOME)")
    d.set_defaults(func=cmd_discover)

    w = sub.add_parser("write", help="validate and atomically write the rig file (mode 0600)")
    w.add_argument("--path", type=Path, help="rig file (default: ~/.config/jstack/rig.json)")
    w.add_argument("--input", metavar="FILE", help="rig or discover JSON; - reads stdin")
    w.add_argument("--from-discover", action="store_true", help="start from discovered harnesses, lanes and endpoints")
    w.add_argument("--merge", action="store_true", help="start from the existing rig file")
    w.add_argument("--fallback", metavar="PROVIDER/MODEL")
    w.add_argument("--uploader", metavar="COMMAND")
    w.add_argument("--lane", action="append", metavar="NAME=TOOL[,TOOL]", help="set a lane (repeatable)")
    w.add_argument("--endpoint", action="append", metavar="NAME=URL", help="set an endpoint (repeatable)")
    w.add_argument("--harness", action="append", metavar="NAME", help="set the harness list (repeatable)")
    w.add_argument("--no-net", action="store_true")
    w.add_argument("--dry-run", action="store_true", help="print the rig; write nothing")
    w.set_defaults(func=cmd_write)

    c = sub.add_parser("check", help="validate the rig file")
    c.add_argument("--path", type=Path)
    c.add_argument("--strict", action="store_true", help="treat warnings as errors")
    c.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
