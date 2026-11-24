---
name: omarchy-dev
description: Develop, test and verify Omarchy changes the way the Omarchy team (omacom) does, in throwaway Omarchy VMs from the nightly images, with upstream's own test harness and CI. Use for any change that reaches an Omarchy desktop (Omarchy itself, shell plugins, themes, Omarchy apps, desktop automation) and for the CI jobs that test them, including contributions to public repositories.
---

# Omarchy dev

Every Omarchy change is run, tested and verified in a throwaway Omarchy VM,
never on a live desktop. CI runs the same test on every pull request. This is
the Omarchy team's own method; copy it, do not improvise.

This skill and its files are stock: no host, account, path or personal
setting. Everything they produce can go into a public repository or an
upstream pull request.

## The upstream standard

The target repository's `AGENTS.md` and `agents/skills/` win over this skill.
Pin what you cite to a commit.

- `omacom/omarchy` (default branch `quattro`): `AGENTS.md`; the guides in
  `agents/skills/` (`shell-dev.md`, `visual-verification.md`,
  `acceptance-tests.md`, `migrations.md` and others); `docs/testing.md`.
- `omacom/omarchy` `test/ci-vm` and `.github/workflows/test.yml`: every pull
  request boots the VM image of the current stable release on a GitHub
  runner's `/dev/kvm`, in an Arch container with Arch's QEMU. It copies the
  checkout in, runs `./test/all` in the desktop session with `OMARCHY_PATH` at
  the checkout, and uploads the logs. No secrets, so fork pull requests run it
  too.
- `omacom/omarchy-iso` `test/vm-image/vm-boot`: boots the image straight into
  its kernel on a copy-on-write overlay, with a new SSH key and machine ID per
  boot. The image is never written.
- `omacom/omarchy-iso` `bin/omarchy-iso-test`: the installer acceptance suite.
  `--reuse-base --sync-omarchy ../omarchy` is its fast loop. It sends global
  keybindings through QMP, because in-guest `wtype` does not prove a
  compositor binding.
- Images: `https://nightly.omarchy.org/{stable,edge}/latest.json`. `stable`
  is the latest release and what upstream CI tests. `edge` is built each night
  from the development branch. Published files never change; only
  `latest.json` moves.

## Contribute to Omarchy

1. Fork `omacom/omarchy`. In a work folder, never `/usr/share/omarchy`, put
   the clone beside a clone of `omacom/omarchy-pkgs`. Branch from `quattro`.
2. Read `AGENTS.md` and the guide for the area you change.
3. Run upstream's CI script on the image upstream CI uses, from the work
   folder:

   ```sh
   omarchy-vm fetch stable
   omarchy/test/ci-vm "$(omarchy-vm path stable)" . out
   ```

   Read `out/run.log`. Before you blame your change for a failure, run the
   same script on the unchanged `quattro` commit.
4. Visual changes: follow `visual-verification.md` in a VM. Start the branch's
   shell with `OMARCHY_PATH=~/src/omarchy omarchy-launch-shell` inside an
   `omarchy-vm run --copy omarchy` command, capture with `grim`, and read the
   capture.
5. Installer and acceptance changes: `omarchy-iso`'s `bin/omarchy-iso-test`.
6. Commit and open the pull request as `AGENTS.md` says. Attach before and
   after captures from the VM for visual changes. Upstream CI gives the
   verdict.

`omarchy dev link` and `omarchy-update-dev` run only in a VM.

## Everything else that reaches an Omarchy desktop

Plugins, themes, Omarchy apps, dotfiles and desktop automation use the same
loop:

1. Edit the source: a checkout or a reviewed plugin artifact. Do not edit live
   files to try something.
2. Run the checks that need no desktop: linters, unit tests,
   `omarchy plugin validate <dir>`.
3. Run the change in a fresh VM with `omarchy-vm run`, on `stable` and `edge`.
   Read every screenshot it brings back. A file that exists proves nothing.
4. Fix and repeat. Each run is a new machine, so no state leaks between runs.
5. Before merge, CI passes on `stable` and `edge` (see CI below).
6. Install on a real machine only through the component's own install path,
   after the VM pass, and check the result once. A VM does not prove
   hardware: audio, displays, sleep and USB need a real machine.

## The VM tool

