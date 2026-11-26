---
name: epic
description: Research, plan and ship ambitious multi-issue or multi-repo work end to end. Triggers on 'epic', '/epic', 'ship epic', or bold-options research, a plan for sign-off, then parallel issues, worktrees, zero-downtime deploys and live proof.
---

# Epic

Take an ambitious idea from bold research to a verified production rollout across
one or more repositories, with one clean human review stop at the plan.

`epic` composes existing skills (`council`, `sol-loop`, `full-send`, `file-pr`,
`pr`, `babysit-pr`, `t3-launch-worktrees`, and a plan-publishing skill if you
have one) rather than replacing them. Use the models your `AGENTS.md` or
`CLAUDE.md` configures for delegates, with cross-family review and multi-model
`council` as `sol-loop` and `council` define.

"The plan" is a reviewable plan artifact: Tailplan/taildoc, Postplan, a Markdown
document, or a gist. Pick one and update it **in place** across revisions, so
the reader keeps one link.

## Entry points

- **`epic <goal>`**: run Stages 1 and 2, publish one decision-ready plan, and
  **stop for approval**. Do not file issues, edit repo code, or touch
  production before the user confirms.
- **`ship epic`** (or `ship epic <plan-url>` from a new thread, or a clear
  go-ahead reply on an active `epic` plan thread): run Stages 3 to 6
  autonomously to live production and close with an updated plan.

Do not use `full send` as the epic confirmation command. `full send` triggers a
single-PR `tstack` workflow; inside an epic, `full-send` runs per deliverable
issue, while `ship epic` starts the multi-issue orchestration.

## Stage 1: Bold, multi-model discovery

Stay read-only. Understand the real system before proposing anything.

1. Audit live state first: current code, upstream repos and releases, prior
   agent threads, and telemetry or log history when history matters (for
   example, with the `hindsight` or `logs` skills when your repository uses
   them).
2. Fan out read-only research or design delegates in parallel, using the models
   your `AGENTS.md` or `CLAUDE.md` configures. Use the `council` when comparing
   major architectures. Tell each delegate to stay read-only and start no
   subagents.
3. Be bold: include high-leverage options not limited by today's wiring alongside
   the simplest maintainable design. Stress-test the user's assumptions instead
   of agreeing by reflex.

## Stage 2: Decision-ready plan (stop here)

1. Publish the proposal as the plan artifact. When another model is driving,
   delegate rich layout refinement to the model your instructions name for
   design work. Keep a concise top verdict, charts or diagrams over dense
   tables, deep technical specs inside collapsible sections, and a 390 px
   mobile check.
2. Lead with the recommended design, the core primitives required, and an
   explicit **Skip / Not Now** list.
3. Keep architectural simplicity, zero-downtime cutover, and observability
   (metadata-only unless asked) in scope by default. Do not punt them to a vague
   later phase without a hard blocker.
4. Ask only blocking architecture, cost, or account questions upfront, numbered
   with recommended defaults so the user can reply with `defaults` or overrides.
5. Update the **same plan link in place** across any revision until the user
   replies with `ship epic` (or an explicit go-ahead on the thread).

## Stage 3: Issue decomposition into waves

Once confirmed:

1. File clear GitHub issues across every touched repository before editing code.
2. Group issues into **non-overlapping parallel waves** by repository and file
   scope. Explicitly mark shared-file dependencies so dependent waves start
   only after their prerequisite merges and deploys cleanly to `main`.
3. Include every cross-repo touchpoint in the wave plan: telemetry or logging
   changes, upstream upgrade compatibility, public mirror syncs, rollouts to
   each target host or deployment environment, and docs.

## Stage 4: Orchestrate isolated `tstack` worktrees

1. The parent thread acts as **pure orchestrator**: launch waves, track worker
   state, resolve blockers, and own merge order. Keep direct feature edits out
   of the coordinator checkout during parallel fan-out.
