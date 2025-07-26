# Tonie Audio Updater

A Python script to easily upload audio files to Creative Tonies. Supports multiple audio formats and can automatically convert video files to audio with intelligent silence trimming.

## Features

- 🎵 **Multiple Audio Formats**: Supports MP3, WAV, M4A, and OGG files
- 🎬 **Video Conversion**: Automatically converts MKV, MP4, AVI, MOV files to MP3 using FFmpeg
- ✂️ **Silence Trimming**: Intelligently removes trailing silence from converted audio files
- 🏠 **Multi-Household Support**: Works with Creative Tonies across multiple households
- 🎯 **Smart Updates**: Only updates Tonies when content has changed
- 📋 **Interactive Menu**: Easy-to-use interface for selecting which Tonies to update
- 🔍 **Dry Run Mode**: Preview changes before making them
- 🧹 **Automatic Cleanup**: Removes temporary converted files after upload

## Requirements

- Python 3.6 or higher
- FFmpeg (for video conversion and silence trimming)
- Tonie account with Creative Tonies

## Installation

1. **Clone this repository:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/tonie-audio-updater.git
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
python tony.py -u your_username -p your_password -i /path/to/audio/files
```

### Common Options

```bash
# Dry run (preview changes without uploading)
python tony.py -u username -p password -i /path/to/files --dry-run

# Convert video files to audio
python tony.py -u username -p password -i /path/to/files --convert-video

# Convert video files and trim trailing silence
python tony.py -u username -p password -i /path/to/files --convert-video --trim-silence

# Non-interactive mode (updates first Tonie automatically)
python tony.py -u username -p password -i /path/to/files --non-interactive

# Force update even if Tonie seems up to date
python tony.py -u username -p password -i /path/to/files --force-update

# Keep converted audio files instead of deleting them
python tony.py -u username -p password -i /path/to/files --convert-video --keep-converted

# Custom silence detection settings
python tony.py -u username -p password -i /path/to/files --convert-video --trim-silence --silence-threshold -40dB --min-silence-duration 3.0
```

### All Options

| Option | Description |
|--------|-------------|
| `-u, --username` | Tonie account username (required) |
| `-p, --password` | Tonie account password (required) |
| `-i, --input-path` | Path to directory containing audio/video files (required) |
| `--dry-run` | Show what would be done without actually updating |
| `--non-interactive` | Run in non-interactive mode (updates first Tonie) |
| `--force-update` | Force update even if Tonie appears up to date |
| `--convert-video` | Convert video files (MKV, MP4, AVI, MOV) to MP3 audio |
| `--ffmpeg-path` | Path to ffmpeg executable (default: ffmpeg) |
| `--audio-bitrate` | Audio bitrate for video conversion (default: 128k) |
| `--keep-converted` | Keep converted audio files after upload |
| `--trim-silence` | Trim silence at the end of converted audio files |
| `--silence-threshold` | Silence detection threshold (default: -50dB) |
| `--min-silence-duration` | Minimum silence duration to trigger trimming in seconds (default: 2.0) |

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
python tony.py -u username -p password -i /path/to/videos --convert-video --trim-silence

# More aggressive silence detection (quieter threshold)
python tony.py -u username -p password -i /path/to/videos --convert-video --trim-silence --silence-threshold -60dB

# Only trim very long silence periods
python tony.py -u username -p password -i /path/to/videos --convert-video --trim-silence --min-silence-duration 5.0

# Custom settings for both threshold and duration
python tony.py -u username -p password -i /path/to/videos --convert-video --trim-silence --silence-threshold -45dB --min-silence-duration 1.5
```

## How It Works

1. **Scans** your specified directory for audio files (and video files if conversion is enabled)
2. **Connects** to your Tonie account and retrieves all Creative Tonies
3. **Converts** video files to audio (if enabled) and trims silence (if enabled)
4. **Shows an interactive menu** where you can select which Tonies to update
5. **Compares** existing content with your audio files to determine what needs updating
6. **Uploads** new content, replacing existing chapters on selected Tonies
7. **Cleans up** any temporary files created during the process

## Supported File Formats

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
python tony.py -u myemail@example.com -p mypassword -i ~/Music/Kids
```

### Convert video files and upload with silence trimming
```bash
python tony.py -u myemail@example.com -p mypassword -i ~/Videos/Stories --convert-video --trim-silence
```

### Preview what would be updated
```bash
python tony.py -u myemail@example.com -p mypassword -i ~/Audio --dry-run
```

### Advanced video conversion with custom settings
```bash
python tony.py -u myemail@example.com -p mypassword -i ~/Videos --convert-video --trim-silence --silence-threshold -45dB --min-silence-duration 3.0 --audio-bitrate 192k --keep-converted
```

## Troubleshooting

### "No audio files found"
- Check that your directory contains supported audio formats
- If you have video files, use `--convert-video` option
- Make sure the path is correct

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

## Performance Tips

- **Silence trimming** adds processing time but creates cleaner audio files
- Use `--keep-converted` during testing to avoid re-processing files
- Higher `--audio-bitrate` values create better quality but larger files
- The `--dry-run` option lets you test settings without uploading

## Security Notes

- The script requires your Tonie account credentials as command-line arguments
- Credentials are not stored or logged by the script
- Consider using environment variables for credentials in automated setups

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This is an unofficial tool and is not affiliated with or endorsed by Boxine GmbH (makers of Tonie). Use at your own risk.
