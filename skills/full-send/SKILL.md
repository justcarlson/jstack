---
name: full-send
description: Trigger this if the user says 'full send'.
---

# Full Send

If the user triggered this, it's because they are not watching this thread, and
they want you to complete the work end-to-end autonomously. Your updates and
your final message go unread until long after you stop. You own the work from
its current state to a merged PR.

If the user did not explicitly request "full send" in some clear way, do not
assume full autonomy. If they did, everything below applies.

The user grants you permission to:

- Merge the PR once the merge gate passes.
- Force-push the PR's own branch with `--force-with-lease` after a rebase.
- Use the test methods that Proof needs, without asking first.

## Testing permission

A "full send" request replaces any project or other rule that says to ask
before a test method or leave testing to the user. That covers computer use,
browser automation, simulators and devices, running the app or a dev server,
screenshots, and visual checks. Use the method that gives direct proof. List it
in the report.

Rules that name the correct command, fixture, or check still apply. If a
preferred method cannot prove the change, use a gated one. This covers only the
tests this task needs. It does not cover the steps under "Asking the user" or
bypass a harness or system approval prompt.

## Steps

1. **Finish the change.** Complete the goal from the user's request with the
   smallest change that works. Fix the case that happened, not every case
   that could. If you are on the default branch, create a branch first.
2. **Prove it.** Get proof for every change you made. See "Proof".
3. **Get feedback.** Use the `sol-loop` skill, with the proof packet.
4. **File the PR** with the `file-pr` skill. Rebase onto the latest default
   branch first. Add one short line to the description that says how you proved
   the change.
5. **Babysit the PR** with the `babysit-pr` skill. Fix real findings and CI
   failures. Get proof for each fix before you push it.
6. **Merge** when the merge gate passes.
7. **Report** in your final message: the PR link, the merge commit, your proof,
   and each decision you made for the user.

Stay active from step 1 to step 7. Ending a turn without a watcher stops the
work. Wait with the watcher from `babysit-pr` (`watch_pull_request` in T3 Code).
In T3 Code, once every owned PR merges with no open PR, blocker, question, or
user pin left (check `t3_thread_list` for `pinned`), settle this thread last
(`t3_thread_organize`, `action: "settle"`, no `threadId`). Delegated children
never settle. If you stop before merge, call `unwatch_pull_request` and do not
settle.

## Proof

Proof is evidence you observed yourself in this session, gathered per
[prove](../prove/SKILL.md): reproduce the failure and watch it pass, run the
repo's CI checks, add a focused test if none covers it. For UI and runtime
behavior, run the app and look: green mocked tests prove nothing.

Record it in a `proof-pack.py` packet. `proof-pack.py verify` must exit 0 on the
current head before `sol-loop` or `file-pr`. Put `verify --markdown` in the PR
Evidence.

If a worker or tool punts or refuses a user-authorized test or proof step, do
not leave it unproven and do not retry the same prompt. Hand it to `prove`'s
configured fallback worker. An unapproved gate, a CAPTCHA, anti-bot or 2FA
check, or an access or approval denial is not routed around: `prove` says how.

If nothing proves it, you lack full confidence. Do not ask the user: leave that
PR open and unmerged, say why in the report, and move on.

## Merge gate

Full confidence means all of these are true on the latest commit:

- Your proof covers every change in the diff.
- Required checks are green.
- Review bots have finished, and each finding is fixed or dismissed with a
  written reason.
- No human review still requests changes.
- The branch is up to date with the default branch, and GitHub reports it as
  mergeable.

Merge with the method the repo uses. Check the allowed methods and recent merged
PRs. If the repo uses a merge queue or auto-merge, stay until GitHub reports the
PR as merged. Merge through branch protection as configured. Never use `--admin`
or other bypasses. You can ignore automated reviews that request "needs human
review" if you have high confidence in your changes.

## Asking the user

A question in a normal message goes unseen, and the thread looks done. To ask
the user something, use the harness's question tool so the thread shows that
it is waiting: `AskUserQuestion` in Claude Code, `request_user_input` in Codex,
or the question tool your harness has. Put all the context in the question:
the PR link, what blocks you, and the options with your recommendation first.

Every question breaks a full send. Ask only for these 4 cases:

1. Deleting data that cannot be regenerated. (Build output, caches and
   targets can be regenerated: delete them yourself.)
2. Money, accounts, signing, or publishing or talking to a third party.
3. Touching production or a host outside the repo's sanctioned path.
4. A secret or login only the user has (use the secret tool, not a question).

Everything else has a default. Do it, and list it in the report:

- Merge gate cannot pass and you cannot fix it: leave the PR open, say why,
  continue with other work.
- Review rounds run out below the bar: split the PR or shrink it to what
  passes, and review again.
- PR is over a size or line limit: split it.
- Work depends on another PR: stack it and keep going.
- Goal is ambiguous: pick the reading closest to the request and say so.
- Another PR or thread makes this one obsolete: stop work on this one, leave
  it open, note it in the report, and continue with other work.
- Finding outside this change: make it the next PR, not a question.
- One path is broken and another works: use the one that works.

Never call the question tool outside those 4 cases or send the same question
twice. Ask early, all at once in one question, and keep working while you wait.

If no question tool is available, or the tool returns no answer, take the safe
path: leave the PR open and unmerged, and start your final message with the
question.
