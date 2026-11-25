# Investigation modes

Pick one mode per question. Each mode works on local logs, `gh`, T3 MCP or an
analytics overlay. Use the overlay for counts when `sources.json` declares one.
Otherwise count with local files (see `sources.md`). Put saved SQL in your own
queries file (`queries_ref`), not in a skill.

| Mode | Question | Local source | Overlay or other source |
|---|---|---|---|
| 1. Repeated asks | Which request does the user repeat across sessions? | User messages in session JSONL, first request per session | Prompt text table in the analytics store |
| 2. Friction | Where do tools fail or get denied? | Tool-result and error records in session JSONL | Tool outcome or event tables |
| 3. Cutover | Did a change help? | Session counts and event rates per day, split at the cutover | Request and PR tables; `gh pr list` for merge dates |
| 4. Review loop | Do reviewers find real issues, and does the author act? | `gh pr view --json reviews,comments` | Review-finding tables |
| 5. Thread sample | What happened inside a few specific threads? | Parent session files | T3 threads: `t3-lens.md` |

Every mode obeys the Workspace exclusion and the 30-day window in `SKILL.md`.
Drop Workspace-tainted sessions before you count. Report how many you dropped.

## How to run a mode

1. State the claim as a number, such as "denials per 1,000 shell calls fell
   after the allowlist change".
2. Find the cutover date from `git log` or `gh pr view --json mergedAt`.
   Compare equal windows before and after. Both windows must fit in the last
   30 days. If the cutover is older, report the gap and make no claim.
3. Run the mode's count for both windows. Report `N` and the denominator for
   each. Run `scripts/hindsight-discover` first and list every harness that
   was not covered.
4. Read two or three raw cases (mode 5) to learn why, only after the numbers
   show a pattern. Numbers find the pattern. Threads explain it.
5. Name the lowest tier that fixes it (see `SKILL.md`, step 4).

## Mode notes

- Mode 1: pick two to four plain words. Count each prompt once, at its first
  request in a session. Each request replays the whole conversation, so counting
  every request inflates the number. Exclude system reminders and tool results.
- Mode 2: sandbox flags and denial reasons are often absent from logs. If a
  count needs them, treat that as a Tier 0 logging gap.
- Mode 3: compare inside one harness. A new model changes request volume, so
  compare shares of the day and use sessions as a second denominator.
- Mode 4: a high accept rate can mean good findings or a lenient author. Read a
  few findings before you conclude.
- A harness with no readable rows is uncovered. Say so in the report. Do not
  read it as zero.
