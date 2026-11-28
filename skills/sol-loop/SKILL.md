---
name: sol-loop
description: Use when the user says "sol loop".
---

# sol-loop

Make code changes more correct before (or after) filing a PR: have OpenAI's GPT
Sol review in a loop. Make the smallest changes that satisfy Sol. Resist scope
creep and push back.

## Budget

- Default: 3 rounds. Round 1 is full. Later rounds check only changed code and
  open findings.
- Extend to 5 only for security, permissions, auth, data loss, or
  state/concurrency while a blocker or should stays open with evidence, or when
  the user asks.
- A narrow confirm is not a round. Sol checks one diff: a fix it prescribed
  that you applied as written, or evidence it asked for. At most one after
  each round, sent like a next round with only that diff or evidence. Anything
  but APPROVE from it is an open finding.
- Stop early if a round returns only nits. Declined nits and comment, doc, or
  format-only fixes need no new round.
- One reviewer only. Sol must not start subagents or reviewers.
- Keep a ledger: id, severity, outcome, usage if returned. Never guess.

## 1. Scope

Run `git status --short`. Do not stash, discard, or include unrelated
changes. Limit review to the change paths if they separate cleanly.
Otherwise stop and ask.

Find the base after `git fetch origin`:

- PR: `gh pr view <n> --json baseRefName,headRefOid`. Check out the branch
  only if clean. `HEAD` must be the PR head, or ahead only by this change.
  Base: `git merge-base HEAD origin/<baseRefName>`.
- Local: `git merge-base HEAD origin/<default-branch>`. No remote: a base
  the user names, or `HEAD` for uncommitted changes only.

The change is base to working tree in those paths, with untracked files.
Use one diff command all rounds. State intent and out-of-scope in 1-2
sentences. Run covering checks; do not send code this change breaks. Note
missing or pre-failing checks.

## 2. Start Sol

In T3, call `orchestrator_capabilities`. Pick the latest Sol unless the user
named a version. Never hardcode an ID. Record provider, model, and effort only
if exposed. Use `delegate_task` every round (`role: "review"`, `mode:
"async"`). Save `taskId`. New `clientRequestId` per round. `childThreadId` is
storage, not the next target. Never use `t3_thread_send`, `create_threads`, or
`t3_thread_launch` for review.

If T3 tools are not listed, try one direct capability call. Outside T3, use
a native Sol subagent and keep its ID (in Claude Code, a custom subagent set
up to run Sol). If no route runs Sol, report the blocker. Never substitute.

Do not edit scoped files while review runs. Wait for the notice; do not poll.
Timeout, error, no reply, or no `VERDICT:` line is not approval. On failure, cancel, verify stop, restart with the ledger. On a missing verdict, if Sol named a check it awaited
and this round's narrow confirm is unused, run it and send the result as that
confirm. Otherwise start the next budgeted round or stop without approval.

Round 1 brief (T3 children get no history):

```
Review only. Do not edit, commit, push, comment on PRs, or start subagents.
Repo: <abs path> Base: <sha> Scratch: <dir outside repo> Intent: <intent> Out of scope: <scope> Checks: <results>
Proof: <packet path>
See: git diff <base> [-- <paths>]; git status --short (read untracked).
Read surrounding code. Find bugs, broken callers, mismatch with intent.
Skip style unless it hides a bug. Hold to the smallest change. Flag code,
tests, or guards the intent does not need. Other paths, rare cases, small
perf, extra compat: nits.
Missing, stale, or mocked proof of testable behavior: blocker.
Save any repro script in Scratch (the only writable dir) and give its path.
blocker = intended case wrong. should = real bug callers will hit, in intent. nit = rest.
Reply:
VERDICT: APPROVE or CHANGES
S1 [blocker|should|nit] <file>:<line> <claim>. Fix: <suggestion>. Repro: <path or none> (stable ids)
```

## 3. Answer findings

Check each finding and severity yourself. Another path, rare case, or small
cost is a nit, whatever its label.

- Agree: smallest fix. Prefer delete or narrow over new lock, cache, helper,
  or option. Fix the case that happened. Run Sol's repro script before and
  after. Add one focused test that fails without the fix, if intent needs it.
- Disagree: say why, with evidence (file:line, test, output).
- Out of scope or nit: decline in one line; list as follow-up.

Update the ledger. Re-run checks and `git diff --shortstat <base>`. If review
grew the diff, cut first. Never agree just to end the loop.

## 4. Next round

Start one only if budget remains and a blocker or should is open, behavior code
changed, or approval does not cover the current behavior diff. Use a fresh
`delegate_task` in T3, or follow up the saved native ID. Send the round 1 brief,
the ledger (`fixed:` / `disagree:` / `declined:` + evidence and repro paths),
the same base diff, and the change since last round. Sol checks open ids and
changed code only, marking each old id `resolved` or `still open: <reason>`.

## 5. Stop and ship

Agreed: APPROVE on the current behavior diff, no blocker or should open,
no concern of your own. Stuck: an item stays disputed after two replies,
or budget ends (not approval). Show both sides in 2-3 lines; the user decides.

Diverging: a later round returns new findings of a class you already
fixed, usually because the code imitates another tool. Stop patching.
Offer the user a design that supports only what it matches exactly and
refuses the rest. If taken, later briefs say a refusal is correct and only a
wrong definitive result is a blocker.

Do not push during the loop. Push after agreement only if the user asked
to push, ship, or update the PR. If you push to a PR, add above the model
blurb:

`Reviewed with sol-loop: <N> rounds with <model>. Sol verdict: approved at <short sha>`.

`<short sha>` is the pushed commit Sol approved. After `rounds` add `plus a
narrow confirmation` (or `plus <M> narrow confirmations`) if any ran, and `on
<effort>` only if verified.

Report: rounds and narrow confirms, model, what Sol changed, diff size
before/after, fixed and declined findings with reasons, usage (or "not
exposed"), pushed or not.
