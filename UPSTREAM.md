# Upstream Tracking

`jstack` tracks upstream MIT skill repositories by exact commit SHA and records every local patch cleanly so merged upstream fixes can be dropped without losing history.

## Pinned upstream commits

| Upstream | Commit | Date | Skills tracked |
| --- | --- | --- | --- |
| [t3dotgg/tstack](https://github.com/t3dotgg/tstack) | `11e37a74d0a6868c121cd0910ab2b3bd9873b92a` | 2026-11-11 | `babysit-pr`, `council`, `file-pr`, `full-send`, `full-stop`, `leaving-pr-comments`, `modernize`, `sol-loop`, `takeover` |
| [mattpocock/skills](https://github.com/mattpocock/skills) | `a496f5513d4a4cf889bc48e189e579f4b0bdf6aa` | 2026-10-27 | `pr` (`skills/engineering/pr`) |

## Sync policy

1. Keep `patches/*.patch` in sync with every divergence from pinned `t3dotgg/tstack`.
2. When `t3dotgg/tstack` merges an upstream PR that a patch carries, drop the corresponding file from `patches/`, bump the pinned SHA above, and verify all skill tests and CI checks pass.
3. Preserve `Co-authored-by:` commit trailers and [NOTICE.md](NOTICE.md) rows for every redistributed community contribution.
4. Keep personal model rosters, fleet hostnames, and private URLs out of `skills/`; users put those in `AGENTS.md`, `CLAUDE.md`, or `~/.config/hindsight/sources.json`.
5. Local `jstack` patches with no upstream PR stay in `patches/` until upstream adopts equivalent behavior.
