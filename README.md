# Tonie Audio Updater

A Python script to easily upload audio files to Creative Tonies. Supports multiple audio formats and can automatically convert video files to audio with intelligent silence trimming.

## Features

- 🎵 **Multiple Audio Formats**: Supports MP3, WAV, M4A, and OGG files
- 🎬 **Video Conversion**: Automatically converts MKV, MP4, AVI, MOV, WMV, and FLV files to MP3 using FFmpeg
- ✂️ **Silence Trimming**: Intelligently removes trailing silence from converted audio files
- ⏱️ **90-Minute Limit**: Truncates a single over-long file to the 90 minute Creative Tonie limit, and warns when a set of files exceeds it
- 🏠 **Multi-Household Support**: Works with Creative Tonies across multiple households
- 🎯 **Smart Updates**: Only updates Tonies when content has changed
- 📋 **Interactive Menu**: Easy-to-use interface for selecting which Tonies to update
- 🔍 **Dry Run Mode**: Preview changes before making them
- 🧹 **Automatic Cleanup**: Removes temporary converted files after upload
- 🔑 **Credentials Kept Off the Command Line**: Reads `$TONIE_USERNAME` and `$TONIE_PASSWORD`, or prompts without echoing
- 🔁 **Upload Retries**: Retries a file that fails on a dropped connection, and records what was on the Tonie first

## Requirements

