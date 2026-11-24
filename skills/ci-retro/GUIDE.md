# Fast CI guide

Source: Owen Gretzinger, [How I made our CI 20x faster (steal this)](https://x.com/owengretzinger/status/2116291924219060319),
2026-10-30. Boardy cut PR CI from 40 minutes to 2. The numbers below are
Boardy's, from that article. Re-measure each one in your own repo.

Agents push, wait for CI, fix the red check and push again. When agents write
code ten times faster and CI does not get faster, CI is the wait. Treat CI as a
product: measure it, then remove the largest wait first.

| Change | Boardy before | Boardy after |
| --- | --- | --- |
| Runners other than GitHub's default | up to 11 min waiting for a machine | 8 s |
| Oxlint instead of ESLint | 2 min | 5 s |
| tsc, then TypeScript 7, then `bun check` | 70 s | under 5 s |
| Test files share a worker | 100 s per shard | 35 s |
| Cache seeded from main | half of PR runs missed | 1% missed |

## Measure first

Every job has three parts: **queue** (waiting for a runner), **setup**
(checkout, toolchain, cache, install) and **run** (the steps you care about).
Pull the last 50 to 150 runs and split every job into those parts
(`scripts/ci-timings`). Boardy's largest setup win came from this audit: half
the test jobs missed the dependency cache all year, and nobody saw it because
agents retried red runs instead of reading them.

A PR waits for its slowest job, plus that job's queue time. Rank the work by
seconds removed from that critical path, times the number of runs.

## 1. Queue: put each job where it starts fastest

Queue time is job time. A 5-second job that waits 10 minutes for a machine is a
10-minute job. Boardy left its two smallest jobs on slow runners, and they
became the slowest part of the pipeline. Measure the queue for every job,
including the tiny ones, and move any job whose queue exceeds its run time.

Runner changes took Boardy from 40 minutes to about 10. Faster runners are
usually one line per job (`runs-on:`).

## 2. Lint: use the fastest linter, with every rule on

Oxlint replaced ESLint and lint went from 2 minutes to 5 seconds. Agents are
not annoyed by strict rules, so turn on every rule you can. A strict linter
makes the wrong code fail fast, and the agent fixes it in the same loop.

## 3. Typecheck: re-benchmark when a faster checker ships

Boardy switched typecheckers three times in a month: tsc (70 s cold),
TypeScript 7 (13 s), then `bun check` (under 5 s) in CI, with tsrs (0.6 s)
locally. When a faster tool ships, benchmark it on the repo the same day and
switch if it is faster and reports the same errors.

## 4. Tests: buy cores before shards

Boardy split one 8-minute test target into six shards on 8-vCPU machines, each
with its own database. Bigger machines mattered more than more shards: each
shard spent most of its CPU loading modules, not running tests.

## 5. Tests: stop reloading the app for every file

Vitest gives each test file a fresh worker by default, so every file imported
the whole app again. With `isolate: false`, each shard went from 100 s to 35 s.
Linear found the same ([CI bottleneck reworked](https://linear.app/now/ci-bottleneck-reworked)).
Shared workers let state leak between files. Add a hook that resets state after
every file, and write down what a test must clean up.

## 6. Setup: the part nobody watches

Boardy's server test job went from 168 s to 74 s with almost no change to the
tests. The time was in setup.

- **Seed caches from main.** GitHub scopes a PR's cache to its own branch. A PR
  can restore caches from its base branch, so a push to main must save one.
  Without that, most PRs start cold.
- **Cache dependencies.** A restored `node_modules` took 13 s and replaced a
  33 s install.
- **Use a blobless clone** (`filter: blob:none`), not a shallow one. Shallow
  clones break tools that read git history. Checkout went from 36 s to 12 s.
- **Match parallelism to cores.** A 4-vCPU job ran 8 tasks at once. Half the
  concurrency was as fast and removed a flaky test.

Deleting tests did not help. An agent audited 20,000 test cases and found
almost nothing worth removing; the time was never in the tests.

## 7. Run everything in parallel

Lint, typecheck, build and tests run at the same time, so a PR takes as long as
the slowest one. Then look at what else the slowest job does. Boardy's first
test shard also ran migration checks and other apps' tests, so it always
finished last. A separate job for those cut 2 minutes.

## 8. Run only what a PR touches, and test the skip

Boardy uses `nx affected` so a PR tests only the projects it changed, and runs
the full suite every night on main. Skip logic can fail open: Boardy hid a
server change from Nx on purpose, and all six shards skipped and reported
green. Now that case fails the run. Every skip rule needs a test that proves a
real change is not skipped.

## 9. Run the checks before every push

A pre-push hook runs format, lint and typecheck on changed files in under 9 s.
An agent that hits a type error locally fixes it in seconds. Put the check in a
hook, not in `AGENTS.md`: agents skip written steps, and a hook cannot be
skipped by forgetting it.

## Cost

Boardy's CI bill went from $230 to $4,300 a month, and they count it as the
cheapest way to make agents faster. Price the wait too: agent time and
merge time spent on a red or queued run.

## Next bottleneck

With 2-minute CI, the slowest part of Boardy's loop became a person clicking
merge. Once CI is fast, required checks and automatic merge move the next wait.
