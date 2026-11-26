---
name: epic
description: Research, plan and ship ambitious multi-issue or multi-repo work end to end. Triggers on 'epic', '/epic', 'ship epic', or bold-options research, a plan for sign-off, then parallel issues, worktrees, zero-downtime deploys and live proof.
---

# Epic

Take an ambitious idea from bold research to verified production rollout across
one or more repos, with one human review stop at the plan.

`epic` composes existing skills (`council`, `sol-loop`, `full-send`, `file-pr`,
`pr`, `babysit-pr`, `t3-launch-worktrees`, and any plan-publishing skill). Use
the models your `AGENTS.md` or `CLAUDE.md` configures, with cross-family review
and multi-model `council` per `sol-loop` and `council`.

"The plan" is a reviewable artifact (Tailplan/taildoc, Postplan, Markdown, or a
gist) updated **in place** across revisions so the reader keeps one link.

## Entry points

- **`epic <goal>`**: run Stages 1–2, publish one decision-ready plan, and
  **stop for approval**. Do not file issues, edit code, or touch production
  before confirmation.
- **`ship epic`** (or `ship epic <plan-url>`, or a clear go-ahead on an active
  `epic` thread): run Stages 3–6 autonomously to production and close with an
  updated plan.

Do not use `full send` as the epic trigger; `full-send` runs per deliverable
issue, while `ship epic` starts multi-issue orchestration.

## Stage 1: Bold, multi-model discovery

Stay read-only. Understand the real system before proposing anything.

1. Audit live state first: code, upstream repos and releases, prior agent
   threads, and telemetry or log history when relevant (e.g. `hindsight` or
   `logs`).
2. Fan out read-only research or design delegates in parallel using configured
   models. Use `council` to compare major architectures. Tell each delegate to
   stay read-only and start no subagents.
3. Be bold: include high-leverage options beyond today's wiring alongside the
   simplest maintainable design. Stress-test assumptions rather than agreeing.

## Stage 2: Decision-ready plan (stop here)

1. Publish the proposal as the plan artifact. Delegate rich layout refinement
   to the configured design model when another model drives. Keep a concise top
   verdict, charts or diagrams over dense tables, deep specs in collapsible
   sections, and a 390 px mobile check.
2. Lead with the recommended design, core primitives, and an explicit
   **Skip / Not Now** list.
3. Keep architectural simplicity, zero-downtime cutover, and observability
   (metadata-only unless asked) in scope by default; do not punt without a hard
   blocker.
4. Ask only blocking architecture, cost, or account questions upfront, numbered
   with recommended defaults so the user can reply `defaults` or override.
5. Update the **same plan link in place** across revisions until the user
   replies `ship epic` (or an explicit go-ahead).

## Stage 3: Issue decomposition into waves

Once confirmed:

1. File clear GitHub issues across every touched repo before editing code.
2. Group issues into **non-overlapping parallel waves** by repo and file scope.
   Mark shared-file dependencies so dependent waves start only after their
   prerequisite merges and deploys cleanly to `main`.
3. Include every cross-repo touchpoint: telemetry or logging, upstream upgrade
   compatibility, public mirror syncs, rollouts to each target host or
   environment, and docs.

## Stage 4: Orchestrate isolated `tstack` worktrees

1. The parent thread acts as **pure orchestrator**: launch waves, track worker
   state, resolve blockers, and own merge order. Keep direct feature edits out
   of the coordinator checkout during parallel fan-out.
2. When `ship epic` starts, check `t3_thread_list` (`currentThreadId`,
   `pinned`). If unpinned, pin it (`t3_thread_organize`, `action: "pin"`, no
   `threadId`) so no T3 sweep settles it between waves or post-merge proof.
   Follow T3's PR linking and watching rules for PRs the orchestrator owns; do
   not link PRs a `t3_thread_launch` worker owns.
3. Run each non-overlapping issue in its own worktree: use `delegate_task`
   (`isolation: "worktree"`) so workers stay out of the top-level sidebar, or
   `t3_thread_launch` (`t3-launch-worktrees`) only when top-level issue threads
   are requested. Use the configured default worker model, or a stronger design
   model when the user asks or the issue is design-heavy.
4. Give each worker an explicit file scope, issue link, proof bar, and the rule
   that the orchestrator owns final merge order when waves depend on each other.
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
   reviews pass. After merging a PR from a `t3_thread_launch` worker you
   launched, check `t3_thread_read`: if `status` is not `running`/`preparing`/
   `starting`/`queued`, `pinned` is `false`, `openPullRequestCount` and
   `pendingRequestCount` are `0`, and `pendingBackgroundTasks` is empty, settle
   it (`t3_thread_organize`, `action: "settle"`, `threadId`).
2. Wait for production deploy health before rebasing and launching dependent
   waves.
3. Protect uptime: additive-first migrations, backwards-compatible cutovers,
   and rollback or dead-man guards for infra or network changes. Clean up after
   merge: prune stale deploy snapshots if storage is tight, remove temporary
   worktrees, and fast-forward local `main`.
4. Prove every deliverable live before calling it done: production health, real
   tool or UI execution, telemetry rows arriving when telemetry changed, PR
   screenshots, and clean drift checks (`--check` or equivalent) across online
   targets. Green unit tests or mocks alone do not close an epic.

## Stage 6: Close the loop

1. Update the original **plan in place** with shipped status, PR links, deploy
   URLs, live proof, decisions made, and any remaining manual user step.
2. Settle any remaining `t3_thread_launch` workers you launched whose PRs
   merged (passing the Stage 5 `t3_thread_read` check). On clean Stage 6
   completion with no open PRs or user steps left, settle this thread last if
   Stage 4 added the pin (keep any user pin; `t3_thread_organize`,
   `action: "settle"`, no `threadId`). On a blocker, abort, or user step, do
   not settle this thread; `unpin` only if Stage 4 added the pin.
3. Send a brief report: lead with any blocker, link the updated plan and key
   PRs or deploys, confirm zero open PRs or issues remain (or list what stayed
   open and why), and end with one or two plain sentences on what is live and
   what, if anything, still needs the user.

## Traps

- Do not treat `full send` as the epic confirmation trigger; `full-send` belongs
  to each deliverable PR.
- Do not run `ship epic` unpinned: T3's merge, close, and inactivity sweeps
  settle unpinned threads (closed PRs settle even with
  `sidebarAutoSettleOnMerge: false`), clearing watches and cutting off waves.
- Never settle another thread blindly: settling by `threadId` acts at once,
  even mid-run, clearing pins, watches, and pending questions. Settle only
  `t3_thread_launch` workers you launched whose PRs merged, after the Stage 5
  `t3_thread_read` check passes.
- Do not merge overlapping PRs together; serialize merges across shared files
  and live deploys to preserve zero downtime.
- Do not stop at "PR opened" while CI, deploys, or later waves are still active.
- Behind a chat bridge (such as `t3-slack`), chat posts only the final text of
  the turn answering a user message. If background turns continue, state what
  is running and what finishes next before ending the turn.
