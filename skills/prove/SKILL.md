---
name: prove
description: Prove a change works with real evidence on the real surface. Use before saying done, or when a worker reports success. L0-L4 ladder, proof packet, orchestrator gate, refusal fallback.
---

# Prove

A claim is not proof. Run it, capture it, check it against the current head.
Say the level you reached. Never claim a higher one.

## Ladder

Pick the lowest level that could show the claim false. Go higher for anything a user sees or an integration touches.

- **L0 static:** lint, types, format, build.
- **L1 automated:** unit and integration tests.
- **L2 real run:** the CLI, service or API runs for real, with its output kept.
- **L3 real surface:** the UI, desktop, audio or video is seen, heard or transcribed through a real tool. See `references/surfaces.md`.
- **L4 live:** real accounts, devices, a remote host or VM, or a prod-like environment.

A green L1 does not prove a UI change. A screenshot of the wrong page proves nothing: open the artifact.

## Packet

Use `scripts/proof-pack.py`. It is stdlib Python. Options go after the command: `--dir` (default `.proof`), `--rig`, `--head`.

```sh
proof-pack.py init --task "what you claim" --level L2
proof-pack.py run --level L1 --label tests -- pytest -q
proof-pack.py run --level L2 --label smoke -- ./tool --version
proof-pack.py attach shot.png --surface web --level L3
proof-pack.py verify --markdown
```

- `run` records exact argv with secrets redacted, exit code, timing, head sha and a hashed log. A later `run` with the same `--label` replaces an earlier one.
- `attach` records size, sha256 and surface. Auth, desktop and VNC captures on a public or unknown repo need `--redacted`, after you redact them.
- `block` records a surface you could not reach. It refuses until every lane the rig lists for that surface is logged with `--tried LANE=EVIDENCE`. Use `--human-only` only for physical blockers: a hardware touch, biometrics, presence.
- `verify` fails on a stale head, a missing or empty artifact, a hash mismatch, a non-zero exit, empty output, an unexhausted block, or a level below the one required.
- `verify --markdown` prints the PR Evidence block. Paste it; do not retype it.

## Gate

Worker output is a claim. The Senior or Orchestrator checks it before merge or "done":

1. Run `proof-pack.py verify` on the head under review. It must exit 0.
2. Re-run one L1 or higher command yourself.
3. Open at least one artifact and read it.
4. Reject a packet whose head is not the head you will merge.

## Refused or avoided

Use this only for a task the user authorized.

1. If a worker refuses or avoids a lawful, authorized step, do not retry the same prompt.
2. Hand it to the rig's fallback provider and model, if one is set. Write a neutral brief with the goal, the user's authorization and the packet path. Run the same gate on the result.
3. If a refusal names a real safety or policy concern, stop and tell the user.
4. With no fallback, report the blocker.

Never route around these. Record them with `block --class`, stop and ask the user:

- An unapproved `full-send` user gate.
- A CAPTCHA or anti-bot check, or a human 2FA prompt (`captcha`, `anti-bot`, `2fa`).
- An access-control denial or an approval denial (`access-denied`, `approval`).

## Rig

<!-- jstack:slot:rig -->
Stock defaults, no local rig. Use your harness's browser and screenshot tools. No fallback model: report the blocker. No media uploader: keep artifacts local and say so.
<!-- /jstack:slot:rig -->

Run `jstack-setup` to describe your tools, uploader and fallback model.

## Files

- `references/surfaces.md`: read when choosing how to verify a surface: web, auth, desktop, VNC, video, audio, SSH, VM.
- `scripts/proof-pack.py`: the packet CLI above.