- Python 3.6 or higher
- FFmpeg (for video conversion and silence trimming)
- yt-dlp (for links and playlists, see [All Options](#all-options))
- Tonie account with Creative Tonies

## Installation

1. **Clone this repository:**
   ```bash
   git clone https://github.com/muddro1/tonie-audio-updater.git
   cd tonie-audio-updater
   ```

2. **Install Python dependencies:**

   **Option A: Direct installation**
   ```bash
   pip install -r requirements.txt
   ```

   **Option B: Using virtual environment (recommended)**
   ```bash
   # Create virtual environment
   python -m venv tonie-env
   
   # Activate virtual environment
   # On Windows:
   tonie-env\Scripts\activate
   # On macOS/Linux:
   source tonie-env/bin/activate
   
   # Install dependencies
   pip install -r requirements.txt
   ```

   > **Note**: If using a virtual environment, remember to activate it each time before running the script:
   > - Windows: `tonie-env\Scripts\activate`
   > - macOS/Linux: `source tonie-env/bin/activate`

3. **Install FFmpeg** (required for video conversion and silence trimming):
   - **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html)
   - **macOS**: `brew install ffmpeg`
   - **Ubuntu/Debian**: `sudo apt install ffmpeg`

## Usage

### Basic Usage

```bash
python tony.py -i /path/to/audio/files
```

You will be prompted for your username and password. To avoid the prompt, export
them first:

```bash
export TONIE_USERNAME=you@example.com
export TONIE_PASSWORD='your-password'
python tony.py -i /path/to/audio/files
```

Both can still be passed as `-u` and `-p`, but see [Credentials](#credentials)
before putting a password on the command line.

### Several Sources at Once

`-i` takes more than one path, and accepts individual files as well as directories:

```bash
# Two folders and a loose file in one run
python tony.py -i ~/Music/Kids ~/Downloads/Story.mp3 ~/Videos/Bedtime

# A single audio or video file
python tony.py -i ~/Downloads/Bedtime-Story.m4a
```

### Links and Playlists

A link is downloaded with `yt-dlp`, which must be installed separately (`brew install
yt-dlp`, or see [yt-dlp's own instructions](https://github.com/yt-dlp/yt-dlp)) - it is
detected, not bundled, the same way FFmpeg is:

```bash
# A single video
python tony.py -i "https://www.youtube.com/watch?v=XXXXXXXXXXX"

# A playlist - every video in it is downloaded as a chapter
python tony.py -i "https://www.youtube.com/playlist?list=XXXXXXXXXXXXXXXXXXXX"

# Links mixed with local files and folders in the same run
python tony.py -i ~/Music/Kids "https://www.youtube.com/watch?v=XXXXXXXXXXX"
```

Point `--ytdlp-path` at the executable if it is not on `PATH`.

### Common Options

```bash
# Dry run (preview changes without uploading)
python tony.py -i /path/to/files --dry-run

# Convert video files to audio
python tony.py -i /path/to/files --convert-video

# Convert video files and trim trailing silence
python tony.py -i /path/to/files --convert-video --trim-silence

# Non-interactive mode (no menu; names the Tonie to update)
python tony.py -i /path/to/files --non-interactive --tonie "Elephant"

# Force update even if Tonie seems up to date
python tony.py -i /path/to/files --force-update

# Keep converted audio files instead of deleting them
python tony.py -i /path/to/files --convert-video --keep-converted

# Custom silence detection settings
python tony.py -i /path/to/files --convert-video --trim-silence --silence-threshold -40dB --min-silence-duration 3.0

# Raise or lower the duration limit (default: 90 minutes)
python tony.py -i /path/to/files --max-duration 60

# Upload a long file untouched, without the duration check
python tony.py -i /path/to/files --no-duration-limit
```

### All Options

| Option | Description |
|--------|-------------|
| `-u, --username` | Tonie account username (default: `$TONIE_USERNAME`, otherwise prompted for) |
| `-p, --password` | Tonie account password. Exposes it in `ps` output and shell history — prefer `$TONIE_PASSWORD` |
| `-i, --input-path` | One or more files or directories containing audio/video, and/or links to a video or a playlist (required). List them all after a single `-i`, separated by spaces (`-i a b c`) - repeating the flag keeps only the last one |
| `--dry-run` | Show what would be done without actually updating |
| `--non-interactive` | Run without the selection menu. Needs `--tonie` unless the account holds exactly one Creative Tonie |
| `--tonie` | Name of the Creative Tonie to update, for non-interactive runs (case-insensitive) |
| `--force-update` | Force update even if Tonie appears up to date |
| `--convert-video` | Convert video files (MKV, MP4, AVI, MOV, WMV, FLV) to MP3 audio |
| `--ffmpeg-path` | Path to ffmpeg executable (default: ffmpeg) |
| `--ytdlp-path` | Path to the yt-dlp executable, used to resolve and download links (default: yt-dlp) |
| `--audio-bitrate` | Audio bitrate for video conversion (default: 128k) |
| `--keep-converted` | Keep converted audio files after upload. A converted video's audio is written beside the video; a downloaded link's audio goes to `~/Downloads` |
| `--trim-silence` | Trim silence at the end of converted audio files |
| `--silence-threshold` | Silence detection threshold (default: -50dB) |
| `--min-silence-duration` | Minimum silence duration to trigger trimming in seconds (default: 2.0) |
| `--max-duration` | Maximum minutes a Creative Tonie accepts; a single longer file is truncated to this length (default: 90) |
| `--no-duration-limit` | Skip the duration limit check entirely (no truncation, no warning) |
| `--upload-retries` | Attempts per file before giving up on an upload (default: 3) |
| `--retry-delay` | Seconds between upload attempts, doubling each time (default: 2.0) |

## macOS App

A native macOS GUI wraps the same engine as the `tony.py` command line: pick files,
folders, or links (drag and drop works too); tick the Creative Tonies to update; watch
the log; done. It stores credentials in the macOS Keychain rather than the
environment, shows each Tonie's own picture with its current chapters (expand a row to
see them), and shows a banner instead of a traceback when FFmpeg or yt-dlp is missing.

### Running It

**From source**, no build needed:

```bash
pip install -r requirements.txt -r requirements-gui.txt
python -m gui
```

**As a built app**, unsigned:

```bash
pip install -r requirements.txt -r requirements-gui.txt -r requirements-dev.txt
./build/build_app.sh
```

This produces `build/dist/Tonie Audio Updater.app`. It is not code-signed or notarized,
so the first time you open it, macOS Gatekeeper refuses a double click. Right-click
the app, choose **Open**, then **Open** again on the dialog that follows - this
override is required only once, and macOS remembers the choice from then on.

### What It Does and Does Not Bundle

FFmpeg and yt-dlp are detected on `PATH` (or at the path given in Advanced options)
rather than bundled into the app. If either is missing, a banner names which one and
gives you the install command to copy; uploading plain audio files still works with
neither installed, since only video conversion and links need them.

### Sign-In

Credentials are asked for once and, if you choose to remember them, kept in the macOS
Keychain rather than in a file or an environment variable - the same prompt macOS
itself uses for network passwords. Quitting and reopening the app does not ask again
until you sign out.

**Sign Out** appears beside the account button once you are signed in. It removes the
Keychain entry and the remembered username and empties the Creative Tonie list, so the
next launch asks for credentials again.

## Silence Trimming Feature

The silence trimming feature automatically detects and removes long periods of silence at the end of converted audio files, making them cleaner and more professional.

### How It Works

1. **Detection**: Uses FFmpeg's `silencedetect` filter to analyze audio and identify silence periods
2. **Analysis**: Finds the last silence period that extends to (or near) the end of the file
3. **Trimming**: Removes trailing silence if it meets the minimum duration threshold
4. **Efficiency**: Uses audio stream copying to avoid re-encoding when possible

### Configuration Options

- **`--silence-threshold`**: Audio level below which is considered silence (default: -50dB)
  - Lower values (e.g., -60dB) detect quieter sounds as silence
  - Higher values (e.g., -30dB) only detect very quiet periods as silence
  
- **`--min-silence-duration`**: Minimum length of silence required to trigger trimming (default: 2.0 seconds)
  - Prevents trimming of brief pauses
  - Longer durations ensure only significant trailing silence is removed

### Examples

```bash
# Basic silence trimming with default settings
python tony.py -i /path/to/videos --convert-video --trim-silence

# More aggressive silence detection (quieter threshold)
python tony.py -i /path/to/videos --convert-video --trim-silence --silence-threshold -60dB

# Only trim very long silence periods
python tony.py -i /path/to/videos --convert-video --trim-silence --min-silence-duration 5.0

# Custom settings for both threshold and duration
python tony.py -i /path/to/videos --convert-video --trim-silence --silence-threshold -45dB --min-silence-duration 1.5
```

## Duration Limit

A Creative Tonie holds a maximum of **90 minutes** of audio. The script checks the total
runtime before uploading so you find out up front instead of watching the upload fail.

### How the Limit Is Applied

1. **Measurement**: Every file's duration is read with FFmpeg after any video conversion
   and silence trimming, so the check reflects the audio as it will actually be uploaded
2. **One file over the limit**: The file is truncated to just under 90 minutes, and the
   result is measured to confirm it fits before the upload goes ahead
3. **Several files over the limit**: Nothing is truncated - the total is reported as a
   warning, both in the log and on the confirmation screen, since which file to shorten
   is your call
4. **Under the limit**: Nothing changes; the total runtime is shown on the confirmation
   screen

### Why It Lands Just Under 90 Minutes

The Tonie service enforces the limit strictly, and truncating without re-encoding can
only cut on an audio frame boundary - so asking for exactly 90:00 produces a file a few
milliseconds *over*, which gets rejected. The script therefore aims about a second below
the limit and measures the result, widening the gap and retrying if the file still comes
out over. Expect a truncated file to run around 89:59.

If a file needs truncating but cannot be truncated, the script **stops before touching
any Creative Tonie**. Uploading it would clear the Tonie's existing chapters first and
then be rejected, leaving you with an empty Tonie.

### Your Source Files Are Never Modified

Truncation always writes a **copy** to a temporary directory and uploads that. The
original file in your input directory is left exactly as it was, and the temporary copy
is deleted after the upload (unless you pass `--keep-converted`).

### Examples

```bash
# Default: a single file longer than 90 minutes is truncated to 90 minutes
python tony.py -i /path/to/files

# Truncate to 60 minutes instead
python tony.py -i /path/to/files --max-duration 60

# Turn the check off completely
python tony.py -i /path/to/files --no-duration-limit
```

> **Note**: The duration check needs FFmpeg. If FFmpeg isn't installed and you're
> uploading plain audio files, the check is skipped with a warning and everything else
> works as before.

## How It Works

1. **Scans** your specified directory for audio files (and video files if conversion is enabled)
2. **Connects** to your Tonie account and retrieves all Creative Tonies
3. **Converts** video files to audio (if enabled) and trims silence (if enabled)
4. **Shows an interactive menu** where you can select which Tonies to update
5. **Compares** existing content with your audio files to determine what needs updating
6. **Uploads** new content, replacing existing chapters on selected Tonies
7. **Cleans up** any temporary files created during the process

## Supported File Formats

Extension case is ignored, so `.MP3` and `.MOV` work as well as `.mp3` and `.mov`.
Only the input directory itself is scanned — subdirectories are not searched.

### Audio Files (Direct Upload)
- MP3
- WAV
- M4A
- OGG

### Video Files (Converted to MP3)
- MKV
- MP4
- AVI
- MOV
- WMV
- FLV

## Interactive Menu

The script provides an easy-to-use menu system:

- **View all your Creative Tonies** with current status
- **See which Tonies need updates** and why
- **Select multiple Tonies** using numbers, ranges (1-3), or keywords (all, update)
- **Preview changes** before confirming
- **Visual indicators** for converted files and silence trimming status

## Examples

### Upload audio files from a folder
```bash
python tony.py -i ~/Music/Kids
```

### Convert video files and upload with silence trimming
```bash
python tony.py -i ~/Videos/Stories --convert-video --trim-silence
```

### Preview what would be updated
```bash
python tony.py -i ~/Audio --dry-run
```

### Advanced video conversion with custom settings
```bash
python tony.py -i ~/Videos --convert-video --trim-silence --silence-threshold -45dB --min-silence-duration 3.0 --audio-bitrate 192k --keep-converted
```

## Troubleshooting

### "No audio files found"
- Check that your directory contains supported audio formats
- If you have video files, use `--convert-video` option
- Make sure the path is correct
- Only the directory itself is scanned; files in subdirectories are not picked up
- Extension case does not matter — `Story.MP3` and `Clip.MOV` are found just like
  their lowercase forms

### "ffmpeg not found"
- Install FFmpeg on your system
- Use `--ffmpeg-path` to specify the full path to ffmpeg
- FFmpeg is required for both video conversion and silence trimming

### Silence trimming not working
- Ensure `--trim-silence` is used with `--convert-video`
- Check that FFmpeg supports the `silencedetect` filter
- Try adjusting `--silence-threshold` and `--min-silence-duration` values
- Use `--keep-converted` to inspect the audio files before they're cleaned up

### Connection issues
- Verify your Tonie account credentials
- Check your internet connection
- Make sure you have Creative Tonies in your account

### Upload failures
- Ensure audio files are not corrupted
- Check file permissions
- Try with smaller files first
- Each file is retried automatically; raise `--upload-retries` on a flaky connection
- A file over 90 minutes is truncated rather than rejected — see [Duration Limit](#duration-limit)
- If an upload fails partway, the log lists the chapter titles that were cleared, so
  you know what to put back

### "--non-interactive needs --tonie NAME"
- The account holds more than one Creative Tonie, and updating clears the one it picks,
  so the script will not guess. Pass `--tonie "Name"`; the error lists the names found.

## Performance Tips

- **Silence trimming** adds processing time but creates cleaner audio files
- Use `--keep-converted` during testing to avoid re-processing files
- Higher `--audio-bitrate` values create better quality but larger files
- The `--dry-run` option lets you test settings without uploading

## Credentials

The script needs your Tonie account username and password. It looks for them in this
order:

1. `-u` and `-p` on the command line
2. `$TONIE_USERNAME` and `$TONIE_PASSWORD`
3. An interactive prompt — the password is read without echoing

**Avoid `-p`.** Anything on a command line is visible to every user on the machine
through `ps`, and your shell writes it to history. For a scheduled or scripted run,
put the password in the environment instead:

```bash
export TONIE_PASSWORD='your-password'
python tony.py -i /path/to/files --non-interactive --tonie "Elephant"
```

In `--non-interactive` mode there is nowhere to prompt, so the username and password
must come from the environment or the flags. The script says so plainly rather than
hanging on a prompt no one can answer.

Credentials are never stored or logged by the script.

## Non-Interactive Runs

`--non-interactive` skips the selection menu, for cron jobs and scripts.

Because updating a Tonie **clears its existing chapters first**, this mode never
guesses which Tonie you meant. Pass `--tonie NAME` (matched case-insensitively). The
name is only optional when the account holds exactly one Creative Tonie; otherwise the
script stops and lists the names it found. A name that two households both use is an
error rather than a coin flip.

```bash
python tony.py -i /path/to/files --non-interactive --tonie "Elephant"
```

## If an Upload Fails

A Tonie's chapters are cleared before the new files go up. That order is forced: the
90 minute cap counts a Tonie's *total* content, so new audio cannot be added alongside
the old and swapped afterwards.

So that a dropped connection does not cost you the Tonie's contents:

- The titles already on the Tonie are logged **before** they are cleared, giving you a
  record of what was there
- Each file is retried `--upload-retries` times (default 3), waiting `--retry-delay`
  seconds and doubling between attempts
- If a file still fails, the script reports how many made it and which chapters were
  cleared, then stops rather than continuing

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

Tests that measure or truncate audio run a real FFmpeg rather than a mock, since what
they check is where FFmpeg lands on a frame boundary. They skip automatically when
FFmpeg is not installed.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This is an unofficial tool and is not affiliated with or endorsed by Boxine GmbH (makers of Tonie). Use at your own risk.
