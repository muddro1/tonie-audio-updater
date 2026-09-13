# Mac GUI for Tonie Audio Updater — Design

**Date**: 2026-09-13
**Status**: Approved, ready for implementation planning

## Purpose

Give the uploader a double-clickable macOS application so that people who will not
open a terminal can put audio on a Creative Tonie.

The command line tool stays exactly as it is. The GUI is a second front end over the
same engine, not a replacement and not a fork of the logic.

## Audience and distribution

For the author and non-technical people in the same household.

The deliverable is an unsigned `.app` bundle. Recipients right-click → Open once to get
past Gatekeeper, after which macOS remembers the choice. There is no code signing, no
notarization, and no Apple Developer account. Public distribution is explicitly out of
scope; it would require signing and notarization and is a separate piece of work.

## Why this is cheap to build

`tony.py` keeps terminal I/O in three functions. Every other function — file discovery,
video conversion, silence trimming, the 90 minute duration cap, `needs_update`,
`upload_with_retries` — writes only to `logging` and returns values.

| Function | print | input |
|---|---|---|
| `display_tonies_menu` | 30 | 1 |
| `confirm_selection` | 21 | 1 |
| `main` | 26 | 0 |
| everything else | 0 | 0 |

The GUI replaces those three and reuses the rest unchanged.

## Toolkit

**PySide6** (Qt for Python), bundled with **PyInstaller**.

Chosen over the alternatives considered:

- **Tkinter** — stdlib and a smaller bundle, but the Homebrew Python 3.14 on the
  development machine has no `_tkinter`, and Apple's `/usr/bin/python3` is Python 3.9
  with Tk 8.5, which looks visibly dated. The audience is people who will judge the app
  by how it looks.
- **SwiftUI front end** — the most native result, but a second language and an Xcode
  project, the bundle must still carry a Python runtime and `tonie-api` so the size
  saving disappears, and the UI could not be verified during development.

PySide6 6.11.2 publishes a `cp310-abi3` wheel, so it runs on the installed Python 3.14
without a version pin. It is LGPL licensed; PyInstaller ships the Qt libraries as
separate dynamically loaded files inside the bundle. For distribution within one
household this raises no practical obligation. Public distribution is out of scope, and
would want the licence terms reviewed alongside the signing and notarization work.

## Architecture

`tony.py` is not modified.

```
tony.py                  unchanged - CLI entry point and the whole engine
gui/
  __init__.py
  app.py                 main window, wiring, dialogs
  signin.py              first-run credential sheet
  worker.py              QThread wrapper and the logging-to-signal bridge
  keychain.py            security(1) wrapper
  state.py               GUI control state -> argv list
tests/
  test_gui_state.py      state -> argv
  test_keychain.py       keychain round trip against a throwaway service
  test_gui_app.py        window behaviour, headless
build/
  tonie_gui.spec         PyInstaller spec
```

### state.py is the anti-drift mechanism

The GUI never constructs a config object of its own. It converts its controls to a
normal argv list and calls `tony.parse_args(argv)`, which populates the same module
level `args` the CLI uses.

```python
build_argv(state) -> ["-i", "/path", "--convert-video", "--max-duration", "90", ...]
tony.parse_args(build_argv(state))
```

Consequences, all of them wanted:

- The GUI inherits the CLI's defaults, types and validation for free
- A flag added to `build_parser()` is the single source of truth for both front ends
- A control that produces an invalid value fails in `argparse`, where it already fails
  for the CLI, rather than somewhere new

`tony.args` is process-global, so exactly one operation may run at a time. The UI
enforces this by disabling controls while a run is in progress.

### Threading

Conversion and upload are slow. Both run in a `QThread`.

Progress reaches the UI through a `logging.Handler` installed by `worker.py` that emits
a Qt signal per record. The engine already logs every step worth showing — `Uploading
(2/5): Title`, `Truncated copy written to …`, retry warnings, the chapter titles about
to be cleared — so the GUI gets a live feed and the engine stays unaware a GUI exists.

Qt signals marshal to the main thread, so the log pane and progress bar update safely.

### Cancellation

The worker checks a cancel flag **between files**.

Cancelling during scanning or conversion is safe and leaves nothing behind beyond temp
files, which are cleaned up.

Cancelling during upload is not safe, because `update_tonie` clears the Tonie's chapters
before the first file goes up. The Cancel button therefore warns during upload that the
Tonie will be left incomplete, names the chapter titles that were cleared, and requires
confirmation.

## Screens and flow

### Main window

```
┌─ Tonie Audio Updater ──────────────────────────┐
│ Folder:  [ ~/Music/Kids            ] [Choose…] │
│          8 files · 47 min                       │
│                                                 │
│ Tonie:   [ Elephant (Home)        ▾]           │
│          ⚠ needs update · 5 chapters            │
│                                                 │
│ ▸ Advanced                                      │
│                                                 │
│ ────────────────────────────────────────────── │
│ [████████████░░░░░░░░] Uploading 3 of 8         │
│ ┌─ log ───────────────────────────────────────┐ │
│ │ Clearing all chapters from 'Elephant'       │ │
│ │ Uploading (3/8): Bedtime Story              │ │
│ └─────────────────────────────────────────────┘ │
│                            [Cancel]  [ Upload ] │
└─────────────────────────────────────────────────┘
```

The `Advanced` disclosure is collapsed by default and holds every remaining CLI option,
in four labelled groups:

