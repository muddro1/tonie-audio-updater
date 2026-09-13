# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- The password is no longer required on the command line, where it was visible to any
  user running `ps` and written to shell history. `-u` and `-p` are now optional and
  fall back to `$TONIE_USERNAME` and `$TONIE_PASSWORD`, then to a prompt that reads the
  password without echoing it.

### Added
- `--tonie NAME` selects the Creative Tonie to update in non-interactive runs
- `--upload-retries` (default 3) and `--retry-delay` (default 2.0s, doubling) retry a
  file whose upload fails
- A test suite: `pip install -r requirements-dev.txt && pytest`. Tests that measure or
  truncate audio run a real FFmpeg and skip when it is missing.

### Fixed
- Audio and video files are found whatever the case of their extension. `glob` patterns
  match case-sensitively even on a case-insensitive filesystem, so a directory of `.MP3`
  or `.MOV` files - the usual shape off a ripper or a camera - reported "No audio files
  found".
- The chapter titles on a Tonie are logged before they are cleared, and a failed upload
  reports how many files made it and which chapters were lost. Clearing before uploading
  cannot be avoided, since the 90 minute cap counts a Tonie's total content.
- Reordered chapters are detected as needing an update. Titles were compared as sorted
  lists, so the same files in a different order read as up to date, despite chapter order
  being playback order.
- A mismatch is described with the titles as written rather than lowercased for
  comparison, and counts a title appearing a different number of times.
- Both prompts exit cleanly at end of input instead of raising `EOFError`, so piping
  input no longer ends in a traceback.
- `--min-silence-duration` is parsed as a number, so a typo fails at parse time rather
  than deep inside silence detection.
- `AudioTitle` is hashable again. Defining `__eq__` without `__hash__` set `__hash__` to
  `None`, which would have raised on any attempt to put one in a set.

### Changed
- **Breaking**: `--non-interactive` no longer updates whichever Creative Tonie the API
  listed first. It requires `--tonie NAME` unless the account holds exactly one, and
  treats a name shared by two households as an error. Updating clears the Tonie it
  picks, so guessing was not safe.
- Arguments are parsed in `main()` rather than at import, and `tonie_api` is imported
  there too, so the module can be imported - and tested - without argv or the dependency
  installed.
- Documented WMV and FLV in the video formats the `--convert-video` option accepts; both
  were already supported.
- Dropped four unused imports: `json`, `Config`, `CreativeTonie`, `User`.

## [3.1] - 2026-09-12

### Added
- **90-Minute Duration Limit**
  - Checks total runtime against the 90 minute Creative Tonie limit before uploading
  - A single file longer than the limit is truncated to just under 90 minutes; the
    source file is never modified, a temporary copy is uploaded instead
  - Truncated output is measured and retried if it lands over the limit, since stream
    copying can only cut on a frame boundary and the Tonie service is strict
  - Aborts before any Creative Tonie is modified if a file needs truncating but cannot
    be, rather than clearing the Tonie's chapters for an upload that would be rejected
  - A set of several files that exceeds the limit is reported as a warning in the log and
    on the confirmation screen, but never truncated
  - Total runtime is shown on the confirmation screen
  - New `--max-duration` option to change the limit (default: 90 minutes)
  - New `--no-duration-limit` option to skip the check entirely
  - Skipped with a warning rather than failing when FFmpeg is unavailable

### Changed
- The duration check is on by default. A single file over 90 minutes that previously
  uploaded (and was rejected by the Tonie service) is now truncated instead. Pass
  `--no-duration-limit` for the old behaviour.
- Temporary file cleanup now handles more than one temporary directory

## [3.0] - 2025-07-26

### Added
- **Silence Trimming**
  - Automatically removes trailing silence from converted audio files
  - Uses FFmpeg's `silencedetect` filter to locate the end of actual audio content
  - Trims by stream copying, avoiding a re-encode
  - New `--trim-silence` option to enable it
  - New `--silence-threshold` option to set the detection threshold (default: -50dB)
  - New `--min-silence-duration` option to set the minimum silence that triggers
    trimming (default: 2.0s)

