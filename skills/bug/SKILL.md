---
name: bug
description: Take an upstream bug, in a tool we use but do not own such as T3 Code, from first error to merged fix. Use when an error comes from upstream code, or when asked to check for an upstream issue, file one, or propose its fix.
---

# Bug

Prove the bug is upstream, find what changed, reproduce it yourself, file
one short issue in the project's own format, and then help the fix land.
Worked example: T3 Code issue
[#37380](https://github.com/pingdotgg/t3code/issues/37380) and the
maintainer fix [#37392](https://github.com/pingdotgg/t3code/pull/37392).

## Steps

1. **Place the bug.** Find the error text in the installed source (for example,
   in T3 Code, the pinned source is under `~/.t3/source/<sha>/`). Confirm that
   nothing in our repos causes it. If it is ours, stop and fix it here.
   Done when you can name the upstream file and the check that fails.

2. **Find what changed.** When the user says it is new, compare the installed
   version with the one before (for example, in T3 Code, `serverVersion` is in
   `~/.t3/userdata/server-runtime.json`). Diff the code path across the two
   builds, then find the upstream PR that changed it. Note the PRs that it
   reverses on purpose (in #37380, #36379 dropped unborn branches to fix
   #22017). A fix that undoes that intent is wrong.

3. **Search first.** Search open and closed issues and PRs for the error
   text, the UI words, the function name and the suspect PR number. If one
   matches, comment or react there; do not file a duplicate.
   Done when every search is listed with its result.

4. **Reproduce it yourself.** Use the real app in the preview browser. For a
   local T3 Code, open `origin` from `server-runtime.json`. Use harmless input,
   such as "Reply with the word ok." Capture the failure and the state that
   explains it (in #37380, the picker said "No refs found" while the label
   said "From main"). Test each workaround before you suggest it.
   Done when you have saved screenshots and a tested workaround.

5. **Clean the screenshots.** Crop out the sidebar, thread titles, hostnames
   and anything personal. Preview screenshots are 2x, so double the crop
   coordinates. Look at each image before you upload it.

6. **Draft in their format.** Read `.github/ISSUE_TEMPLATE/` and
   `CONTRIBUTING.md` with a sparse clone. Fill each template field with an
   option it allows. Keep it short and user-facing (Matt Pocock's `qa` style, if
   you have it): the user's view, numbered steps, expected and actual
   behavior, no file paths or line numbers, readable in 30 seconds. Put the suspect PR and related items on
   one line. When an open issue looks close, say in one line why yours is
   different, or triage closes it as a duplicate. Give the version that
   broke and the last one that worked. Apply `unslop` if you have it.
   Done when every required template field is filled.

7. **Review with the council.** Give each member the draft, the screenshots,
   the template rules and your facts to verify. Run rounds until each score
   is 8 or more and no member names a blocking change.

8. **File it.** Run `gh` with network/auth access (outside any offline sandbox). Host screenshots in a public
   gist (`gh gist create --public` cannot take binaries, so clone the gist,
   add the images and push). Check that each raw link loads. Then run
   `gh issue create --title "[Bug]: ..." --body-file body.md`. Only
   maintainers can add labels. Done when the issue URL opens and both
   images render in it.

9. **Propose the fix, if asked.** Clone upstream `main` at a pinned commit.
   Have the council trace the root cause and propose the simplest
   maintainable fix, and score your plan. Prefer one rule in a shared helper
   over a check skipped in one caller. Follow the server: if it ignores an
   input, the client must not require it. Done when each proposal names the
   root cause with a file and line, a diff sketch and the test that goes red.

10. **Follow the fix.** Watch the issue for a linked PR. Compare it with the
    council's fix. If they differ, post one short review comment with the
    simpler rule and the case it covers. Use `leaving-pr-comments`. Done
    when the fix merges or the user stops the follow-up.

## Writing the fix PR

The maintainer fix #37392 sets the bar for a PR we send upstream:

- **Reproduce on `main` first**, in a throwaway home, not the user's live
  app. For T3: `T3CODE_DEV_SEED=0 vp run dev --home-dir <tmp>`, outside any
  git checkout, then recreate the report's state (in #37380,
  `git init -b main` in `<tmp>/scratch`). Match the reporter's screenshots.
- **Red, then green.** Add or extend one unit test. Show it fails with the
  fix reverted and passes with it. Run the repo's changed-file check (T3:
  `vp run check:changed`).
- **Before and after** screenshots from the real app before merge.
- **Not in this change:** list the related gaps you left out on purpose.
- **Who did the work:** the author model, and the reviewers who saw the code
  without the author's reasoning.

## Traps

- A label can show a value that the check behind it never stored. Read both
  sides before you trust the UI.
- `gh` may be logged out inside an offline sandbox.
- Outside a sandbox, `$TMPDIR` can point somewhere else. Use absolute paths
  for files that `gh` must read.
- Starting a real thread to test a workaround creates a separate thread and
  worktree. Once its test turn finishes, archive that test thread by its
  `threadId` (`t3_thread_organize`, `action: "archive"`). Never archive your
  own thread.
