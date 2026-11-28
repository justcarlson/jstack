---
name: epic
description: Research, plan and ship ambitious multi-issue or multi-repo work end to end. Triggers on 'epic', '/epic', 'ship epic', or bold-options research, a plan for sign-off, then parallel issues, worktrees, zero-downtime deploys and live proof.
---

# Epic

Take an ambitious idea from bold research to verified production rollout across
repos, with one human review stop at the plan.

`epic` composes `council`, `sol-loop`, `full-send`, `prove`, `file-pr`, `pr`,
`babysit-pr`, `t3-launch-worktrees`, and any plan-publishing skill. Use the
models your `AGENTS.md` or `CLAUDE.md` configures, with cross-family review and
multi-model `council`.

"The plan" is a reviewable artifact (Tailplan/taildoc, Postplan, Markdown, or a
gist) updated **in place** so the reader keeps one link.

## Entry points

- **`epic <goal>`**: run Stages 1–2, publish one decision-ready plan, and
  **stop for approval**. Do not file issues, edit code, or touch production
  before confirmation.
- **`ship epic`** (or `ship epic <plan-url>`, or a clear go-ahead on an active
  `epic` thread): run Stages 3–6 autonomously to production and close with an
  updated plan.

## Stage 1: Bold, multi-model discovery

Stay read-only. Understand the real system first.

1. Audit live state first: code, upstream repos and releases, prior agent
   threads, and telemetry or log history when relevant (`hindsight`, `logs`).
2. Fan out read-only research or design delegates in parallel on configured
   models. Use `council` to compare major architectures. Tell each delegate to
   stay read-only and start no subagents.
3. Be bold: include high-leverage options beyond today's wiring next to the
   simplest maintainable design. Stress-test assumptions.

## Stage 2: Decision-ready plan (stop here)

1. Publish the proposal as the plan artifact. Delegate rich layout to the
   configured design model when another model drives. Keep a concise top
   verdict, diagrams over dense tables, deep specs collapsible, and a 390 px
   mobile check.
2. Lead with the recommended design, core primitives, and an explicit
   **Skip / Not Now** list.
3. Keep simplicity, zero-downtime cutover, and observability (metadata-only
   unless asked) in scope; do not punt without a hard blocker.
4. Ask only blocking architecture, cost, or account questions, numbered with
   recommended defaults so the user can reply `defaults` or override.
5. Update the **same plan link** until the user replies `ship epic` or gives an
   explicit go-ahead.

## Stage 3: Issue decomposition into waves

Once confirmed:

1. File clear GitHub issues across every touched repo before editing code.
2. Group issues into **non-overlapping parallel waves** by repo and file scope.
   Mark shared-file dependencies: dependent waves start only after their
   prerequisite merges and deploys cleanly to `main`.
3. Include every cross-repo touchpoint: telemetry, upstream upgrade
   compatibility, public mirror syncs, rollouts to each host, and docs.

## Stage 4: Orchestrate isolated `tstack` worktrees

1. The parent thread is the **pure orchestrator**: launch waves, track workers,
   resolve blockers, own merge order. No feature edits in its checkout.
2. When `ship epic` starts, check `t3_thread_list` (`currentThreadId`,
   `pinned`). If unpinned, pin it (`t3_thread_organize`, `action: "pin"`, no
   `threadId`) so no sweep settles it between waves or post-merge proof. Follow
   T3's PR linking and watching rules for PRs you own; do not link PRs a
   `t3_thread_launch` worker owns.
3. Run each non-overlapping issue in its own worktree: `delegate_task`
   (`isolation: "worktree"`) keeps workers out of the sidebar;
   `t3_thread_launch` (`t3-launch-worktrees`) only for requested top-level issue
   threads. Use the configured worker model, or a stronger design model when
   asked or the issue is design-heavy.
4. Give each worker a file scope, issue link, proof bar, and the rule that the
   orchestrator owns merge order across dependent waves.
