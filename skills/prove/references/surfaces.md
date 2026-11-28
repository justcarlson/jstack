# Verification surfaces

Recipes for L2 to L4 evidence. Use the rig's lane for a surface first, then the stock tool named here. Attach each result with `proof-pack.py attach --surface NAME`. Surface names match rig lane names: `web`, `auth`, `native_gui`, `vnc`, `video`, `audio`, `vm`, `ssh`.

Every recipe has the same shape: drive the real thing, capture what a user would see or hear, open the capture, then attach it. Do not keep a screenshot you did not look at.

## Web and UI (`web`)

1. Open the page in a real browser tool (`agent-browser`, Playwright or the harness browser).
2. Do the user's path: click, type, submit. Do not stop at page load.
3. Check state, not only pixels: the visible text, the URL, a console with no errors.
4. Capture a screenshot of the result. For motion, record a short clip.
5. Check a narrow phone width and a desktop width for layout changes.

Attach: `--surface web --kind screenshot`.

## Auth, secrets and passkeys (`auth`)

Auth captures can show codes, tokens and account names. They are gated.

1. Take the credential from the rig's secret manager at run time. Never type it into a command line, a log or a brief.
2. Prefer a test account. Use a real account only when the user said so.
3. Passkeys and one-time codes the tool can generate, such as TOTP through an authenticator CLI, are in scope. Codes that need a person are not: see the human-only rule below.
4. Prove the outcome, such as the signed-in page, with the sensitive area cropped or blurred.
5. Redact first, then attach with `--redacted`. A public or unknown repo refuses anything else.

## Native GUI: Wayland, X11, macOS (`native_gui`)

1. Drive the app through its accessibility tree first (`cua-driver` or the platform equivalent). Use pixel clicks only for surfaces the tree lacks.
2. Capture the one window, not the whole desktop: `grim -g` with a window geometry on Wayland, `screencapture -l` on macOS, a window grab on X11.
3. Verify after the action with a fresh read of state, not the cached one.
4. Crop out other windows, notifications and the clock before attaching.

Attach: `--surface native_gui --redacted`.

## VNC and remote desktop (`vnc`)

1. Connect with the rig's viewer. Use a view-only session when you only need to look.
2. Capture the viewer window or the framebuffer, not the host screen.
3. Name the remote machine by role (`build-vm`), never by hostname or address, in anything you attach or write.
4. Redact, then attach with `--redacted`.

## Video contact sheets (`video`)

Do not attach a long clip nobody will watch. Prove it with frames.

1. Record with the rig's recorder, such as `wf-recorder` or `ffmpeg`.
2. Check the clip is real: `ffprobe` for duration and streams, non-zero size.
3. Build a contact sheet: `ffmpeg -i clip.mp4 -vf "fps=1,scale=320:-1,tile=4x3" sheet.png`.
4. Open the sheet. Confirm the start, the action and the end are all there.
5. Attach the sheet at L3 and the clip at L3 or L4.

## Audio in and out, and ASR (`audio`)

1. For output: play to a loopback or capture the sink, then transcribe it. Compare the transcript to the expected text.
2. For input: feed a known recording and check what the app did with it.
3. Transcribe with the rig's ASR tool. Keep the transcript beside the audio.
4. State the match plainly: exact, near or off. A transcript that differs is a failed check, not a warning.

Attach the audio and the transcript, both `--surface audio`.

## SSH, remote hosts and VMs (`ssh`, `vm`)

1. Name the target by role. Never put a hostname, tailnet name or address in a packet.
2. Run the real command on the remote side. Keep argv and output with `proof-pack.py run -- ssh ROLE ...`.
3. For a VM, start from a clean snapshot or image, install the change, run it, and keep the log. Destroy or revert the VM afterward.
4. Check the exit code and the output. A connection that opens proves nothing about the change.
5. Do not add keys, edit `known_hosts` or change firewall rules to get in. If access is denied, record `block --class access-denied` and stop.

## Human-only: physical exhaustion rule

A step is `human-only` only when a person's body is required: touch a hardware key, scan a finger or face, plug in a device, be in the room.

Before you record `block --human-only --class physical`:

1. List every lane the rig has for the surface.
2. Try each one. Log what happened with `--tried LANE=EVIDENCE`.
3. If the rig has no lane for the surface, log at least two different methods.

`proof-pack.py block` refuses until the log covers every lane, and `verify` checks it again.

CAPTCHA, anti-bot checks, human 2FA prompts, access denials and approval denials are not physical. Do not try to get past them. Record `block --class captcha|anti-bot|2fa|access-denied|approval`, stop and ask the user. They are never handed to a fallback model.
