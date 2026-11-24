# jstack

Agent skills for shipping real pull requests in Claude Code, Codex, Antigravity, OpenCode and T3 Code.

jstack is an independent companion and patched distribution of Theo Browne's [t3dotgg/tstack](https://github.com/t3dotgg/tstack). It carries tstack's core workflow with community fixes applied, plus a PR body standard and companion skills.

Not affiliated with Upstash JStack or OpenJDK `jstack`.

## Quick install

With the [skills CLI](https://www.npmjs.com/package/skills), for every client it finds:

```sh
npx skills add justcarlson/jstack -g
```

For Antigravity, including Antigravity managed by T3 Code, use `./install.sh --client antigravity` below. The skills CLI's `-a antigravity` writes to `~/.gemini/antigravity/skills`, but Antigravity reads global skills from `~/.gemini/config/skills`.

From a clone, with links back to the checkout so `git pull` updates every client:

```sh
git clone https://github.com/justcarlson/jstack
cd jstack
./install.sh                         # every client it detects
./install.sh --client claude --only full-send
./install.sh --check                 # report state, change nothing
./install.sh --uninstall             # remove only what jstack installed
```

| Client | Folder | Detected by |
| --- | --- | --- |
| `claude` | `~/.claude/skills` | `~/.claude` |
| `codex` | `$CODEX_HOME/skills` (default `~/.codex/skills`) | `$CODEX_HOME` or `~/.codex` |
| `antigravity` | `~/.gemini/config/skills` | `~/.gemini` or T3's `~/.t3/userdata/providers/antigravity` |
| `opencode` | `~/.config/opencode/skills` | `~/.config/opencode` |

`--only` adds the sibling skills a skill calls, so `--only full-send` also installs `sol-loop`, `file-pr`, `babysit-pr`, `leaving-pr-comments` and `pr`. Pass `--no-deps` to skip them, or `--mode copy` to copy instead of link (pair `--check` with `--mode copy` when checking copies). The installer needs only Python 3 and puts nothing on your `$PATH`.

As a plugin:

```text
# Claude Code 2.1.275 or later
/plugin install jstack --marketplace justcarlson/jstack

# Older Claude Code
/plugin marketplace add justcarlson/jstack
/plugin install jstack@jstack

# Codex
codex plugin marketplace add justcarlson/jstack
codex plugin add jstack@jstack
```

## Skills

### Core workflow

The nine tstack skills, patched. [UPSTREAM.md](UPSTREAM.md) pins the upstream commit and lists each patch in `patches/`.

| Skill | Use it to |
| --- | --- |
| `full-send` | Take work from its current state to a merged PR without check-ins |
| `full-stop` | Do the `full-send` workflow, then stop with the PR ready for you to merge |
| `council` | Get three models to review a change or plan, with scores |
| `sol-loop` | Loop a reviewer model over your diff until it approves |
| `babysit-pr` | Watch a PR through review and CI |
| `file-pr` | File a short, focused pull request |
| `leaving-pr-comments` | Mark agent-written GitHub comments as agent-written |
| `modernize` | Bring an old PR up to date, idea first and branch second |
| `takeover` | Finish another agent's PR, branch or thread, keeping its credit |

### PR standard

| Skill | Use it to |
| --- | --- |
| `pr` | Write PR bodies as Summary, Evidence and Merge Danger, with a visual; ships a CI lint |

### Companions

| Skill | Use it to |
| --- | --- |
| `epic` | Plan and ship multi-issue or multi-repo work, from options to live proof |
| `hindsight` | Find agent mistakes that repeat across sessions and fix each at its source |
| `hindsight-setup` | Choose which agent logs `hindsight` reads |
| `ci-retro` | Make CI faster from its own run history |
| `bug` | Take an upstream bug from first error to a merged fix |
| `omarchy-dev` | Test Omarchy changes in throwaway Omarchy VMs, the way upstream does |
| `t3-launch-worktrees` | Launch T3 Code threads in the right checkout |

## Make them yours

The skills name no models, hosts or private paths. Put those in your own instructions:

- Put your model roster in `AGENTS.md` or `CLAUDE.md`, for example the three `council` members and the `sol-loop` reviewer. The skills use the models you name there.
- Run `hindsight-setup` once. It writes `~/.config/hindsight/sources.json`, which tells `hindsight` which harness logs and stores to read.

## Development

```sh
python3 scripts/validate_skills.py        # frontmatter, links, manifests, size budget
python3 scripts/check_privacy.py --all    # secret files and private markers in tree and history
uv run --with pytest --with pyyaml pytest -q tests/
```

`size-budget.json` caps each skill at 250 bytes of description and 6,144 bytes of body. Skills already over a cap keep their current size as a ceiling that can only go down. After you shrink one, run `python3 scripts/validate_skills.py --write-budget`.

CI runs these checks with gitleaks, shellcheck, actionlint, ruff and the skills CLI. One `ci-ok` job gates the merge. A weekly job checks links.

## Related public skill repos

- [justcarlson/agent-box](https://github.com/justcarlson/agent-box): disposable Linux desktops for browser and GUI agents
- [justcarlson/mcp-gateway-spec](https://github.com/justcarlson/mcp-gateway-spec): a specification and conformance checker for MCP gateways
- [justcarlson/taildoc](https://github.com/justcarlson/taildoc): private document publishing over Tailscale

## Credits and license

MIT. See [LICENSE](LICENSE). Upstream licenses, community patch authors and other credits are in [NOTICE.md](NOTICE.md). Upstream sync policy is in [UPSTREAM.md](UPSTREAM.md).