2. When `ship epic` starts, check `t3_thread_list` (`currentThreadId`,
   `pinned`). If unpinned, pin it (`t3_thread_organize`, `action: "pin"`, no
   `threadId`) so no T3 sweep settles it between waves or post-merge proof.
   Follow T3's PR linking and watching rules for PRs the orchestrator owns; do
   not link PRs a `t3_thread_launch` worker owns.
3. Run each non-overlapping issue in its own isolated worktree (using
   `delegate_task` with `isolation: "worktree"`, or `t3_thread_launch` per
   `t3-launch-worktrees` when top-level issue threads are requested). Use the
   default worker model your `AGENTS.md` or `CLAUDE.md` configures, and a
   stronger design model when the user asks or the issue is design-heavy.
4. Give each worker an explicit file scope, issue link, proof requirements, and
   the rule that the orchestrator owns final merge order when waves depend on
   each other.
5. Every deliverable PR follows `tstack`:
   - `full-send` execution per deliverable (implement, prove, review, file PR,
     babysit CI and bot findings).
   - `sol-loop` (cross-family review) for routine feature and issue PRs.
   - `council` (multi-model, per your configured roster) for architectural,
     security, multi-repo, or high-risk PRs, or whenever a worker is blocked or
     uncertain.
   - `pr` body format, `file-pr`, and `babysit-pr`. When your repository uses
     them, add a `## Review ledger` table to the PR body and host screenshots
     with a `pr-image` helper.
6. Keep execution unattended using `full-send`'s four-gate rule: interrupt the
   user only for (1) irreversible data deletion, (2) money, accounts, signing,
   or external publishing, (3) unsanctioned production changes, or (4) a secret
   or login via `request_secret`. Default everything else and record each call.

## Stage 5: Zero-downtime sequential merge and live proof

1. Merge **one PR or non-overlapping wave at a time**, owned by the
   orchestrator, only after required CI checks, preview deploys, and automated
   reviews pass.
2. Wait for production deploy health before rebasing and launching dependent
   waves.
3. Protect uptime: additive-first migrations, backwards-compatible cutovers,
   and rollback or dead-man guards for infra or network changes. Clean up after
   merge: prune stale deployment snapshots if storage constrains deploys, remove
   temporary worktrees, and fast-forward local `main`.
4. Prove every deliverable live before calling it done: live production health,
   real tool or UI execution, telemetry rows arriving when telemetry changed,
   screenshots attached to the PR, and drift checks (`--check` or equivalent)
   clean across every target host or deployment environment that is online.
   Green unit tests or mocks alone do not close an epic.

## Stage 6: Close the loop

1. Update the original **plan in place** with shipped status, PR links,
   production deploy URLs, live proof, decisions made, and any remaining manual
   step for the user.
2. On clean Stage 6 completion with no open PRs or user steps left, if Stage 4
   added the pin (keep any user pin), settle this thread last
   (`t3_thread_organize`, `action: "settle"`, no `threadId`; it also unpins).
   On a blocker, abort, or user step, do not settle; `unpin` only if Stage 4
   added the pin.
3. Send a brief, scannable report: lead with any blocker, link the updated
   plan and key PRs or deploys, confirm zero open PRs or issues remain (or
   list what stayed open and why), and end with one or two plain sentences on
   what is live and what, if anything, still needs the user.

## Traps

- Do not treat `full send` as the epic confirmation trigger; `full-send` belongs
  to each deliverable PR.
- Do not run `ship epic` unpinned: T3's merge, close, and inactivity sweeps
  settle unpinned threads (closed PRs settle even with
  `sidebarAutoSettleOnMerge: false`), clearing watches and cutting off waves.
- Settle only this thread (no `threadId`). Settling another thread acts at once,
  even mid-run, clearing its pin, watches, and pending questions.
- Do not merge overlapping PRs together; serialize merges across shared files
  and live deployments to preserve zero downtime.
- Do not stop at "PR opened" while CI, deploys, or later waves are still active.
- When running behind a chat bridge (such as `t3-slack`), the chat posts only
  the final text of the turn that answers a user message. If orchestration
  continues in background turns, state what is running and what finishes next
  before ending the turn.
