# Third-Party Notices and Attribution

`justcarlson/jstack` is licensed under the MIT License ([LICENSE](LICENSE)). It bundles and builds on MIT-licensed upstream skills and community pull requests, credited below.

## Upstream skill repositories

### t3dotgg/tstack

- Repository: <https://github.com/t3dotgg/tstack>
- License: MIT ([LICENSE-tstack](LICENSE-tstack))
- Copyright: Copyright (c) 2026 Theo Browne
- Skills included: `babysit-pr`, `council`, `file-pr`, `full-send`, `full-stop`, `leaving-pr-comments`, `modernize`, `sol-loop`, `takeover`

### Community patches on t3dotgg/tstack

The following pull request contributions to `t3dotgg/tstack` (MIT, inbound=outbound under GitHub Terms of Service Section D.6) are applied on top of `t3dotgg/tstack` and recorded in `patches/` and [UPSTREAM.md](UPSTREAM.md):

| Patch | Upstream PR | Commit | Author | Notes |
| --- | --- | --- | --- | --- |
| `01-council-shared-provider.patch` | [t3dotgg/tstack#18](https://github.com/t3dotgg/tstack/pull/18) | `bef2f542bb` | `xloeza` | Closed unmerged upstream (2026-11-23); keeps only the shared-provider relaxation |
| `02-council-neutral-briefs.patch` | [t3dotgg/tstack#25](https://github.com/t3dotgg/tstack/pull/25) | `a27f10f412` | `pauldupuyjr` | Neutral briefs, forbid nested subagents, fresh rounds |
| `03-council-stop-loops-and-readonly.patch` | [t3dotgg/tstack#22](https://github.com/t3dotgg/tstack/pull/22) | `e191a43765` | Bilal (`@Bilalkamal`) | 3-round stop cap and read-only guard |
| `04-sol-loop-narrow-confirms-repro-diverging.patch` | [t3dotgg/tstack#21](https://github.com/t3dotgg/tstack/pull/21) | `e89b2e260b` | Can H. Tartanoglu (`@caniko`) | Narrow confirms, missing-verdict handling, scratch repros, diverging stop, approved SHA |
| `05-full-send-ask-only-irreversible.patch` | [t3dotgg/tstack#23](https://github.com/t3dotgg/tstack/pull/23) | `e5685adad6` | `deorozindo` | 4-case ask rule; adapted locally to leave obsolete PRs open |
| `06-pr-wait-timeouts-and-required-checks.patch` | [t3dotgg/tstack#24](https://github.com/t3dotgg/tstack/pull/24) | `a314f0f95c`, `41973e920` | Luke Cunningham (`@icaruswings`) | 120s `gh` timeout and transient required-check re-raise (Linux/macOS commits) |
| `07-pr-wait-failed-baseline.patch` | [t3dotgg/tstack#14](https://github.com/t3dotgg/tstack/pull/14) | `89b467adb3` | `ryoppippi` | Avoid saving empty baseline state on first-poll failure |
| `08-pr-wait-ready-no-gating-bot.patch` | [t3dotgg/tstack#16](https://github.com/t3dotgg/tstack/pull/16) | `2af47e4d53` | Dhruv Arora (`@dhruv1220`) | Let `pr-wait --until ready` finish when no gating bot reviewed the PR |

### mattpocock/skills (`pr`) and HumanLayer (`show-me`)

- Repository: <https://github.com/mattpocock/skills>
- License: MIT ([LICENSE-mattpocock-skills](LICENSE-mattpocock-skills))
- Copyright: Copyright (c) 2026 Matt Pocock
- Transitive attribution: the **Summary** visuals menu in `skills/pr/SKILL.md` comes from [Dex Horthy](https://github.com/dexhorthy) / [HumanLayer](https://github.com/humanlayer/skills) (`show-me`, MIT), preserved in `skills/pr/CREDITS.md`.

### omacom/omarchy and omacom/omarchy-iso (`omarchy-dev`)

- Repositories: <https://github.com/omacom/omarchy>, <https://github.com/omacom/omarchy-iso>
- License: MIT ([LICENSE-omarchy](LICENSE-omarchy))
- Copyright: Copyright (c) David Heinemeier Hansson (`omacom/omarchy`); Copyright (c) 2026 Anton Hvornum (`omacom/omarchy-iso`)
- Scope: `skills/omarchy-dev/scripts/omarchy-vm` and `skills/omarchy-dev/templates/omarchy-vm.yml` adapt upstream's `test/ci-vm`, `.github/workflows/test.yml`, and `test/vm-image/vm-boot`.

### Methodological references

- `skills/ci-retro/GUIDE.md` summarizes published CI benchmarks from Owen Gretzinger's post *"How I made our CI 20x faster (steal this)"* (Boardy, 2026-10-30) and Linear's *"CI bottleneck reworked"* in original prose.
