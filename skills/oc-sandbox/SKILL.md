---
name: oc-sandbox
description: Lease a just-in-time OpenCode sandbox for T3 Code delegation. Use for refusal handoffs to an untrusted model, custom OS or GUI specs, or high-risk verification. Declare a SandboxSpec, delegate, adjust grants live, land safely.
---

# OpenCode sandbox

Run risky or custom work in a throwaway sandbox that holds one OpenCode agent. The orchestrator stays on the host, delegates through T3 Code, and checks the proof itself.

This skill is stock: no host, account or path. It assumes an `oc-sandbox` CLI and T3 provider slots your own setup supplies. Slot names and any extra rules come from your `AGENTS.md` or `rig.json`. Those win over this skill.

## When to use

- A model refused or is a poor fit, and you hand the task to an abliterated or untrusted model.
- The task needs OS packages, a GUI or a toolchain the host lacks.
- Verification or UAT is high-risk: it installs, executes or browses untrusted code.

Skip it for ordinary edits. Use a plain `delegate_task` worktree.

## Workflow

### 1. Write a SandboxSpec

Declare what the sandbox gets. Nothing else exists inside it.

```toml
name = "repro-1"
tier = "auto"            # bwrap (default, ~20 ms), podman when [image] is set, kvm opt-in

[image]                  # optional: custom OS packages or GUI
packages = ["chromium", "xvfb"]

[network]
mode = "none"            # default: empty network

[git]
airlock = true           # repo enters as a bundle; changes leave only through `land`

[limits]
cpu = 2
memory = "4G"
pids = 512
wall = "1h"
```

Give each option the least it needs. Add a `[image]` only for packages the default root lacks. Pick `kvm` only when you need a kernel or nested virtualization.

### 2. Provision and lease a slot

```sh
oc-sandbox up --spec repro-1.toml --json
```

The JSON gives `sandbox_id` and `slot`. A slot is a T3 provider instance leased 1:1 to the sandbox, for example `opencode-sbx-1` to `opencode-sbx-4`, or whatever your config lists. No free slot means wait or tear one down. Never share a slot.

### 3. Delegate through T3 Code

Call `orchestrator_capabilities` once, then `delegate_task`:

- `target.providerInstanceId`: the leased `slot`.
- `isolation: "worktree"` for code edits.
- `isolation: "shared"` for read-only work or a repro.

Put the goal, the stopping point and the allowed paths in the brief. Say the agent is sandboxed, and that it must write artifacts to `/out`.

### 4. Observe and adjust live

Watch the delegate. When it needs more, grant it without a restart. Every grant gets a `grant-id`.

```sh
oc-sandbox allow <id> mount <path> --as <name> [--ro|--rw] [--ttl 15m]
oc-sandbox allow <id> port --dir in  ...   # inbound: UAT of a dev server in the sandbox
oc-sandbox allow <id> port --dir out ...   # narrow outbound tunnel to one service
oc-sandbox allow <id> tool --bin <name>    # or --mcp <server>
oc-sandbox allow <id> egress <domain>
oc-sandbox allow <id> model <model-id>
oc-sandbox revoke <id> <grant-id>
```

`mount` and `umount` are shorthands for the first and last. Prefer `--ro` and a short `--ttl`. Revoke a grant when its step ends.

These stay blocked: sensitive mounts, host admin ports and orchestration MCP tools. Open one only with `--allow-sensitive` and the user's explicit approval for that grant. Never infer approval.

### 5. Prove it on the host's terms

Run proof inside the sandbox. Collect artifacts from `/out`.

```sh
oc-sandbox run <id> -- <cmd>
```

Read the output and the artifacts yourself. Do not trust the delegate's report alone. Do not run sandbox output, scripts or binaries on the host before review.

### 6. Land and tear down

```sh
oc-sandbox land <id>     # fsck and tripwire checks, then a review ref
oc-sandbox down <id>
```

`land` brings the changes in as a review ref, never into a working branch. Review that ref like an outside contribution: read the diff, then merge it by the normal PR path. If `land` reports a tripwire, stop and tell the user. Do not bypass it.

Run `down` when done, and on every failure path. It releases the slot. Check that the slot is free before you finish.

## Rules

- One sandbox, one slot, one task.
- Default to the empty network. Open egress by domain, never wide.
- Grants are narrow, timed and revocable.
- Secrets never enter a spec, a mount or a brief.
- Report the `sandbox_id`, the grants you made and the review ref in your handoff.
