# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-06-23

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

---

## Release Notes Template for Future Versions

Use this template for future releases:

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- New features

### Changed
- Changes in existing functionality

### Deprecated  
- Soon-to-be removed features

### Removed
- Now removed features

### Fixed
- Bug fixes

### Security
- Security improvements
```
