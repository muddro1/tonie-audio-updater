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

The GUI replaces those three and reuses the rest, with one scoped change to the
engine described in the next section.

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

## One change to the engine: `-i` accepts files

Everything else in `tony.py` is reused as it stands, but the GUI needs to upload a
hand-picked set of files, and `-i` currently takes a single directory.

`-i` gains `nargs="+"` and accepts any mix of files and directories. A directory is
scanned as it is today; a file named directly is taken as given, subject to the same
extension check.

```bash
python tony.py -i ~/Music/Kids                 # as before
python tony.py -i story1.mp3 story2.mp3        # individual files
python tony.py -i ~/Music/Kids extra.mp3       # both
```

`get_audio_files()` takes a list of paths rather than one directory. The CLI gains the
same ability, which is the point of doing it here rather than in the GUI: the
alternative was a temp directory of symlinks that would have made every log line point
somewhere the user never put a file.

This is the only engine change the GUI requires, and it lands first, with its own tests,
before any GUI code.

## Architecture

```
tony.py                  CLI entry point and the whole engine; only -i changes
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

With several Tonies queued, cancelling stops after the one in flight rather than partway
through it where possible, and the summary reports which were completed, which was
interrupted and which were never started.

## Screens and flow

### Main window

```
┌─ Tonie Audio Updater ────────────────────────────────┐
│ Source:  ┌────────────────────────────────────────┐  │
│          │ ~/Music/Kids                 6 files   │  │
│          │ ~/Desktop/extra.mp3                    │  │
│          └────────────────────────────────────────┘  │
│          [Add Files…] [Add Folder…] [Remove]         │
│          7 files · 47 min                            │
│                                                      │
│ Tonies:  ┌────────────────────────────────────────┐  │
│          │ ☑ Elephant    Home   ⚠ needs update    │  │
│          │ ☑ Lion        Home   ⚠ needs update    │  │
│          │ ☐ Giraffe     Attic  ✅ up to date      │  │
│          └────────────────────────────────────────┘  │
│          [Select all] [Select needing update]        │
│                                                      │
│ ▸ Advanced                                           │
│                                                      │
│ ──────────────────────────────────────────────────── │
│ [████████░░░░░░░░] Elephant — uploading 3 of 7       │
│ ┌─ log ────────────────────────────────────────────┐ │
│ │ Clearing all chapters from 'Elephant'            │ │
│ │ Uploading (3/7): Bedtime Story                   │ │
│ └──────────────────────────────────────────────────┘ │
│                               [Cancel]  [ Upload ]   │
└──────────────────────────────────────────────────────┘
```

The source list accepts files and folders in any combination, added through the buttons
or dropped onto the window. Dropping is the natural gesture on macOS for "these files",
and Qt gives it cheaply.

The Tonie list is multi-select, because uploading the same bedtime stories to two
children's Tonies is a normal thing to do. Each row shows the name, the household and
whether it needs updating — the same information the CLI menu prints — and the two
buttons mirror the menu's `a` and `u` shortcuts.

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
3. **Add sources** — a *cheap* scan only, across every path in the source list:
   `tony.find_files()` for directories, the paths themselves for files, then
   `tony.get_audio_duration()` per file to show the count, total runtime and any
   over-limit warning. No conversion, no truncation, no temp files.
4. **Upload** — a confirmation dialog states what is about to happen, mirroring what
   `confirm_selection` prints: every Tonie selected, how many files, total runtime, how
   many chapters will be cleared **across all of them**, and any warning. A selected
   Tonie that is already up to date is named as one that will be skipped, unless Force
   update is on — the same decision `main()` makes.
5. **Run** — the worker calls `tony.get_audio_files()` once (conversion, trimming,
   truncation are shared across every target), then loops the selected Tonies calling
   `tony.needs_update` and `tony.update_tonie` for each. Progress shows which Tonie is
   in flight and its position in the queue.
6. **Finish** — a summary of which Tonies were updated, skipped and failed, and
   `tony.cleanup_converted_files()` in a `finally` so temp files go even on failure or
   cancellation.

A Tonie that fails does not abandon the rest: the remaining ones are still attempted and
the summary reports each outcome, matching how `main()` treats a failure today. The
failure detail — how many files landed, which chapters were cleared — is reported per
Tonie.

### Why the preview is cheap

`get_audio_files()` converts video, trims silence and truncates over-long files. Running
it when a source is added would freeze the window for a minute on a folder holding a
large MKV, for a preview. The cheap scan reuses `find_files()` and `get_audio_duration()`,
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

- **Engine, for the `-i` change** — a directory behaves as before, a named file is
  accepted, a mix of both works, a named file with an unsupported extension is rejected,
  and a missing path is an error naming which one
- **`test_gui_state.py`** — `build_argv()` for every control, including that defaults
  produce the same `args` as the bare CLI, that several source paths survive the trip,
  and that a flag added to `build_parser()` without a control is caught
- **`test_keychain.py`** — store, read, overwrite and delete against a throwaway service
  name, and the behaviour when no entry exists
- **`test_gui_app.py`** — the window driven headless under `QT_QPA_PLATFORM=offscreen`
  with `QTest`: adding a folder and a loose file updates the summary, an over-limit
  source shows the warning, checking two Tonies and pressing Upload clears and uploads to
  both in order against a stubbed `TonieAPI`, an up-to-date Tonie is skipped unless Force
  update is set, one Tonie failing still attempts the next, a failing upload surfaces the
  dialog, and controls are disabled while a run is in progress

Headless Qt tests run in CI and locally without a display.

**Manual verification**, which cannot be automated: one run of the built `.app` to
confirm it opens past Gatekeeper, the Keychain prompt appears and "Always Allow" works,
and the window looks right on a real display.

## Out of scope

- Code signing, notarization and public distribution
- A Windows or Linux GUI
- Editing or reordering chapters already on a Tonie; the API surface used here replaces
  all chapters
- Bundling FFmpeg, as described above

## Success criteria

1. A household member can open the `.app`, add a folder or drop files on it, tick one or
   more Tonies, press Upload and have the audio arrive, without a terminal
2. The same set of files can go to several Tonies in one run, converted once
3. Every CLI option is reachable from the Advanced section
4. The GUI cannot drift from the CLI: both go through `build_parser()`
5. The only engine change is `-i` accepting files as well as directories, it is covered
   by tests, and the existing 79 tests still pass
6. A failed upload tells the user what was lost, as the CLI does, per Tonie
