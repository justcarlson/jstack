---
name: t3-launch-worktrees
description: Launch requested T3 Code threads in the intended checkout, or recover an uncertain launch.
---

Use current T3 schemas and routing rules. Use `t3_thread_launch` only for a user-requested new top-level thread; use `delegate_task` for child work.

1. Verify the target server, project Git repository, and intended base ref. Do not assume `main`. Resolve requested models and settings through `orchestrator_capabilities`. For another machine, pass its `environmentId`; IDs belong to that machine.
2. Set `workspaceStrategy`:
   - New checkout: `{type: "worktree", baseRef: "<verified-ref>"}`.
   - Stack: parent branch as `baseRef`, `startFromOrigin: false`. Uncommitted edits are not copied.
   - Existing checkout: `{type: "existing_worktree", worktreePath: "<verified-project-worktree>"}`.
   - Project checkout: `{type: "root"}`.

   Omission uses the project root, regardless of UI defaults or shell directory. Always supply worktree `baseRef`: optional in the schema, it was required at runtime in a previous failed launch.
3. Put the goal, essential context, constraints, and authorized stopping point in `message`; no checkout setup. Retain a unique `clientRequestId` for the launch.
4. Launch, then use `t3_thread_read` to verify project, branch, worktree path, and run state.
5. After an error or lost reply, read the known thread or find recent matches with `t3_thread_list` on that server and project. A failed launch may still create a thread. Retry the same launch with the same request ID. If recovery remains uncertain, report the blocker instead of creating another thread.
6. Follow `t3_thread_wait` instructions to the stopping point, then read the result. Obey returned `next`; end the turn when instructed. Report the returned `link` verbatim and verified outcome or blocker. Launch success is not task completion.
7. If this agent launched a worker thread (`createdBy: "agent"`) for orchestrated work — unless the launch request asked it to stay open — and later merges its PR or closes out its handoff with no user step left, check `t3_thread_read`: once `status` is not `running`/`preparing`/`starting`/`queued`, `pinned` is `false`, `openPullRequestCount` and `pendingRequestCount` are `0`, and `pendingBackgroundTasks` is empty, settle it (`t3_thread_organize`, `action: "settle"`, `threadId`).
