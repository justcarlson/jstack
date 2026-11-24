---
name: ci-retro
description: Make a repository's CI faster from its own run history, then keep it fast. Use when CI is slow, queued, flaky or cold-cached, when auditing CI performance, or after a session that spent its time waiting on or retrying CI.
---

# CI retro

A **retro** for CI: read the CI record, find where PRs wait, and change the
environment so the next run waits less. [GUIDE.md](GUIDE.md) is the playbook
(nine changes, with Boardy's measured results). This file is the procedure.

The CI record is the session log here. Every candidate traces to runs you
measured: a job, a step, a run ID and seconds. Discard a candidate you cannot
trace. A candidate with no measured win stays a proposal.

## Steps

1. **Read the repo's own checks.** Workflows, the build tool's `lint`,
   `typecheck` and `test` scripts, hooks, and the repo's CI notes. A check that
   exists but is unwired, skipped or silently broken is the finding, not a
   reason to build a new one. A repo with no guardrail (no hook and no CI job
   that runs lint, typecheck and tests) is a finding of its own.
   Done when you can list every job, what triggers it and what it runs.

2. **Measure.** Run `scripts/ci-timings OWNER/REPO --runs 100 --steps` for PRs
   (`--event pull_request`) and for main (`--event push`). Split every job into
   queue, setup and run. Note the critical path: the slowest job plus its
   queue. Note cache misses, retries of the same commit and flaky failures.
   Done when each job has p50 and p90 for queue, setup and run.

3. **Find candidates.** Walk the guide's sections against the numbers. Each
   candidate names its category, its evidence, its fix and the seconds it
   should remove from the critical path.

   | Category | Evidence | Fix it with |
   | --- | --- | --- |
   | Queue | queue p90 above the job's run time | a runner change (Runners and gates below) |
   | Setup | install, checkout or toolchain above 10 s; cold PR caches | a cache seeded from main, blobless clone, persistent tool cache |
   | Run | one step dominates the job | faster tool, shared test workers, bigger cores, then shards |
   | Critical path | jobs in sequence, or one job carrying extra work | parallel jobs; move the extra work out |
   | Scope | full suite on a docs-only or one-package change | affected-only runs, a nightly full run, and a test that the skip cannot hide a real change |
   | Local guardrail | CI fails on lint or types an agent could catch locally | a pre-push hook on changed files, under 10 s |
   | Flake | the same commit fails, then passes | fix or quarantine it with an owner; lower parallelism if it races |
   | Dead weight | a job that never failed in 90 days and duplicates another | delete it |

   Classify each rule you add. A **mechanical** rule (a fixed pattern, a cache
   that must hit, a skip that must not hide a change) becomes a check that can
   fail. Only a judgement call goes into the repo's coding standards, which the
   reviewer reads. `AGENTS.md` and `CLAUDE.md` get navigation pointers only.

4. **Rank.** Order by seconds removed from the critical path times runs per
   month, most first. A quiet cold cache on every PR can outrank a loud flake
   once a week. Present the list with evidence for each candidate.

5. **Pick.** Apply the candidates the user picks. "Full send" picks every
   candidate in the list. A candidate that cannot show a measured win in step 6
   is reverted and reported, not kept.

6. **Apply and measure again.** One commit per candidate. For each, record
   before and after from the same `ci-timings` columns, on at least three runs.
   Try a new check on a PR before it can block merges. Done when every picked
   candidate is kept with a measured win or reverted with its numbers.

7. **Make it stick.** A required check is the gate (Runners and gates below). Run the full
   suite on main on a schedule when PRs run less than everything. Put the
   before and after table in the PR's Evidence section.

## Runners and gates

These rules hold for any repository. A team with a private runner pool can
record its labels, capacity and monthly budget in its own `AGENTS.md` or
`CLAUDE.md`; this skill needs none of them.

- **Never register a self-hosted runner on a public repository.** A fork PR can
  run untrusted code on it. Run public repositories on hosted runners
  (`ubuntu-24.04`).
- **Match tiny, fast jobs to hosted runners** when their queue on a self-hosted
  runner exceeds their run time (`pr-body`, `actionlint`). Hosted minutes are
  billed per job, rounded up to a minute, so state each moved job's monthly
  minutes in the PR.
- **Gate merges on one always-running aggregator job**, for example `ci-ok`,
  that `needs` every CI job and fails unless each one succeeded or was skipped
  by a tested scope rule. Put path filters inside the workflow, never in `on:`
  `paths-ignore`, so the gate always reports. Require the gate in a ruleset
  only after it is green on main and on a PR.

## Files

- [GUIDE.md](GUIDE.md): the playbook behind step 3. Read it before you pick
  candidates, and when you explain a candidate to the user.
- `scripts/ci-timings`: run it in steps 2 and 6. It needs `python3` and an
  authenticated `gh`. Run `scripts/ci-timings --help` first when unsure.
