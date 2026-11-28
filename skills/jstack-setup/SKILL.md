---
name: jstack-setup
description: Describe your local rig once (tools, uploader, fallback model). Use for "jstack setup", "/jstack-setup", or after adding a browser, desktop, VM or model tool. Renders it into deployed skills.
---

# jstack setup

Save your local tools in `~/.config/jstack/rig.json`. The installer renders them into the deployed skills that have a rig slot, such as `prove`. The public repo stays stock.
Ask short questions. Write nothing until the user confirms.

## Steps

1. **Inventory.** Run `scripts/jstack-rig.py discover --human` from this skill. It is read-only: it looks up program names, config folders and loopback ports, and runs `gh auth status` for its exit code. Also note whether T3 Code or other MCP tools are visible in this session.
2. **Show the table.** Give lane, tools found and gaps. Lanes: `web`, `auth`, `native_gui`, `vnc`, `video`, `audio`, `vm`, `ssh`, `secrets`. A gap is not a failure; it means that surface falls back to stock behavior.
3. **Ask once, together:**
   - Which found tools to keep or drop per lane? Any tool to add?
   - A media uploader command, if you have one?
   - A fallback `provider/model` for tasks a worker refuses or avoids? Optional.
   - Any local endpoint to record (OpenCode, Ollama, llama-server)?
4. **Write the rig.** Run `scripts/jstack-rig.py write --from-discover` with the answers: `--lane NAME=tool,tool`, `--uploader CMD`, `--fallback PROVIDER/MODEL`, `--endpoint NAME=URL`. Add `--dry-run` first to show the result. The file is written atomically with mode 0600. It holds names only. The script rejects any value that looks like a token, password or credential URL, and it never echoes the value. Move such a value into your secret manager.
5. **Render.** From the jstack checkout, run `./install.sh --reconcile`. It re-renders deployed skills from the rig and repairs only entries jstack installed. If nothing is installed yet, run `./install.sh` first. Offer `./install.sh --install-hook` so `git pull` re-renders on its own; add it only if the user says yes.
6. **Verify.** Run `scripts/jstack-rig.py check` and `./install.sh --check`. Both must exit 0. A `drift` line means the rig or a skill changed since the last render: run `--reconcile` again.
7. **Chain.** Offer `hindsight-setup` next, if the user has not set up their log sources.
8. **Close.** Tell the user which lanes are live, which are stock, and to re-run `jstack-setup` after adding a tool.

## Rules

- Setup reads program names, folder names and loopback ports only. It does not open transcripts, key files or credential stores.
- Never put a secret in the rig. Keep tokens in your secret manager.
- Do not overwrite a rig that is invalid JSON. Show the error and ask.
- The overlay per skill is capped at 1,024 bytes. If a render is refused for size, shorten the lane lists.
- Do not edit `AGENTS.md` or `CLAUDE.md` unless the user says yes.
- Do not copy rig values into a repository, a PR or a public message. `rig.example.json` shows the shape with placeholders.