- **Video**: convert video, audio bitrate, keep converted files
- **Silence**: trim silence, threshold, minimum silence duration
- **Limits and retries**: maximum duration, no duration limit, upload retries, retry
  delay
- **Run**: dry run, force update

### Flow

1. **Launch** — read the username from `QSettings` and the password from Keychain. If
   either is missing, show the sign-in sheet.
2. **Connect** — the worker constructs `TonieAPI` and calls
   `tony.get_all_creative_tonies(api)`, filling the Tonie dropdown with name and household.
3. **Choose folder** — a *cheap* scan only: `tony.find_files()` plus
   `tony.get_audio_duration()` per file, to show the file count, total runtime, and any
   over-limit warning. No conversion, no truncation, no temp files.
4. **Upload** — a confirmation dialog states what is about to happen, mirroring what
   `confirm_selection` prints: which Tonie, how many files, total runtime, how many
   chapters will be cleared, and any warning. On confirmation the worker runs
   `tony.get_audio_files()` (conversion, trimming, truncation), then `tony.needs_update`,
   then `tony.update_tonie`.
5. **Finish** — a summary, and `tony.cleanup_converted_files()` in a `finally` so temp
   files go even on failure or cancellation.

### Why the preview is cheap

`get_audio_files()` converts video, trims silence and truncates over-long files. Running
it on folder selection would freeze the window for a minute on a folder holding a large
MKV, for a preview. The cheap scan reuses `find_files()` and `get_audio_duration()`,
both already public in `tony.py`, and costs one short ffmpeg probe per file.

The preview therefore reports pre-conversion durations. Where that matters — a video
that will be trimmed, or a file that will be truncated — the confirmation dialog at step
4 shows the real post-processing numbers before anything is uploaded.

## Credentials

`keychain.py` shells out to `security`, which was verified to write, read back and
delete a generic password during design.

- Service: `tonie-audio-updater`
- Account: the Tonie account username
- The username, not being secret, lives in `QSettings`; the password lives only in the
  login Keychain

First launch shows a sign-in sheet with "Remember in Keychain" ticked by default.
macOS prompts once for access to the stored item; choosing "Always Allow" makes later
launches silent. Unticking the box keeps the password in memory for that run only.

Signing out clears both the `QSettings` username and the Keychain entry.

The GUI passes the credentials straight to `TonieAPI` and never calls
`tony.resolve_credentials()`, which exists to prompt on a terminal.

## FFmpeg

FFmpeg is required for video conversion, silence trimming and the duration check.

**It is not bundled.** On launch the app checks for it with `tony.check_ffmpeg()`. If it
is missing, a banner appears at the top of the window explaining what is unavailable,
with a button that copies `brew install ffmpeg` to the clipboard. The app remains usable
for plain audio uploads, degrading exactly as the CLI does today.

Bundling a static FFmpeg would remove that step, but redistributing FFmpeg carries
licensing obligations that vary with how the binary was built. That is a deliberate
decision to revisit later if the install step proves to be a real obstacle, not an
oversight.

## Error handling

No failure is silent. Each one produces a dialog and leaves the log pane showing the
detail.

| Failure | Behaviour |
|---|---|
| Bad credentials | Sign-in sheet reopens with the message; Keychain entry is not overwritten |
| No Creative Tonies on the account | Dialog; Upload stays disabled |
| FFmpeg missing | Banner with a copy-able install command; plain audio still uploads |
| A file cannot be truncated to the limit | `RuntimeError` from the engine, shown as a dialog. Nothing is uploaded and no Tonie is touched, matching the CLI |
| Several files exceed the limit | Warning in the confirmation dialog, which requires an explicit confirmation to continue |
| Upload exhausts its retries | Dialog reporting how many files were uploaded and which chapter titles were cleared, taken from the same information the CLI logs |
| Anything unanticipated | Dialog with the exception, log pane scrolled to it |

## Testing

The 79 existing engine tests are untouched and keep passing.

New tests:

- **`test_gui_state.py`** — `build_argv()` for every control, including that defaults
  produce the same `args` as the bare CLI, and that a flag added to `build_parser()`
  without a control is caught
- **`test_keychain.py`** — store, read, overwrite and delete against a throwaway service
  name, and the behaviour when no entry exists
- **`test_gui_app.py`** — the window driven headless under `QT_QPA_PLATFORM=offscreen`
  with `QTest`: choosing a folder updates the summary, an over-limit folder shows the
  warning, Upload against a stubbed `TonieAPI` clears and uploads in the right order,
  a failing upload surfaces the dialog, and controls are disabled while a run is in
  progress

Headless Qt tests run in CI and locally without a display.

**Manual verification**, which cannot be automated: one run of the built `.app` to
confirm it opens past Gatekeeper, the Keychain prompt appears and "Always Allow" works,
and the window looks right on a real display.

## Out of scope

- Code signing, notarization and public distribution
- A Windows or Linux GUI
- Uploading to more than one Tonie in a single run; the CLI menu allows it, the GUI
  targets one at a time. A second run covers the case
- Editing or reordering chapters already on a Tonie; the API surface used here replaces
  all chapters
- Bundling FFmpeg, as described above

## Success criteria

1. A household member can open the `.app`, pick a folder, pick a Tonie, press Upload and
   have the audio arrive, without a terminal
2. Every CLI option is reachable from the Advanced section
3. The GUI cannot drift from the CLI: both go through `build_parser()`
4. `tony.py` is unchanged, and its tests still pass
5. A failed upload tells the user what was lost, as the CLI does
