"""Tests for the prove skill, the jstack-setup rig tool and install-time rig rendering.

Secrets and private-looking strings are built at run time so no literal trips a scanner.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
PACK = ROOT / "skills" / "prove" / "scripts" / "proof-pack.py"
RIG = ROOT / "skills" / "jstack-setup" / "scripts" / "jstack-rig.py"


def load(name: str, path: Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


install = load("jstack_install_rig", SCRIPTS / "install.py")
privacy = load("jstack_privacy_rig", SCRIPTS / "check_privacy.py")
validator = load("jstack_validate_rig", SCRIPTS / "validate_skills.py")
rigtool = load("jstack_rig_tool", RIG)
proof = load("jstack_proof_pack", PACK)

HEAD = "a" * 40
OTHER = "b" * 40

# Built at run time, never written as literals.
FAKE_TOKEN = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
FAKE_HOME = "/" + "home" + "/" + "someone"
FAKE_TAILNET = "box." + "tail1234" + "." + "ts" + "." + "net"
FAKE_CGNAT = "100" + ".101.102.103"


def cli(script: Path, *args: str, cwd: Path | None = None, env: dict[str, str] | None = None):
    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, "-I", str(script), *map(str, args)],
        cwd=cwd,
        env=merged,
        capture_output=True,
        text=True,
        check=False,
    )


# proof-pack ---------------------------------------------------------------


@pytest.fixture
def work(tmp_path: Path) -> Path:
    w = tmp_path / "work"
    w.mkdir()
    return w


def pp(work: Path, *args: str, head: str = HEAD, rig: Path | None = None):
    extra = ["--dir", str(work / ".proof"), "--head", head]
    if rig is not None:
        extra += ["--rig", str(rig)]
    sub, rest = args[0], list(args[1:])
    if sub == "run" and "--" in rest:
        i = rest.index("--")
        return cli(PACK, sub, *rest[:i], *extra, *rest[i:], cwd=work)
    return cli(PACK, sub, *rest, *extra, cwd=work)


def no_rig(work: Path) -> Path:
    return work / "absent-rig.json"


def make_rig(path: Path, lanes: dict[str, list[str]] | None = None) -> Path:
    path.write_text(json.dumps({"schema": "jstack.rig/1", "lanes": lanes or {}}))
    path.chmod(0o600)
    return path


def test_lifecycle_passes_and_prints_markdown(work: Path):
    rig = no_rig(work)
    assert pp(work, "init", "--task", "demo claim", "--level", "L3", "--visibility", "public", rig=rig).returncode == 0
    run = pp(work, "run", "--level", "L1", "--label", "tests", "--", sys.executable, "-c", "print('3 passed')", rig=rig)
    assert run.returncode == 0 and "3 passed" in run.stdout
    shot = work / "shot.png"
    shot.write_bytes(b"not-really-a-png")
    assert pp(work, "attach", str(shot), "--surface", "web", "--level", "L3", rig=rig).returncode == 0
    ver = pp(work, "verify", rig=rig)
    assert ver.returncode == 0 and "verified" in ver.stdout
    md = pp(work, "verify", "--markdown", rig=rig)
    assert md.returncode == 0
    assert "## Proof packet" in md.stdout and "PASS" in md.stdout and "| s1 | L1 |" in md.stdout and "| a1 | L3 |" in md.stdout


def test_stale_head_is_rejected(work: Path):
    rig = no_rig(work)
    pp(work, "init", "--task", "t", "--level", "L1", "--visibility", "public", rig=rig)
    pp(work, "run", "--label", "tests", "--", sys.executable, "-c", "print('ok')", rig=rig)
    assert pp(work, "verify", rig=rig).returncode == 0
    stale = pp(work, "verify", head=OTHER, rig=rig)
    assert stale.returncode == 1
    assert "stale step" in stale.stderr


def test_failing_step_and_empty_output_are_rejected(work: Path):
    rig = no_rig(work)
    pp(work, "init", "--task", "t", "--level", "L1", "--visibility", "public", rig=rig)
    pp(work, "run", "--label", "bad", "--", sys.executable, "-c", "raise SystemExit(3)", rig=rig)
    out = pp(work, "verify", rig=rig)
    assert out.returncode == 1 and "exited 3" in out.stderr
    pp(work, "run", "--label", "bad", "--", sys.executable, "-c", "pass", rig=rig)
    quiet = pp(work, "verify", rig=rig)
    assert quiet.returncode == 1 and "empty output" in quiet.stderr
    pp(work, "run", "--label", "bad", "--allow-empty", "--", sys.executable, "-c", "pass", rig=rig)
    assert pp(work, "verify", rig=rig).returncode == 0


def test_missing_and_tampered_artifacts_are_rejected(work: Path):
    rig = no_rig(work)
    pp(work, "init", "--task", "t", "--level", "L3", "--visibility", "public", rig=rig)
    shot = work / "shot.png"
    shot.write_bytes(b"first")
    assert pp(work, "attach", str(shot), "--surface", "web", rig=rig).returncode == 0
    shot.write_bytes(b"second")
    assert "sha256 mismatch" in pp(work, "verify", rig=rig).stderr
    shot.unlink()
    assert "file is missing" in pp(work, "verify", rig=rig).stderr
    empty = work / "empty.png"
    empty.write_bytes(b"")
    refused = pp(work, "attach", str(empty), "--surface", "web", rig=rig)
    assert refused.returncode == 2 and "empty" in refused.stderr


def test_level_below_required_fails(work: Path):
    rig = no_rig(work)
    pp(work, "init", "--task", "t", "--level", "L3", "--visibility", "public", rig=rig)
    pp(work, "run", "--level", "L1", "--label", "tests", "--", sys.executable, "-c", "print(1)", rig=rig)
    out = pp(work, "verify", rig=rig)
    assert out.returncode == 1 and "level L3 required, reached L1" in out.stderr
    assert pp(work, "verify", "--level", "L1", rig=rig).returncode == 0


def test_gated_surface_needs_redaction_on_public_repo(work: Path):
    rig = no_rig(work)
    pp(work, "init", "--task", "t", "--level", "L3", "--visibility", "public", rig=rig)
    shot = work / "desk.png"
    shot.write_bytes(b"pixels")
    for surface in ("auth", "native_gui", "vnc", "desktop"):
        assert pp(work, "attach", str(shot), "--surface", surface, rig=rig).returncode == 3, surface
    assert pp(work, "attach", str(shot), "--surface", "auth", "--redacted", rig=rig).returncode == 0


def test_gated_surface_is_allowed_on_private_repo(work: Path):
    rig = no_rig(work)
    pp(work, "init", "--task", "t", "--level", "L3", "--visibility", "private", rig=rig)
    shot = work / "desk.png"
    shot.write_bytes(b"pixels")
    assert pp(work, "attach", str(shot), "--surface", "auth", rig=rig).returncode == 0


def test_block_requires_every_rig_lane(work: Path):
    rig = make_rig(work / "rig.json", {"vnc": ["viewer-a", "viewer-b"]})
    pp(work, "init", "--task", "t", "--level", "L1", "--visibility", "public", rig=rig)
    base = ["block", "--surface", "vnc", "--reason", "needs a hardware touch", "--class", "physical", "--human-only"]
    refused = pp(work, *base, "--tried", "viewer-a=connected, key prompt", rig=rig)
    assert refused.returncode == 4 and "lane viewer-b not tried" in refused.stderr
    done = pp(work, *base, "--tried", "viewer-a=connected, key prompt", "--tried", "viewer-b=same prompt", rig=rig)
    assert done.returncode == 0 and "blocked b1" in done.stdout


def test_block_without_lanes_needs_two_methods(work: Path):
    rig = no_rig(work)
    pp(work, "init", "--task", "t", "--level", "L1", "--visibility", "public", rig=rig)
    base = ["block", "--surface", "usb", "--reason", "plug in a device", "--class", "physical", "--human-only"]
    assert pp(work, *base, "--tried", "one=nothing", rig=rig).returncode == 4
    assert pp(work, *base, "--tried", "one=nothing", "--tried", "two=nothing", rig=rig).returncode == 0


def test_unexhausted_block_fails_verify_even_if_edited_in(work: Path):
    rig = make_rig(work / "rig.json", {"vnc": ["viewer-a"]})
    pp(work, "init", "--task", "t", "--level", "L1", "--visibility", "public", rig=rig)
    pp(work, "run", "--label", "tests", "--", sys.executable, "-c", "print(1)", rig=rig)
    pack = work / ".proof" / "pack.json"
    data = json.loads(pack.read_text())
    data["blocks"].append(
        {"id": "b1", "surface": "vnc", "class": "physical", "reason": "x", "tried": {}, "human_only": True, "head_sha": HEAD}
    )
    pack.write_text(json.dumps(data))
    out = pp(work, "verify", rig=rig)
    assert out.returncode == 1 and "lane viewer-a not tried" in out.stderr
    assert pp(work, "verify", "--allow-blocked", rig=rig).returncode == 1  # exhaustion is still checked


@pytest.mark.parametrize("cls", ["captcha", "anti-bot", "2fa", "access-denied", "approval"])
def test_gate_classes_stop_and_ask_without_exhaustion(work: Path, cls: str):
    rig = make_rig(work / "rig.json", {"web": ["tool-a", "tool-b"]})
    pp(work, "init", "--task", "t", "--level", "L1", "--visibility", "public", rig=rig)
    out = pp(work, "block", "--surface", "web", "--reason", "a gate", "--class", cls, rig=rig)
    assert out.returncode == 0 and "stop and ask the user" in out.stdout
    block = json.loads((work / ".proof" / "pack.json").read_text())["blocks"][0]
    assert block["escalate"] is False and block["human_only"] is True


def test_human_only_rejects_non_physical_other_class(work: Path):
    rig = no_rig(work)
    pp(work, "init", "--task", "t", "--level", "L1", "--visibility", "public", rig=rig)
    out = pp(work, "block", "--surface", "web", "--reason", "slow", "--class", "other", "--human-only", rig=rig)
    assert out.returncode == 2


def test_redaction_helpers():
    text = " ".join([FAKE_TOKEN, FAKE_HOME + "/project", FAKE_TAILNET, FAKE_CGNAT, "Bearer abcdefghijklmnop"])
    out = proof.redact_text(text)
    for leaked in (FAKE_TOKEN, FAKE_HOME, FAKE_TAILNET, FAKE_CGNAT, "abcdefghijklmnop"):
        assert leaked not in out
    assert "~/project" in out and "<tailnet-host>" in out and "<cgnat-ip>" in out
    argv = proof.redact_argv(["tool", "--token", "hunter2", "--api-key=hunter3", "SECRET_KEY=hunter4", "--name", "ok"])
    joined = " ".join(argv)
    assert "hunter" not in joined and "--name ok" in joined


def test_run_log_and_packet_hold_no_secrets(work: Path):
    rig = no_rig(work)
    pp(work, "init", "--task", "uses " + FAKE_TOKEN, "--level", "L1", "--visibility", "public", rig=rig)
    code = f"print({FAKE_TOKEN!r}); print({FAKE_HOME!r} + '/x')"
    pp(work, "run", "--label", "leak", "--", sys.executable, "-c", code, rig=rig)
    blob = (work / ".proof" / "pack.json").read_text() + "".join(p.read_text() for p in (work / ".proof" / "logs").iterdir())
    assert FAKE_TOKEN not in blob and FAKE_HOME not in blob


def test_init_refuses_to_overwrite_without_force(work: Path):
    rig = no_rig(work)
    assert pp(work, "init", "--task", "t", "--visibility", "public", rig=rig).returncode == 0
    assert pp(work, "init", "--task", "t", "--visibility", "public", rig=rig).returncode == 2
    assert pp(work, "init", "--task", "t", "--visibility", "public", "--force", rig=rig).returncode == 0


# jstack-rig ---------------------------------------------------------------


def good_rig() -> dict:
    return {
        "schema": "jstack.rig/1",
        "harnesses": ["claude"],
        "endpoints": {"ollama": "http://127.0.0.1:11434"},
        "lanes": {"web": ["agent-browser"], "ssh": ["ssh"]},
        "media_uploader": "upload-tool",
        "fallback": {"provider": "prov", "model": "mod-1"},
    }


def test_example_rig_has_schema_and_is_not_a_forbidden_file():
    example = json.loads((ROOT / "rig.example.json").read_text())
    assert example["schema"] == "jstack.rig/1"
    assert set(example) <= set(rigtool.TOP_KEYS)
    assert privacy.forbidden_file("rig.example.json") is None


def test_validate_accepts_good_rig():
    assert rigtool.validate(good_rig()) == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(schema="other/1"),
        lambda r: r.update(surprise=True),
        lambda r: r["lanes"].update({"Bad Lane": ["x"]}),
        lambda r: r["lanes"].update({"web": "not-a-list"}),
        lambda r: r.update(fallback={"provider": "only"}),
        lambda r: r.update(endpoints={"x": "not a url"}),
    ],
)
def test_validate_rejects_bad_shapes(mutate):
    rig = good_rig()
    mutate(rig)
    assert rigtool.validate(rig)


@pytest.mark.parametrize(
    "field",
    ["uploader", "tool", "endpoint", "model"],
)
def test_validate_rejects_secret_values_without_echoing_them(field: str):
    rig = good_rig()
    secret = FAKE_TOKEN
    if field == "uploader":
        rig["media_uploader"] = "upload --key " + secret
    elif field == "tool":
        rig["lanes"]["web"] = [secret]
    elif field == "endpoint":
        rig["endpoints"]["ollama"] = "http://user:" + "pw" + "@127.0.0.1:1"
    else:
        rig["fallback"]["model"] = secret
    problems = rigtool.validate(rig)
    assert problems
    assert secret not in " ".join(problems) and "pw@" not in " ".join(problems)


def test_write_creates_0600_file_and_check_passes(tmp_path: Path):
    path = tmp_path / "cfg" / "rig.json"
    out = cli(RIG, "write", "--path", path, "--lane", "web=agent-browser", "--fallback", "prov/mod", "--uploader", "upload-tool")
    assert out.returncode == 0, out.stderr
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["fallback"] == {"provider": "prov", "model": "mod"}
    assert cli(RIG, "check", "--path", path).returncode == 0


def test_write_refuses_secret_and_leaves_no_file(tmp_path: Path):
    path = tmp_path / "rig.json"
    out = cli(RIG, "write", "--path", path, "--uploader", "up --token " + FAKE_TOKEN)
    assert out.returncode == 2
    assert FAKE_TOKEN not in out.stdout + out.stderr
    assert not path.exists()


def test_write_dry_run_writes_nothing(tmp_path: Path):
    path = tmp_path / "rig.json"
    out = cli(RIG, "write", "--path", path, "--lane", "web=agent-browser", "--dry-run")
    assert out.returncode == 0 and not path.exists() and "agent-browser" in out.stdout


def test_check_flags_loose_mode_and_invalid_json(tmp_path: Path):
    path = tmp_path / "rig.json"
    path.write_text(json.dumps(good_rig()))
    path.chmod(0o644)
    assert cli(RIG, "check", "--path", path).returncode == 1
    path.chmod(0o600)
    assert cli(RIG, "check", "--path", path).returncode == 0
    path.write_text("{ nope")
    bad = cli(RIG, "check", "--path", path)
    assert bad.returncode == 1 and "not valid JSON" in bad.stderr


def test_discover_is_read_only_json_and_human(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    out = cli(RIG, "discover", "--no-net", "--no-gh", "--home", home)
    assert out.returncode == 0
    data = json.loads(out.stdout)
    assert "lanes" in data and "harnesses" in data
    assert FAKE_HOME not in out.stdout
    human = cli(RIG, "discover", "--human", "--no-net", "--no-gh", "--home", home)
    assert human.returncode == 0 and "lane" in human.stdout and "tools found" in human.stdout
    assert list(home.iterdir()) == []


# install: slot rendering --------------------------------------------------


def run_install(home: Path, *args: str) -> int:
    return install.run(["--home", str(home), *args], environ={})


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    (h / ".claude").mkdir(parents=True)
    return h


@pytest.fixture
def rigfile(tmp_path: Path) -> Path:
    return make_rig_full(tmp_path / "rig.json")


def make_rig_full(path: Path) -> Path:
    path.write_text(json.dumps(good_rig()))
    path.chmod(0o600)
    return path


def rendered(tmp_path: Path) -> Path:
    return tmp_path / "rendered"


def test_stock_install_without_rig_has_no_rendering(home: Path, tmp_path: Path, capsys):
    # No --rig and no default rig file under the fake home: stock symlink to the checkout.
    assert run_install(home, "--client", "claude", "--only", "prove", "--no-deps", "--render-dir", str(rendered(tmp_path))) == 0
    entry = home / ".claude" / "skills" / "prove"
    assert entry.is_symlink() and entry.resolve() == (ROOT / "skills" / "prove").resolve()
    assert not rendered(tmp_path).exists()
    assert "rendered" not in capsys.readouterr().out


def test_install_renders_slot_from_rig(home: Path, tmp_path: Path, rigfile: Path):
    args = ["--client", "claude", "--only", "prove", "--no-deps", "--rig", str(rigfile), "--render-dir", str(rendered(tmp_path))]
    assert run_install(home, *args) == 0
    entry = home / ".claude" / "skills" / "prove"
    text = (entry / "SKILL.md").read_text()
    assert "Fallback model: `prov/mod-1`" in text and "Lane web: `agent-browser`" in text and "Media uploader: `upload-tool`" in text
    assert "Stock defaults, no local rig" not in text
    assert (entry / "references" / "surfaces.md").is_file()
    assert (entry / "scripts" / "proof-pack.py").is_file()
    stock = (ROOT / "skills" / "prove" / "SKILL.md").read_text()
    assert "Stock defaults, no local rig" in stock  # the repo copy stays stock
    marker = json.loads((rendered(tmp_path) / "prove" / ".jstack-install.json").read_text())
    assert marker["rendered"] is True
    assert {"source_digest", "rig_digest", "rendered_digest"} <= set(marker)


def test_overlay_cap_falls_back_to_stock(home: Path, tmp_path: Path, capsys):
    big = good_rig()
    big["lanes"] = {f"lane{i:02d}": [f"tool-{i:02d}-{j:02d}-padding-padding" for j in range(8)] for i in range(12)}
    path = tmp_path / "rig.json"
    path.write_text(json.dumps(big))
    path.chmod(0o600)
    code = run_install(
        home, "--client", "claude", "--only", "prove", "--no-deps", "--rig", str(path), "--render-dir", str(rendered(tmp_path))
    )
    err = capsys.readouterr().err
    assert code == 1 and "1024-byte cap" in err
    entry = home / ".claude" / "skills" / "prove"
    assert "Stock defaults, no local rig" in (entry / "SKILL.md").read_text()


def test_render_skill_raises_over_cap(tmp_path: Path):
    big = good_rig()
    big["lanes"] = {f"lane{i:02d}": [f"tool-{i:02d}-{j:02d}-padding-padding" for j in range(8)] for i in range(12)}
    with pytest.raises(ValueError, match="cap"):
        install.render_skill("prove", big, install.rig_digest(big), tmp_path / "r")


def test_check_reports_drift_when_rig_changes_and_reconcile_repairs(home: Path, tmp_path: Path, rigfile: Path):
    args = ["--client", "claude", "--only", "prove", "--no-deps", "--rig", str(rigfile), "--render-dir", str(rendered(tmp_path))]
    assert run_install(home, *args) == 0
    assert run_install(home, "--check", *args) == 0

    changed = good_rig()
    changed["fallback"] = {"provider": "prov", "model": "mod-2"}
    rigfile.write_text(json.dumps(changed))
    assert run_install(home, "--check", *args) == 1  # drift, and --check never rewrites
    assert "mod-1" in (home / ".claude" / "skills" / "prove" / "SKILL.md").read_text()

    assert run_install(home, "--reconcile", *args) == 0
    text = (home / ".claude" / "skills" / "prove" / "SKILL.md").read_text()
    assert "mod-2" in text and "mod-1" not in text
    assert run_install(home, "--check", *args) == 0


def test_check_reports_edited_rendered_folder(home: Path, tmp_path: Path, rigfile: Path, capsys):
    args = ["--client", "claude", "--only", "prove", "--no-deps", "--rig", str(rigfile), "--render-dir", str(rendered(tmp_path))]
    assert run_install(home, *args) == 0
    (rendered(tmp_path) / "prove" / "SKILL.md").write_text("edited\n")
    capsys.readouterr()
    assert run_install(home, "--check", *args) == 1
    assert "drift (rendered folder edited)" in capsys.readouterr().out


def test_reconcile_touches_only_owned_entries(home: Path, tmp_path: Path, rigfile: Path):
    skills = home / ".claude" / "skills"
    (skills / "prove").mkdir(parents=True)
    (skills / "prove" / "SKILL.md").write_text("mine\n")
    args = ["--client", "claude", "--only", "prove", "--no-deps", "--rig", str(rigfile), "--render-dir", str(rendered(tmp_path))]
    assert run_install(home, "--reconcile", *args) == 0
    assert (skills / "prove" / "SKILL.md").read_text() == "mine\n"
    assert not skills.joinpath("hindsight").exists()


def test_reconcile_installs_nothing_new(home: Path, tmp_path: Path, rigfile: Path):
    args = ["--client", "claude", "--rig", str(rigfile), "--render-dir", str(rendered(tmp_path))]
    assert run_install(home, "--reconcile", *args) == 0
    assert not (home / ".claude" / "skills").exists()


def test_uninstall_removes_rendered_link(home: Path, tmp_path: Path, rigfile: Path):
    args = ["--client", "claude", "--only", "prove", "--no-deps", "--rig", str(rigfile), "--render-dir", str(rendered(tmp_path))]
    assert run_install(home, *args) == 0
    assert run_install(home, "--uninstall", "--client", "claude", "--only", "prove") == 0
    assert not (home / ".claude" / "skills" / "prove").exists()


def test_copy_mode_renders_and_checks_ok(home: Path, tmp_path: Path, rigfile: Path):
    args = ["--client", "claude", "--only", "prove", "--no-deps", "--mode", "copy", "--rig", str(rigfile), "--render-dir", str(rendered(tmp_path))]
    assert run_install(home, *args) == 0
    entry = home / ".claude" / "skills" / "prove"
    assert not entry.is_symlink() and "Fallback model" in (entry / "SKILL.md").read_text()
    assert run_install(home, "--check", *args) == 0


def test_invalid_rig_stops_the_install(home: Path, tmp_path: Path):
    bad = tmp_path / "rig.json"
    bad.write_text("{ not json")
    with pytest.raises(SystemExit):
        run_install(home, "--client", "claude", "--only", "prove", "--no-deps", "--rig", str(bad))
    assert not (home / ".claude" / "skills").exists()


def test_deps_and_exclusive_flags(home: Path, tmp_path: Path):
    assert install.DEPS["jstack-setup"] == ("prove",)
    assert install.resolve(["jstack-setup"]) == ["jstack-setup", "prove"]
    with pytest.raises(SystemExit):
        run_install(home, "--check", "--reconcile")
    with pytest.raises(SystemExit):
        run_install(home, "--install-hook", "--reconcile")


def test_install_hook_writes_and_never_clobbers(home: Path, tmp_path: Path, capsys):
    hooks = tmp_path / "hooks"
    assert run_install(home, "--client", "claude", "--only", "prove", "--no-deps", "--install-hook", "--hooks-dir", str(hooks)) == 0
    for name in ("post-merge", "post-checkout"):
        hook = hooks / name
        assert hook.is_file() and os.access(hook, os.X_OK)
        assert "--reconcile" in hook.read_text() and install.HOOK_MARK in hook.read_text()
    # Re-running updates its own hooks.
    assert run_install(home, "--client", "claude", "--only", "prove", "--no-deps", "--install-hook", "--hooks-dir", str(hooks)) == 0
    (hooks / "post-merge").write_text("#!/bin/sh\necho theirs\n")
    capsys.readouterr()
    code = run_install(home, "--client", "claude", "--only", "prove", "--no-deps", "--install-hook", "--hooks-dir", str(hooks))
    assert code == 1 and "echo theirs" in (hooks / "post-merge").read_text()
    assert "skipped" in capsys.readouterr().err


# slot syntax and privacy rules -------------------------------------------


def test_render_text_only_swaps_known_slot_and_keeps_unknown():
    text = "a\n<!-- jstack:slot:rig -->\nstock\n<!-- /jstack:slot:rig -->\nb\n<!-- jstack:slot:other -->x<!-- /jstack:slot:other -->\n"
    out = install.render_text(text, good_rig())
    assert "stock" not in out and "prov/mod-1" in out
    assert "<!-- jstack:slot:other -->x<!-- /jstack:slot:other -->" in out
    assert install.render_text(text, {"schema": "jstack.rig/1"}) == text  # empty rig keeps stock text


def test_validator_checks_slot_pairs(tmp_path: Path):
    ok = tmp_path / "ok"
    ok.mkdir()
    (ok / "SKILL.md").write_text("<!-- jstack:slot:rig -->\nx\n<!-- /jstack:slot:rig -->\n")
    assert validator.check_slots(ok) == []
    for body in (
        "<!-- jstack:slot:rig -->\nno close\n",
        "<!-- jstack:slot:rig -->\n<!-- /jstack:slot:other -->\n",
        "<!-- /jstack:slot:rig -->\n",
    ):
        bad = tmp_path / "bad"
        bad.mkdir(exist_ok=True)
        (bad / "SKILL.md").write_text(body)
        assert validator.check_slots(bad), body


@pytest.mark.parametrize("name", ["rig.json", "profile.toml", "sub/dir/rig.json", "x/profile.toml"])
def test_privacy_blocks_private_config_files(name: str):
    assert privacy.forbidden_file(name)


@pytest.mark.parametrize("name", ["rig.example.json", "profile.example.toml", "skills/jstack-setup/rig.example.json"])
def test_privacy_allows_example_files(name: str):
    assert privacy.forbidden_file(name) is None


def test_proof_pack_redacts_json_secrets(tmp_path: Path):
    pack = tmp_path / "pack"
    assert cli(PACK, "init", "--dir", pack, "--task", "json-redact", "--head", "abc1234").returncode == 0
    out = cli(
        PACK,
        "run",
        "--dir",
        pack,
        "--head",
        "abc1234",
        "--label",
        "json",
        "--",
        sys.executable,
        "-c",
        'print(\'{"password": "hunter2", "token": "opaque-value"}\')',
    )
    assert out.returncode == 0
    assert "hunter2" not in out.stdout and "opaque-value" not in out.stdout
    data = json.loads((pack / "pack.json").read_text())
    log = (pack / "logs" / Path(data["steps"][0]["log"]).name).read_text()
    assert "hunter2" not in log and "opaque-value" not in log
    assert '"password": "[REDACTED]"' in log and '"token": "[REDACTED]"' in log


def test_later_gate_blocker_stays_active_after_earlier_artifact(tmp_path: Path):
    pack = tmp_path / "pack"
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n1234")
    assert cli(PACK, "init", "--dir", pack, "--task", "gate-order", "--head", "abc1234", "--level", "L3").returncode == 0
    assert cli(PACK, "attach", "--dir", pack, "--head", "abc1234", "--surface", "web", "--level", "L3", "--kind", "screenshot", shot).returncode == 0
    assert cli(PACK, "block", "--dir", pack, "--head", "abc1234", "--surface", "web", "--class", "access-denied", "--reason", "403 after login").returncode == 0
    bad = cli(PACK, "verify", "--dir", pack, "--head", "abc1234")
    assert bad.returncode == 1 and "access-denied" in bad.stdout + bad.stderr
    # A subsequent qualifying artifact after the blocker resolves it.
    assert cli(PACK, "attach", "--dir", pack, "--head", "abc1234", "--surface", "web", "--level", "L3", "--kind", "screenshot", shot).returncode == 0
    assert cli(PACK, "verify", "--dir", pack, "--head", "abc1234").returncode == 0


def test_install_hook_preserves_custom_rig_and_render_dir(home: Path, tmp_path: Path, rigfile: Path):
    hooks = tmp_path / "hooks"
    rdir = rendered(tmp_path)
    args = [
        "--client",
        "claude",
        "--only",
        "prove",
        "--no-deps",
        "--rig",
        str(rigfile),
        "--render-dir",
        str(rdir),
        "--install-hook",
        "--hooks-dir",
        str(hooks),
    ]
    assert run_install(home, *args) == 0
    hook = hooks / "post-merge"
    body = hook.read_text()
    assert "--rig" in body and str(rigfile.resolve()) in body and "--render-dir" in body and str(rdir.resolve()) in body
    proc = subprocess.run(["sh", str(hook)], check=False)
    assert proc.returncode == 0
    assert "Fallback model: `prov/mod-1`" in (home / ".claude" / "skills" / "prove" / "SKILL.md").read_text()


def test_sol_loop_regressions_rig_and_pack(tmp_path: Path):
    # S1: legitimate >=32-char hyphen/slash model IDs pass looks_secret; S6: trailing newline fails.
    rig = good_rig()
    rig["fallback"] = {"provider": "opencode", "model": "openrouter/anthropic/claude-sonnet-4-5-20250929"}
    assert rigtool.validate(rig) == []
    bad_nl = good_rig()
    bad_nl["lanes"] = {"web": ["agent-browser\n"]}
    assert rigtool.validate(bad_nl)
    # S8: --lane NAME= clears a lane cleanly and malformed pair exits 2.
    rig_path = tmp_path / "rig.json"
    assert cli(RIG, "write", "--path", rig_path, "--lane", "vnc=wayvnc", "--lane", "web=agent-browser").returncode == 0
    assert cli(RIG, "write", "--path", rig_path, "--merge", "--lane", "vnc=").returncode == 0
    assert "vnc" not in json.loads(rig_path.read_text())["lanes"]
    assert cli(RIG, "write", "--path", rig_path, "--endpoint", "broken").returncode == 2
    # S2, S3, S4, S5: slash label, prefixed secret/PEM/uppercase ts host, surface validation, stale block.
    pack = tmp_path / "pack"
    assert cli(PACK, "init", "--dir", pack, "--task", "sol", "--head", "aaa1111").returncode == 0
    out = cli(PACK, "run", "--dir", pack, "--head", "aaa1111", "--label", "api/auth", "--", sys.executable, "-c", 'print("ok")')
    assert out.returncode == 0
    fake_tailnet = "BOX.TAIL99." + "TS.NET"
    red = proof.redact_text(
        f'{{"access_token": "sec123"}} GITHUB_TOKEN=tok456 {fake_tailnet}\n'
        "-----BEGIN RSA PRIVATE KEY-----\nBODYSECRET\n-----END RSA PRIVATE KEY-----"
    )
    for leaked in ("sec123", "tok456", "BODYSECRET", "TAIL99"):
        assert leaked not in red
    shot = tmp_path / "s.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n1234")
    assert cli(PACK, "attach", "--dir", pack, "--head", "aaa1111", "--surface", "AUTH", "--level", "L3", "--kind", "screenshot", shot).returncode == 2
    assert cli(PACK, "block", "--dir", pack, "--head", "aaa1111", "--surface", "VNC", "--class", "physical", "--reason", "x", "--tried", "a=1", "--tried", "b=2").returncode == 2
    assert cli(PACK, "block", "--dir", pack, "--head", "aaa1111", "--surface", "web", "--class", "access-denied", "--reason", "403").returncode == 0
    stale_check = cli(PACK, "verify", "--dir", pack, "--head", "bbb2222", "--allow-blocked")
    assert stale_check.returncode == 1 and "stale block" in stale_check.stdout + stale_check.stderr
    # S7: inverted slots fail check_slots.
    inv = tmp_path / "inv"
    inv.mkdir()
    (inv / "SKILL.md").write_text("<!-- /jstack:slot:rig -->\nx\n<!-- jstack:slot:rig -->\n")
    assert validator.check_slots(inv)