`scripts/omarchy-vm` wraps the image's own `vm-boot`. It keeps upstream's
image layout (`base.qcow2`, `vmlinuz`, `initrd`, `cmdline`), so
`test/ci-vm` and `vm-boot` read its cache folders directly.

```sh
omarchy-vm fetch [stable|edge]   # verifies every sha256; ~4.5 GB once per image
omarchy-vm path [stable|edge]    # the image folder, for test/ci-vm
omarchy-vm run [--channel edge] [--copy <path>]... [--pkg <name>]... --out <dir> -- <cmd>
omarchy-vm shell [stable|edge]   # interactive; prints the ssh line and QMP socket
```

`run` copies each path to `~/src/<basename>` (Git metadata included, build
output excluded), installs `--pkg` packages from the official repositories,
waits for Hyprland, keeps the screen awake, runs `<cmd>` as user `omarchy` in
the desktop session, copies `~/out` back to `--out`, and powers off. Its exit
status is the command's. The image's password is `omarchy`.

In `<cmd>`: `grim ~/out/<name>.png` captures the screen; `hyprctl` and
`omarchy-shell` reach the session; `OMARCHY_VM_CHANNEL` and
`OMARCHY_VM_VERSION` name the image. Before a capture, wait for the shell. It
answers one ping and then drops calls while plugins load, so wait for three
answers in a row.

The host needs `/dev/kvm`, about 10 GB of free memory, and
`qemu-system-x86 qemu-img qemu-hw-display-virtio-gpu qemu-hw-display-virtio-vga
openssh jq curl` from the official repositories. `aria2` makes the fetch
faster.

## Recipes

**Shell plugin install or update.** Rehearse the reviewed checkout before any
real install. Pin it to the reviewed commit; `omarchy plugin add` installs
that commit:

```sh
omarchy-vm run --copy "$checkout" --out "$out" -- bash -c '
  set -euo pipefail
  src=$HOME/src/$1 id=$2
  omarchy plugin validate "$src"
  omarchy plugin add "file://$src" --yes
  omarchy plugin enable "$id"
  sleep 3; omarchy-shell shell ping; grim ~/out/enabled.png' _ "$(basename "$checkout")" "$plugin_id"
```

Then use the plugin's own feature in the same command and capture it.

**Themes.** `omarchy theme install <url>`, then `omarchy theme current` and a
capture.

**Omarchy apps.** Build on the host, copy the build or package in, run it, and
capture the result. Drive compositor keybindings through QMP
(`omarchy-vm shell` prints the socket), not in-guest `wtype`.

## CI

`templates/omarchy-vm.yml` is upstream's `test.yml` for any repository. It
runs on `ubuntu-26.04` (GitHub-hosted, KVM) with `stable` and `edge` in a
matrix. It fits the run to the runner: the image goes into RAM when it fits,
as upstream does, else onto the runner's disk, and the VM gets the runner's
CPUs and its memory less 2 GB. Public repositories get 16 GB runners, private
ones 8 GB, and both work. It runs QEMU in an Arch container with the pacman
Landlock fallback and Omarchy's Arch mirror, holds no secrets, pins action
SHAs, and uploads `out/` on every run, pass or fail.

To adopt it, copy `scripts/omarchy-vm` to `test/omarchy-vm` and the template
to `.github/workflows/omarchy-vm.yml`, and write a `test/all` that runs in the
VM, as upstream does. A self-hosted runner needs `/dev/kvm` and about 10 GB of
free memory.

## Files

- `scripts/omarchy-vm`: run it for `fetch`, `path`, `run` and `shell` (the
  section above). It needs the host packages listed there. Read its header
  comment for options and environment variables.
- `templates/omarchy-vm.yml`: read it, then copy it to
  `.github/workflows/omarchy-vm.yml` when a repository adopts the CI job
  (the section above). Do not run it by hand.

## Rules

- Stock only. A VM gets source, builds and fixtures: no dotfiles,
  credentials, tokens, SSH keys or personal configuration. Commits, pull
  request text, test fixtures and CI name no personal host, path or account.
- Look at every capture before you attach it: it must show only the stock VM.
- Tests run only in a VM, never on a live desktop or in a nested Hyprland on
  a host. The host sends no input, activation or drawing for a test.
- A failed run is evidence: read `--out` before you run again. Report a flaky
  pass as flaky; do not rerun until green.
- Report the channel, image version, exit status and the captures you read.
