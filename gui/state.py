"""The boundary that keeps the GUI from drifting from the CLI.

The GUI holds no config of its own. Its controls become a normal argv list, which
tony.parse_args() turns into the same args the command line produces - so defaults,
types and validation have one definition, in build_parser().
"""
import os
from dataclasses import dataclass, field
from typing import List

import tony


@dataclass
class GuiState:
    """Every control in the window. Defaults mirror build_parser()'s."""
    sources: List[str] = field(default_factory=list)

    convert_video: bool = False
    ffmpeg_path: str = "ffmpeg"
    ytdlp_path: str = "yt-dlp"
    audio_bitrate: str = "128k"
    keep_converted: bool = False

    trim_silence: bool = False
    silence_threshold: str = "-50dB"
    min_silence_duration: float = 2.0

    max_duration: float = 90.0
    no_duration_limit: bool = False
    upload_retries: int = 3
    retry_delay: float = 2.0

    dry_run: bool = False
    force_update: bool = False
    non_interactive: bool = False
    tonie_name: str = None


def build_argv(state):
    """Turn the state into the argv the CLI would have been given."""
    argv = []

    for flag, value in (
        ("--ffmpeg-path", state.ffmpeg_path),
        ("--ytdlp-path", state.ytdlp_path),
        ("--audio-bitrate", state.audio_bitrate),
        ("--silence-threshold", state.silence_threshold),
        ("--min-silence-duration", state.min_silence_duration),
        ("--max-duration", state.max_duration),
        ("--upload-retries", state.upload_retries),
        ("--retry-delay", state.retry_delay),
        ("--tonie", state.tonie_name),
    ):
        if value is not None:
            argv += [flag, str(value)]

    for flag, enabled in (
        ("--convert-video", state.convert_video),
        ("--keep-converted", state.keep_converted),
        ("--trim-silence", state.trim_silence),
        ("--no-duration-limit", state.no_duration_limit),
        ("--dry-run", state.dry_run),
        ("--force-update", state.force_update),
        ("--non-interactive", state.non_interactive),
    ):
        if enabled:
            argv.append(flag)

    # A local path is normalised to absolute so a leading "-" (which argparse's
    # option detection would otherwise misread as an unrecognized flag, even for
    # nargs="+") becomes structurally impossible - an absolute path always starts
    # with a path separator, never "-". A URL is left untouched: it always starts
    # with "http://" or "https://" per tony.is_url, so it can never look like a
    # flag either, and os.path.abspath() would corrupt it (it would resolve
    # against the cwd and collapse the "//" after the scheme).
    sources = [s if tony.is_url(s) else os.path.abspath(s) for s in state.sources]

    # Last, because nargs="+" consumes until the next flag
    argv += ["-i", *sources]

    return argv


def apply(state):
    """Set tony's module-level args from this state, and return it."""
    return tony.parse_args(build_argv(state))