### Changed
- Video-to-audio conversion now optionally trims trailing silence
- Trimming status is shown while converting
- FFmpeg is required rather than optional for video conversion and silence trimming
- Expanded the README with a silence trimming guide

### Fixed
- Better error handling around FFmpeg operations
- Improved temporary file cleanup

## [2.0.1] - 2025-06-24

### Fixed
- Corrected every command example in the README, which referred to a `tony1.py`
  that does not exist, to `tony.py`

## [2.0.0] - 2025-06-24

### Added
- `tony.py`, the uploader itself. Every feature listed under 1.0.0 below was
  documented by that release but only became usable here, since the script was
  missing from the 1.0.0 tree.

### Removed
- `tony.sh`, a leftover wrapper that invoked a `/tony.py` outside the repository
  and passed options the uploader does not accept (`--playlist`,
  `--pushover-userkey`, `--pushover-apptoken`, `--cache-path`)

## [1.0.1] - 2025-06-24

### Added
- This changelog

## [1.0.0] - 2025-06-23

> **Note**: This release documented the features below and described how to install
> and run the tool, but `tony.py` itself was not committed - the tagged tree contained
> only the README, `requirements.txt`, `LICENSE`, `.gitignore`, and an unrelated
> `tony.sh` wrapper. The script arrived in 2.0.0. Treat the list below as the feature
> set this release specified rather than shipped.

### Added
- **Core Functionality**
  - Upload audio files to Creative Tonies via official API
  - Support for multiple audio formats (MP3, WAV, M4A, OGG)
  - Smart content comparison to avoid unnecessary updates
  - Multi-household Creative Tonie support
  - Comprehensive error handling and logging

- **Video Conversion**
  - Automatic video to audio conversion using FFmpeg
  - Support for multiple video formats (MKV, MP4, AVI, MOV, WMV, FLV)
  - Configurable audio bitrate for conversions (default: 128k)
  - Automatic FFmpeg detection and validation
  - Auto-enable video conversion when no audio files found

- **Interactive Features**
  - User-friendly interactive menu for Tonie selection
  - Visual status indicators (✅ up-to-date, ⚠️ needs update)
  - Support for multiple selection methods:
    - Individual numbers: `1,3,5`
    - Ranges: `1-3`
    - Keywords: `all`, `update` (updates only needed), `quit`
  - Confirmation prompts before making changes
  - Progress indicators during uploads

- **Command Line Options**
  - `--dry-run`: Preview changes without uploading
  - `--non-interactive`: Automated mode for scripts
  - `--force-update`: Override smart update detection
  - `--convert-video`: Enable video conversion
  - `--keep-converted`: Preserve converted audio files
  - `--ffmpeg-path`: Custom FFmpeg executable path
  - `--audio-bitrate`: Configurable conversion quality

- **File Management**
  - Automatic title truncation to 100 characters for compatibility
  - Temporary file cleanup after uploads
  - Smart filename handling and duplicate prevention
  - Sorted file processing for consistent ordering

- **Safety Features**
  - Dry run mode for testing
  - Update confirmation dialogs
  - Graceful error handling and recovery
  - Keyboard interrupt handling (Ctrl+C)
  - Automatic cleanup on exit

### Technical Details
- **Dependencies**: Minimal dependencies (only `tonie-api` required)
- **Python Support**: Python 3.6+
- **Cross-Platform**: Windows, macOS, Linux compatible
- **API Integration**: Official Tonie API using `tonie_api` library
- **Logging**: Structured logging with timestamps and levels
- **Architecture**: Modular design with separated concerns

### Documentation
- Comprehensive README with usage examples
- Detailed command-line help
- Installation instructions for all platforms
- Troubleshooting guide
- Security considerations