5. Every deliverable PR follows `tstack`:
   - `full-send` per deliverable (implement, prove, review, file PR, babysit).
   - `sol-loop` (cross-family review) for routine PRs.
   - `council` for architectural, security, multi-repo, or high-risk PRs, or
     when a worker is blocked or uncertain.
   - `pr` body, `file-pr`, `babysit-pr`. Where the repo uses them, add a
     `## Review ledger` table and host screenshots with `pr-image`.
6. Worker output is a claim ([prove](../prove/SKILL.md)). Before a PR merges
   or counts as done, run `proof-pack.py verify` on its head and open the
   attached screenshots, video, or audio yourself. If a worker punts or refuses
   a user-authorized task or proof step, dispatch `prove`'s configured fallback
   worker with a neutral brief (goal, authorization, packet path) minus prior
   refusal text, one at a time for single-slot limits. Never escalate an
   unapproved `full-send` user gate, a CAPTCHA, anti-bot or 2FA challenge, or an
   access or approval denial: stop and ask.
7. Stay unattended under `full-send`'s four-gate rule: interrupt the user only
   for (1) irreversible data deletion, (2) money, accounts, signing, or
   external publishing, (3) unsanctioned production changes, or (4) a secret or
   login via `request_secret`. Default the rest and record each call.

## Stage 5: Zero-downtime sequential merge and live proof

1. Merge **one PR or non-overlapping wave at a time**, owned by the
   orchestrator, only after required CI, preview deploys, automated reviews,
   and the Stage 4 proof gate pass. After merging a PR from a `t3_thread_launch`
   worker you launched, check `t3_thread_read`: if `status` is not `running`/
   `preparing`/`starting`/`queued`, `pinned` is `false`, `openPullRequestCount`
   and `pendingRequestCount` are `0`, and `pendingBackgroundTasks` is empty,
   settle it (`t3_thread_organize`, `action: "settle"`, `threadId`).
2. Wait for production deploy health before rebasing and launching dependent
   waves.
3. Protect uptime: additive-first migrations, backwards-compatible cutovers,
   rollback or dead-man guards for infra or network changes. After merge, prune
   stale deploy snapshots if storage is tight, remove temporary worktrees, and
   fast-forward local `main`.
4. Prove every deliverable live before calling it done: production health, real
   tool or UI execution, telemetry rows when telemetry changed, PR screenshots,
   and clean drift checks (`--check` or equivalent) on online targets. Run
   `proof-pack.py verify` on the merged head and inspect the artifacts. Mocks
   and green unit tests alone do not close an epic.

## Stage 6: Close the loop

1. Update the **plan in place** with shipped status, PR links, deploy URLs,
   live proof, decisions made, and any remaining manual user step.
2. Settle remaining `t3_thread_launch` workers you launched whose PRs merged
   (after the Stage 5 `t3_thread_read` check). On clean completion with no open
   PRs or user steps, settle this thread last if Stage 4 added the pin (keep
   any user pin; `t3_thread_organize`, `action: "settle"`, no `threadId`). On a
   blocker, abort, or user step, do not settle it; `unpin` only if Stage 4
   added the pin.
3. Send a brief report: lead with any blocker, link the plan and key PRs or
   deploys, confirm zero open PRs or issues (or list what stayed open and why),
   and end with one or two plain sentences on what is live and what still needs
   the user.

## Traps

- `full send` is not the epic trigger; `full-send` belongs to each deliverable.
- Never run `ship epic` unpinned: T3's merge, close, and inactivity sweeps
  settle unpinned threads (even closed PRs with
  `sidebarAutoSettleOnMerge: false`), clearing watches and cutting off waves.
- Never settle another thread blindly: settling by `threadId` acts at once,
  clearing pins, watches, and pending questions. Settle only workers you
  launched whose PRs merged, after the Stage 5 `t3_thread_read` check.
- Never merge overlapping PRs together; serialize across shared files and deploys.
- Never stop at "PR opened" while CI, deploys, or waves are active.
- Behind a chat bridge (such as `t3-slack`), chat posts only the final text of
  the turn answering a user message. If background turns continue, say what
  runs and what finishes next before ending the turn.
