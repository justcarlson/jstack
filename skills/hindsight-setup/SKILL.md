---
name: hindsight-setup
description: Set up or audit the log sources that hindsight reads. Use for "hindsight setup", "/hindsight-setup", or when adding a new harness, log folder or analytics store.
---

# Hindsight setup

Save which agent logs `hindsight` reads, in `~/.config/hindsight/sources.json`.
Ask short questions. Write nothing until the user confirms.

## Steps

1. **Inventory.** Run `hindsight-discover --no-gh --human` from the sibling
   `hindsight` skill (`scripts/hindsight-discover`). Also note whether `gh` is
   signed in, whether T3 Code MCP tools are visible in this session, and any
   analytics MCP server (ClickHouse, DuckDB, OpenTelemetry or similar).
   - If `hindsight` is not installed, use this check: list these folders under
     `~` and count files by name only, without opening them:
     `.claude/projects`, `.codex/sessions`, `.codex/archived_sessions`,
     `.gemini`, `.pi/agent/sessions`, `.local/share/opencode/opencode.db`,
     `.t3/userdata/providers/antigravity`. Run `gh auth status`.
2. **Show coverage.** Give a short table: harness, session count, date span.
   List missing harnesses as gaps. A gap is not zero incidents.
3. **Ask once, together:**
   - Which found sources to include or exclude?
   - Any other log folders to add (Cursor, Gemini CLI, Aider, custom)? Get a
     name and a glob for each.
   - An analytics MCP server name, and a saved-queries file for it?
   - Privacy: `paraphrase` everywhere (default), or `local-quotes` for short
     quotes in private reports?
4. **Write the config.** Run `hindsight-discover --write-config` with the
   answers: `--extra-glob NAME=GLOB`, `--exclude GLOB`, `--analytics-mcp NAME`,
   `--analytics-queries PATH`, `--privacy MODE`. It keeps unknown keys and
   writes atomically. Without the script, write the same JSON with a temp file
   and rename (keys: `version`, `harnesses`, `custom_globs`, `exclude_globs`,
   `analytics_mcp`, `queries_ref`, `t3_mcp`, `privacy`). To disable a harness,
   set `harnesses.<name>.enabled` to `false`.
   Offer, do not force, this pointer for `AGENTS.md` or `CLAUDE.md`:

   ```md
   ## Hindsight
   Log sources: `~/.config/hindsight/sources.json`. Run `hindsight` for retros.
   Re-run `hindsight-setup` after adding a harness or telemetry store.
   ```

5. **Verify.** Run `hindsight-discover --check --no-gh --human`. Every enabled
   source must be readable. If it fails, show the error lines, fix the
   config with the user and run it again. For a declared analytics MCP, call
   one harmless tool (list tables) to prove it responds.
6. **Close.** Tell the user they can run `hindsight` any time. Tell them to
   re-run `hindsight-setup` when they add a harness or telemetry store. Report
   the exact coverage from the check.

## Rules

- Setup reads file names and counts only. Do not open transcripts.
- Never store secrets in `sources.json`. Keep tokens in your secret manager.
- Do not edit `AGENTS.md` or `CLAUDE.md` unless the user says yes.
- Do not overwrite a config that is invalid JSON. Show the error and ask.
