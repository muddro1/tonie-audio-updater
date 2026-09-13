#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from collections import Counter

import getpass
import logging
import time
import os
import sys
import tempfile
import subprocess
from pathlib import Path
from argparse import ArgumentParser
from dataclasses import dataclass
from typing import Optional

@dataclass(eq=False)
class AudioTitle:
    filepath: str
    title: str
    is_converted: bool = False  # Track if this was converted from video
    is_capped: bool = False  # Track if this was truncated to the duration limit
    duration: Optional[float] = None  # Duration in seconds, when known
    
    def __eq__(self, other):
        return self.title == other.title

    def __hash__(self):
        # Defining __eq__ alone would set __hash__ to None, making these unhashable
        return hash(self.title)

# Populated by parse_args(). Module level so every function can read it, but set
# explicitly rather than at import, which keeps this file importable (and testable)
# without argv.
args = None

def build_parser():
    """Build the argument parser"""
    usage = f"""
Tonie Audio Updater - Upload audio files to Creative Tonies

Python {sys.version}
Usage: {os.path.basename(__file__)} [options]
"""

    parser = ArgumentParser(usage=usage)
    parser.add_argument("-u", "--username", dest="username",
                        help="Tonie account username (default: $TONIE_USERNAME, "
                             "otherwise prompted for)")
    parser.add_argument("-p", "--password", dest="password",
                        help="Tonie account password. Passing it here exposes it in "
                             "`ps` output and your shell history - prefer "
                             "$TONIE_PASSWORD, or let it be prompted for")
    parser.add_argument("-i", "--input-path", dest="input_path", required=True, 
                        help="Path to directory containing audio files (MP3, WAV, M4A, OGG) and optionally video files")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="Show what would be done without actually updating")
    parser.add_argument("--non-interactive", dest="non_interactive", action="store_true",
                        help="Run without the selection menu. Needs --tonie unless the "
                             "account holds exactly one Creative Tonie")
    parser.add_argument("--tonie", dest="tonie_name",
                        help="Name of the Creative Tonie to update, for non-interactive "
                             "runs (case-insensitive)")
    parser.add_argument("--force-update", dest="force_update", action="store_true",
                        help="Force update even if tonie appears up to date")
    parser.add_argument("--convert-video", dest="convert_video", action="store_true",
                        help="Convert video files (MKV, MP4, AVI, MOV) to MP3 audio")
    parser.add_argument("--ffmpeg-path", dest="ffmpeg_path", default="ffmpeg",
                        help="Path to ffmpeg executable (default: ffmpeg)")
    parser.add_argument("--audio-bitrate", dest="audio_bitrate", default="128k",
                        help="Audio bitrate for video conversion (default: 128k)")
    parser.add_argument("--keep-converted", dest="keep_converted", action="store_true",
                        help="Keep converted audio files after upload (default: delete temporary files)")
    parser.add_argument("--trim-silence", dest="trim_silence", action="store_true",
                        help="Trim silence at the end of converted audio files")
    parser.add_argument("--silence-threshold", dest="silence_threshold", default="-50dB",
                        help="Silence detection threshold (default: -50dB)")
    parser.add_argument("--min-silence-duration", dest="min_silence_duration",
                        type=float, default=2.0,
                        help="Minimum silence duration to trigger trimming in seconds (default: 2.0)")
    parser.add_argument("--max-duration", dest="max_duration", type=float, default=90.0,
                        help="Maximum minutes a Creative Tonie accepts; a single longer file is truncated to this length (default: 90)")
    parser.add_argument("--no-duration-limit", dest="no_duration_limit", action="store_true",
                        help="Skip the duration limit check entirely (no truncation, no warning)")
    parser.add_argument("--upload-retries", dest="upload_retries", type=int, default=3,
                        help="Attempts per file before giving up on an upload (default: 3)")
    parser.add_argument("--retry-delay", dest="retry_delay", type=float, default=2.0,
                        help="Seconds to wait between upload attempts, doubling each time (default: 2.0)")

    return parser

def parse_args(argv=None):
    """Parse argv into the module-level args"""
    global args
    args = build_parser().parse_args(argv)
    return args

def resolve_credentials(parsed_args):
    """Work out the username and password to use.

    A password on the command line is readable by anyone who can run `ps`, and is
    recorded in shell history, so it is no longer required there. Order of preference:
    the flag, then the environment, then an interactive prompt.
    """
    username = parsed_args.username or os.environ.get("TONIE_USERNAME")
    password = parsed_args.password or os.environ.get("TONIE_PASSWORD")

    if not username:
        username = input("Tonie account username: ").strip()
    if not password:
        password = getpass.getpass("Tonie account password: ")

    if not username:
        raise ValueError("A username is required. Pass -u, set $TONIE_USERNAME, "
                         "or enter one when prompted.")
    if not password:
        raise ValueError("A password is required. Set $TONIE_PASSWORD, enter one when "
                         "prompted, or pass -p (which exposes it to `ps`).")

    return username, password

def setup_logging():
    """Send structured logs to stdout"""
    logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                        format='%(asctime)s | %(levelname)s | %(message)s')

AUDIO_EXTENSIONS = ('.mp3', '.wav', '.m4a', '.ogg')
VIDEO_EXTENSIONS = ('.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv')

# The Tonie service enforces its duration limit strictly, and stream copying can only
# cut on a frame boundary. Aim this far under the limit so the result fits.
CAP_SAFETY_MARGIN = 1.0  # seconds
CAP_MAX_ATTEMPTS = 4  # margin widens each attempt: 1s, 5s, 21s, 85s

def find_files(directory, extensions):
    """List the files in directory with one of these extensions, ignoring case.

    glob patterns match case-sensitively even on a case-insensitive filesystem, so
    `*.mp3` silently misses a file named Story.MP3 - the usual shape of a track
    straight off a ripper, or a clip off a camera.
    """
    matches = []

    with os.scandir(directory) as entries:
        for entry in entries:
            if not entry.is_file():
                continue
            if os.path.splitext(entry.name)[1].lower() in extensions:
                matches.append(entry.path)

    return sorted(matches)

def check_ffmpeg():
    """Check if ffmpeg is available"""
    try:
        subprocess.run([args.ffmpeg_path, "-version"], 
                      capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def get_audio_duration(audio_path):
    """Get the duration of an audio file in seconds, or None if it can't be read"""
    try:
        cmd = [
            args.ffmpeg_path,
            "-i", str(audio_path),
            "-f", "null",
            "-"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        for line in result.stderr.split('\n'):
            if 'Duration:' in line:
                try:
                    duration_str = line.split('Duration: ')[1].split(',')[0]
                    h, m, s = duration_str.split(':')
                    return float(h) * 3600 + float(m) * 60 + float(s)
                except (IndexError, ValueError):
                    continue

        return None

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logging.warning(f"Failed to read duration of {audio_path}: {e}")
        return None

def format_duration(seconds):
    """Format a duration in seconds as H:MM:SS"""
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"

def detect_silence_end(audio_path):
    """Detect the end of actual audio content (start of trailing silence)"""
    try:
        # Use ffmpeg's silencedetect filter to find silence
        cmd = [
            args.ffmpeg_path,
            "-i", str(audio_path),
            "-af", f"silencedetect=noise={args.silence_threshold}:d={args.min_silence_duration}",
            "-f", "null",
            "-"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # Parse the silencedetect output
        silence_starts = []
        silence_ends = []
        
        for line in result.stderr.split('\n'):
            if 'silence_start:' in line:
                try:
                    start_time = float(line.split('silence_start: ')[1].split(' ')[0])
                    silence_starts.append(start_time)
                except (IndexError, ValueError):
                    continue
            elif 'silence_end:' in line:
                try:
                    end_time = float(line.split('silence_end: ')[1].split(' ')[0])
                    silence_ends.append(end_time)
                except (IndexError, ValueError):
                    continue
        
        # Get the duration of the audio file
        total_duration = get_audio_duration(audio_path)

        if total_duration is None:
            logging.warning("Could not determine audio duration")
            return None
        
        # Find the last silence that extends to the end of the file
        if silence_starts:
            # Check if the last silence period extends to near the end
            last_silence_start = silence_starts[-1]
            
            # If there's trailing silence that starts before the end and continues to the end
            # (or very close to it), we want to trim from that point
            if total_duration - last_silence_start >= args.min_silence_duration:
                # Verify this silence continues to near the end
                if len(silence_ends) < len(silence_starts) or silence_ends[-1] < last_silence_start:
                    # Silence continues to the end
                    return last_silence_start
                elif len(silence_ends) >= len(silence_starts):
                    # Check if the gap between last silence end and file end is small
                    if total_duration - silence_ends[-1] < 1.0:  # Less than 1 second of audio after last silence
                        return last_silence_start
        
        return None
        
    except subprocess.CalledProcessError as e:
        logging.warning(f"Failed to detect silence in {audio_path}: {e}")
        return None

def truncate_title(title, max_length=100):
    """Truncate title to maximum length while preserving readability"""
    if len(title) <= max_length:
        return title
    
    # Try to truncate at word boundary
    truncated = title[:max_length]
    last_space = truncated.rfind(' ')
    
    if last_space > max_length * 0.7:  # If we can preserve at least 70% and break at word
        return truncated[:last_space].rstrip()
    else:
        # Just truncate and add ellipsis
        return truncated[:max_length-3] + "..."

def convert_video_to_audio(video_path, output_dir=None):
    """Convert video file to MP3 using ffmpeg, optionally trimming trailing silence"""
    video_path = Path(video_path)
    
    if output_dir is None:
        output_dir = tempfile.gettempdir()
    
    # Create output filename
    base_name = video_path.stem
    audio_filename = f"{base_name}.mp3"
    audio_path = Path(output_dir) / audio_filename
    
    # Ensure unique filename
    counter = 1
    while audio_path.exists():
        audio_filename = f"{base_name}_{counter}.mp3"
        audio_path = Path(output_dir) / audio_filename
        counter += 1
    
    logging.info(f"Converting video to audio: {video_path.name} -> {audio_path.name}")
    
    try:
        # Use ffmpeg to extract audio
        cmd = [
            args.ffmpeg_path,
            "-i", str(video_path),
            "-vn",  # No video
            "-acodec", "mp3",
            "-ab", args.audio_bitrate,
            "-ar", "44100",  # Sample rate
            "-y",  # Overwrite output file
            str(audio_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logging.debug(f"ffmpeg output: {result.stderr}")
        
        # If silence trimming is enabled, detect and trim trailing silence
        if args.trim_silence:
            logging.info(f"Analyzing audio for trailing silence: {audio_path.name}")
            trim_point = detect_silence_end(audio_path)
            
            if trim_point is not None:
                logging.info(f"Trimming trailing silence from {trim_point:.1f}s to end")
                
                # Create trimmed version
                trimmed_path = audio_path.parent / f"{audio_path.stem}_trimmed{audio_path.suffix}"
                
                trim_cmd = [
                    args.ffmpeg_path,
                    "-i", str(audio_path),
                    "-t", str(trim_point),  # Trim to the silence start point
                    "-acodec", "copy",  # Copy audio codec to avoid re-encoding
                    "-y",
                    str(trimmed_path)
                ]
                
                trim_result = subprocess.run(trim_cmd, capture_output=True, text=True, check=True)
                
                # Replace original with trimmed version
                os.remove(audio_path)
                os.rename(trimmed_path, audio_path)
                
                logging.info(f"Successfully trimmed {audio_path.name}")
            else:
                logging.info(f"No significant trailing silence detected in {audio_path.name}")
        
        return str(audio_path)
        
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to convert {video_path}: {e}")
        logging.error(f"ffmpeg stderr: {e.stderr}")
        raise

def get_audio_files(input_path):
    """Get all audio files from the input directory, optionally converting video files"""
    audio_files = []
    converted_files = []  # Track converted files for cleanup
    
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input path does not exist: {input_path}")
    
    # Get audio files first
    for audio_file in find_files(input_path, AUDIO_EXTENSIONS):
        title = os.path.splitext(os.path.basename(audio_file))[0]
        # Truncate title to 100 characters
        title = truncate_title(title, 100)
        audio_files.append(AudioTitle(filepath=audio_file, title=title))
    
    # Check if we need to auto-enable video conversion
    auto_convert_video = False
    if not audio_files and not args.convert_video:
        # No audio files found, check if there are video files
        video_files = find_files(input_path, VIDEO_EXTENSIONS)

        if video_files:
            logging.info(f"No audio files found, but found {len(video_files)} video files")
            logging.info("Automatically enabling video conversion...")
            auto_convert_video = True
    
    # Handle video files if conversion is enabled (manually or automatically)
    if args.convert_video or auto_convert_video:
        if not check_ffmpeg():
            logging.error(f"ffmpeg not found at '{args.ffmpeg_path}'. Please install ffmpeg or specify correct path with --ffmpeg-path")
            raise FileNotFoundError("ffmpeg is required for video conversion")
        
        video_files = find_files(input_path, VIDEO_EXTENSIONS)

        if video_files:
            if auto_convert_video:
                logging.info(f"Auto-converting {len(video_files)} video files to audio")
            else:
                logging.info(f"Found {len(video_files)} video files to convert")
            
            if args.trim_silence:
                logging.info(f"Silence trimming enabled (threshold: {args.silence_threshold}, min duration: {args.min_silence_duration:g}s)")
            
            # Create temp directory for converted files if not keeping them
            temp_dir = None
            if not args.keep_converted:
                temp_dir = tempfile.mkdtemp(prefix="tonie_converted_")
                logging.info(f"Using temporary directory for converted files: {temp_dir}")
            else:
                # Use input directory for converted files
                temp_dir = input_path
                logging.info("Converted files will be saved in the input directory")
            
            for video_file in video_files:
                try:
                    audio_file_path = convert_video_to_audio(video_file, temp_dir)
                    title = os.path.splitext(os.path.basename(video_file))[0]
                    # Truncate title to 100 characters
                    title = truncate_title(title, 100)
                    audio_files.append(AudioTitle(
                        filepath=audio_file_path, 
                        title=title, 
                        is_converted=True
                    ))
                    converted_files.append(audio_file_path)
                except Exception as e:
                    logging.error(f"Failed to convert {video_file}: {e}")
                    continue
    
    if not audio_files:
        file_types = "audio files"
        if args.convert_video or auto_convert_video:
            file_types += " or video files"
        raise ValueError(f"No {file_types} found in {input_path}")
    
    # Sort by filename for consistent ordering
    audio_files.sort(key=lambda x: x.title.lower())

    # Store converted files list for cleanup. Done before the duration check so that
    # anything it writes is registered even if it aborts (same list object, so appending
    # to converted_files below still updates the global).
    global _converted_files
    _converted_files = converted_files

    # Truncate a single over-long file, or warn when a set exceeds the Tonie limit
    enforce_max_duration(audio_files, converted_files)
    
    return audio_files

def cap_audio_file(audio_file, max_seconds, temp_files):
    """Write a copy of audio_file that plays for no more than max_seconds.

    Returns the path to the truncated copy, or None if it could not be produced. The
    copy always goes to a temp directory so it never lands back in the input directory,
    where a later scan would pick it up as an extra file. Its path is appended to
    temp_files as soon as ffmpeg is asked to write it, so even a failed or over-length
    attempt gets cleaned up.

    Stream copying can only cut on a frame boundary, so ffmpeg rounds up and a plain
    `-t max_seconds` lands slightly *over* the limit - enough for the Tonie service to
    reject it. We aim a safety margin below the limit, then measure the result and
    widen the margin until it actually fits.
    """
    source = Path(audio_file.filepath)

    # Reuse the temp directory a converted file already lives in, otherwise make one
    source_dir = str(source.parent)
    if source_dir.startswith(tempfile.gettempdir()):
        output_dir = Path(source_dir)
    else:
        output_dir = Path(tempfile.mkdtemp(prefix="tonie_capped_"))

    capped_path = output_dir / f"{source.stem}_capped{source.suffix}"
    counter = 1
    while capped_path.exists():
        capped_path = output_dir / f"{source.stem}_capped_{counter}{source.suffix}"
        counter += 1

    margin = CAP_SAFETY_MARGIN

    for attempt in range(1, CAP_MAX_ATTEMPTS + 1):
        target = max_seconds - margin

        if target <= 0:
            logging.error(f"Cannot truncate {source.name}: the {max_seconds:g} second "
                          f"limit is shorter than the safety margin")
            return None

        cmd = [
            args.ffmpeg_path,
            "-i", str(source),
            "-t", str(target),  # Keep only the first `target` seconds
            "-acodec", "copy",  # Copy audio codec to avoid re-encoding
            "-y",
            str(capped_path)
        ]

        if str(capped_path) not in temp_files:
            temp_files.append(str(capped_path))

        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to truncate {source.name}: {e}")
            logging.error(f"ffmpeg stderr: {e.stderr}")
            return None

        # Measure what we actually got - the frame boundary decides, not our target
        actual = get_audio_duration(capped_path)

        if actual is None:
            logging.warning(f"Could not measure the truncated copy of {source.name} - "
                            f"assuming it is within the limit")
            return str(capped_path)

        if actual <= max_seconds:
            logging.debug(f"Truncated to {actual:.2f}s (target {target:.2f}s, "
                          f"limit {max_seconds:.2f}s) on attempt {attempt}")
            return str(capped_path)

        # Still over: the frame boundary rounded past the limit, so aim further under.
        # The +1 guarantees the margin grows even from zero.
        logging.debug(f"Truncated copy came out at {actual:.2f}s, still over the "
                      f"{max_seconds:.2f}s limit - widening the margin")
        margin = margin * 4 + 1.0

    logging.error(f"Could not truncate {source.name} to within {max_seconds:g} seconds "
                  f"after {CAP_MAX_ATTEMPTS} attempts")
    return None

def enforce_max_duration(audio_files, temp_files):
    """Enforce the Creative Tonie duration limit.

    A single file longer than the limit is replaced with a truncated copy. A set of
    several files is never truncated - the total is only reported as a warning, since
    picking which file to cut is the user's call.

    Records each file's duration on the AudioTitle and appends any temporary file it
    creates to temp_files, for cleanup.

    Raises RuntimeError if a single file needs truncating but cannot be truncated. The
    Tonie service enforces the limit strictly, and update_tonie clears a Tonie's existing
    chapters before uploading - so proceeding with an over-length file would wipe the
    Tonie's content and then fail. Better to stop before anything is touched.
    """
    if args.no_duration_limit:
        logging.debug("Duration limit checking is disabled")
        return

    max_seconds = args.max_duration * 60

    if not check_ffmpeg():
        logging.warning(f"ffmpeg not found at '{args.ffmpeg_path}' - skipping the "
                        f"{args.max_duration:g} minute duration check")
        return

    for audio_file in audio_files:
        audio_file.duration = get_audio_duration(audio_file.filepath)
        if audio_file.duration is None:
            logging.warning(f"Could not determine the duration of "
                            f"{os.path.basename(audio_file.filepath)} - it is excluded "
                            f"from the duration check")

    # Single file over the limit: truncate a copy of it
    if len(audio_files) == 1:
        audio_file = audio_files[0]

        if audio_file.duration is None or audio_file.duration <= max_seconds:
            return

        logging.info(f"'{audio_file.title}' runs {format_duration(audio_file.duration)}, "
                     f"over the {args.max_duration:g} minute limit - truncating to "
                     f"{format_duration(max_seconds)}")

        capped_path = cap_audio_file(audio_file, max_seconds, temp_files)

        if capped_path is None:
            raise RuntimeError(
                f"'{audio_file.title}' runs {format_duration(audio_file.duration)} and "
                f"could not be truncated to the {args.max_duration:g} minute limit. "
                f"Stopping before any Creative Tonie is modified - uploading it would "
                f"clear the Tonie's chapters and then be rejected. Shorten the file "
                f"yourself, or pass --no-duration-limit to upload it unchanged."
            )

        audio_file.filepath = capped_path
        audio_file.duration = get_audio_duration(capped_path)
        audio_file.is_capped = True

        measured = (f" - runs {format_duration(audio_file.duration)}"
                    if audio_file.duration is not None else "")
        logging.info(f"Truncated copy written to {capped_path}{measured} "
                     f"(original left untouched)")
        return

    # Several files over the limit: warn only, never truncate
    known_durations = [af.duration for af in audio_files if af.duration is not None]
    if known_durations:
        total = sum(known_durations)
        if total > max_seconds:
            over = total - max_seconds
            logging.warning("=" * 70)
            logging.warning(f"{len(audio_files)} files total {format_duration(total)}, which is "
                            f"{format_duration(over)} over the {args.max_duration:g} minute "
                            f"Creative Tonie limit")
            logging.warning("Sets of several files are never truncated - remove or shorten "
                            "files yourself. Uploading as is will clear the Tonie's "
                            "existing chapters and then be rejected.")
            logging.warning("=" * 70)

def cleanup_converted_files():
    """Clean up temporary converted files"""
    global _converted_files
    if not args.keep_converted and '_converted_files' in globals():
        for file_path in _converted_files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logging.debug(f"Cleaned up converted file: {file_path}")
            except Exception as e:
                logging.warning(f"Failed to clean up {file_path}: {e}")
        
        # Clean up any temp directories we created that are now empty
        # (truncated copies can live in a different directory than converted files)
        for temp_dir in {os.path.dirname(path) for path in _converted_files}:
            try:
                if (temp_dir.startswith(tempfile.gettempdir())
                        and os.path.isdir(temp_dir) and not os.listdir(temp_dir)):
                    os.rmdir(temp_dir)
                    logging.debug(f"Cleaned up temp directory: {temp_dir}")
            except Exception as e:
                logging.warning(f"Failed to clean up temp directory {temp_dir}: {e}")

def get_all_creative_tonies(tonie_api):
    """Get all Creative Tonies from all households"""
    all_tonies = []
    tonie_households = {}  # Map tonie ID to household name
    households = tonie_api.get_households()
    
    for household in households:
        creative_tonies = tonie_api.get_all_creative_tonies_by_household(household)
        for tonie in creative_tonies:
            all_tonies.append(tonie)
            tonie_households[tonie.id] = household.name
    
    return all_tonies, tonie_households

def normalize_title(title):
    """Normalize a title for comparison"""
    if title is None:
        return ""
    # Strip whitespace, convert to lowercase for comparison
    return str(title).strip().lower()

def needs_update(tonie, audio_files, force_update=False):
    """Check if a tonie needs updating"""
    if force_update:
        return True, "Force update requested"
    
    if not getattr(tonie, 'chapters', None):
        return True, "No chapters on tonie"
    
    if len(audio_files) != len(tonie.chapters):
        return True, f"Different number of files ({len(audio_files)} vs {len(tonie.chapters)} chapters)"
    
    # Compare in order: a Tonie plays its chapters in the order they are stored, so a
    # reordering is a real difference even when the same files are present
    audio_titles = [normalize_title(af.title) for af in audio_files]
    tonie_titles = [normalize_title(getattr(chapter, 'title', None))
                    for chapter in tonie.chapters]
    
    # Debug logging
    logging.debug(f"Audio titles (normalized): {audio_titles}")
    logging.debug(f"Tonie titles (normalized): {tonie_titles}")
    
    if audio_titles == tonie_titles:
        return False, "Up to date"
    
    if sorted(audio_titles) == sorted(tonie_titles):
        return True, "Same files in a different order"
    
    # Report the titles as written rather than as normalized for comparison
    audio_originals = {normalize_title(af.title): af.title for af in audio_files}
    tonie_originals = {normalize_title(getattr(chapter, 'title', None)):
                       getattr(chapter, 'title', 'Untitled')
                       for chapter in tonie.chapters}
    
    # Counters rather than sets, so a title appearing a different number of times counts
    audio_counts = Counter(audio_titles)
    tonie_counts = Counter(tonie_titles)
    
    missing_in_tonie = audio_counts - tonie_counts
    extra_in_tonie = tonie_counts - audio_counts
    
    if missing_in_tonie:
        names = [audio_originals.get(t, t) for t in sorted(missing_in_tonie.elements())]
        return True, f"Missing audio files on tonie: {names[:3]}"
    if extra_in_tonie:
        names = [tonie_originals.get(t, t) for t in sorted(extra_in_tonie.elements())]
        return True, f"Extra chapters on tonie: {names[:3]}"
    return True, "Title mismatch detected"

def select_tonies_by_name(tonies, tonie_households):
    """Pick the Tonie to update without the menu, for --non-interactive runs.

    Updating clears a Tonie's chapters, so this never guesses. Without --tonie it
    only proceeds when there is exactly one Tonie it could mean.
    """
    if not args.tonie_name:
        if len(tonies) == 1:
            logging.info(f"Non-interactive mode: '{tonies[0].name}' is the only "
                         f"Creative Tonie on the account")
            return [tonies[0]]

        available = ", ".join(sorted(t.name for t in tonies))
        raise ValueError(
            f"--non-interactive needs --tonie NAME when the account holds more than one "
            f"Creative Tonie, since updating clears the one it picks. "
            f"Available: {available}"
        )

    wanted = normalize_title(args.tonie_name)
    matches = [t for t in tonies if normalize_title(t.name) == wanted]

    if not matches:
        available = ", ".join(sorted(t.name for t in tonies))
        raise ValueError(f"No Creative Tonie named '{args.tonie_name}'. "
                         f"Available: {available}")

    if len(matches) > 1:
        households = ", ".join(sorted(tonie_households.get(t.id, 'Unknown')
                                      for t in matches))
        raise ValueError(f"'{args.tonie_name}' is ambiguous - {len(matches)} Creative "
                         f"Tonies share that name, in these households: {households}")

    logging.info(f"Non-interactive mode: updating '{matches[0].name}'")
    return matches

def display_tonies_menu(tonies, tonie_households, audio_files):
    """Display interactive menu for selecting tonies"""
    print("\n" + "="*70)
    print("CREATIVE TONIES SELECTION")
    print("="*70)
    
    if not tonies:
        print("No Creative Tonies found in your account!")
        return []
    
    print(f"Found {len(audio_files)} audio files to upload:")
    
    # Show converted vs original files
    converted_count = sum(1 for af in audio_files if af.is_converted)
    if converted_count > 0:
        print(f"  - {len(audio_files) - converted_count} original audio files")
        print(f"  - {converted_count} converted from video files")
        if args.trim_silence:
            print(f"  - Silence trimming enabled for converted files")
    
    for i, audio in enumerate(audio_files[:5], 1):  # Show first 5 files
        status = " (converted)" if audio.is_converted else ""
        print(f"  {i}. {audio.title}{status}")
    if len(audio_files) > 5:
        print(f"  ... and {len(audio_files) - 5} more files")
    
    print(f"\nAvailable Creative Tonies:")
    print("-" * 70)
    
    # Display tonies with status
    for i, tonie in enumerate(tonies, 1):
        chapter_count = len(tonie.chapters) if hasattr(tonie, 'chapters') and tonie.chapters else 0
        needs_update_result, reason = needs_update(tonie, audio_files, args.force_update)
        status = "⚠️  NEEDS UPDATE" if needs_update_result else "✅ UP TO DATE"
        household = tonie_households.get(tonie.id, 'Unknown')
        
        print(f"{i:2d}. {tonie.name}")
        print(f"    Household: {household}")
        print(f"    Current: {chapter_count} chapters | Status: {status}")
        if needs_update_result:
            print(f"    Reason: {reason}")
        
        # Debug: Show first few chapter titles
        if hasattr(tonie, 'chapters') and tonie.chapters and chapter_count > 0:
            chapter_titles = [getattr(ch, 'title', 'No title') for ch in tonie.chapters[:3]]
            print(f"    Sample chapters: {chapter_titles}")
        print()
    
    print("-" * 70)
    print("Options:")
    print("  Enter numbers (e.g., '1,3,5' or '1-3' or '1 3 5')")
    print("  'a' or 'all' - Select all tonies")
    print("  'u' or 'update' - Select only tonies that need updates")
    print("  'q' or 'quit' - Exit")
    print("-" * 70)
    
    while True:
        try:
            choice = input("Select tonies to update: ").strip().lower()
            
            if choice in ['q', 'quit', 'exit']:
                print("Exiting...")
                cleanup_converted_files()
                sys.exit(0)
            
            if choice in ['a', 'all']:
                return tonies
            
            if choice in ['u', 'update']:
                return [tonie for tonie in tonies if needs_update(tonie, audio_files, args.force_update)[0]]
            
            # Parse number selections
            selected_indices = set()
            
            # Handle comma-separated, space-separated, and ranges
            parts = choice.replace(',', ' ').split()
            
            for part in parts:
                if '-' in part and len(part.split('-')) == 2:
                    # Handle ranges like 1-3
                    start, end = part.split('-')
                    start, end = int(start.strip()), int(end.strip())
                    selected_indices.update(range(start, end + 1))
                else:
                    # Handle individual numbers
                    selected_indices.add(int(part.strip()))
            
            # Validate selections
            invalid_selections = [i for i in selected_indices if i < 1 or i > len(tonies)]
            if invalid_selections:
                print(f"Invalid selections: {invalid_selections}. Please choose numbers between 1 and {len(tonies)}")
                continue
            
            # Return selected tonies
            selected_tonies = [tonies[i-1] for i in sorted(selected_indices)]
            
            if not selected_tonies:
                print("No tonies selected. Please make a selection.")
                continue
            
            return selected_tonies
            
        except ValueError:
            print("Invalid input. Please enter numbers, ranges, or valid commands.")
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            cleanup_converted_files()
            sys.exit(0)

def confirm_selection(selected_tonies, tonie_households, audio_files, dry_run=False):
    """Confirm the selection before proceeding"""
    print("\n" + "="*70)
    print("CONFIRMATION")
    print("="*70)
    
    action = "DRY RUN - Preview changes for" if dry_run else "Update"
    converted_count = sum(1 for af in audio_files if af.is_converted)
    
    capped_count = sum(1 for af in audio_files if af.is_capped)

    print(f"{action} the following Creative Tonies with {len(audio_files)} audio files")
    if converted_count > 0:
        print(f"({converted_count} converted from video):")
    else:
        print(":")
    if capped_count > 0:
        print(f"({capped_count} truncated to the {args.max_duration:g} minute limit)")
    print()

    known_durations = [af.duration for af in audio_files if af.duration is not None]
    if known_durations:
        total = sum(known_durations)
        if len(known_durations) == len(audio_files):
            print(f"Total runtime: {format_duration(total)}")
        else:
            print(f"Total runtime: {format_duration(total)} "
                  f"({len(known_durations)} of {len(audio_files)} files measured)")

        if not args.no_duration_limit and total > args.max_duration * 60:
            over = total - args.max_duration * 60
            print()
            print("!" * 70)
            print(f"WARNING: total runtime is {format_duration(over)} over the "
                  f"{args.max_duration:g} minute Creative Tonie limit.")
            print("         The upload will likely fail. Remove or shorten files first.")
            print("!" * 70)
        print()
    
    for i, tonie in enumerate(selected_tonies, 1):
        chapter_count = len(tonie.chapters) if hasattr(tonie, 'chapters') and tonie.chapters else 0
        household = tonie_households.get(tonie.id, 'Unknown')
        print(f"{i}. {tonie.name} (Household: {household})")
        print(f"   Current: {chapter_count} chapters")
    
    print("-" * 70)
    
    while True:
        try:
            confirm = input(f"Proceed with {'dry run' if dry_run else 'update'}? (y/n): ").strip().lower()
            if confirm in ['y', 'yes']:
                return True
            elif confirm in ['n', 'no']:
                return False
            else:
                print("Please enter 'y' for yes or 'n' for no.")
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            cleanup_converted_files()
            sys.exit(0)

def describe_audio_file(audio_file):
    """Build the parenthetical status shown next to a file while uploading"""
    notes = []
    if audio_file.is_converted:
        notes.append("converted from video")
    if audio_file.is_capped:
        notes.append(f"truncated to {args.max_duration:g} min")
    return f" ({', '.join(notes)})" if notes else ""

def existing_chapter_titles(tonie):
    """The chapter titles currently on a Tonie, for the record kept before clearing"""
    if not getattr(tonie, 'chapters', None):
        return []
    return [getattr(chapter, 'title', 'Untitled') for chapter in tonie.chapters]

def upload_with_retries(tonie_api, tonie, audio_file):
    """Upload one file, retrying a transient failure.

    A Tonie's chapters have already been cleared by the time uploading starts - the
    90 minute limit is on a Tonie's total content, so new audio cannot be added
    alongside the old and the clear cannot be deferred. That makes a dropped
    connection mid-upload expensive, so it is worth a few attempts.
    """
    attempts = max(1, args.upload_retries)
    delay = args.retry_delay

    for attempt in range(1, attempts + 1):
        try:
            tonie_api.upload_file_to_tonie(tonie, audio_file.filepath, audio_file.title)
            return
        except Exception as e:
            if attempt == attempts:
                logging.error(f"Giving up on '{audio_file.title}' after {attempts} "
                              f"attempts: {e}")
                raise

            logging.warning(f"Upload of '{audio_file.title}' failed "
                            f"(attempt {attempt}/{attempts}): {e}")
            if delay > 0:
                logging.info(f"Retrying in {delay:g}s")
                time.sleep(delay)
            delay *= 2

def update_tonie(tonie_api, tonie, tonie_households, audio_files, dry_run=False):
    """Update a single Creative Tonie with audio files"""
    household = tonie_households.get(tonie.id, 'Unknown')
    logging.info(f"{'[DRY RUN] ' if dry_run else ''}Updating '{tonie.name}' (Household: {household}) with {len(audio_files)} files")
    
    if not dry_run:
        # Record what is on the Tonie before it goes. Clearing is unavoidable, so if the
        # upload then fails this log is the only way to know what was lost.
        previous_titles = existing_chapter_titles(tonie)
        if previous_titles:
            logging.info(f"'{tonie.name}' currently holds {len(previous_titles)} "
                         f"chapters, about to be replaced: {previous_titles}")

        # Clear existing chapters
        logging.info(f"Clearing all chapters from '{tonie.name}'")
        tonie_api.clear_all_chapter_of_tonie(tonie)
        
        # Upload new files
        for i, audio_file in enumerate(audio_files, 1):
            status = describe_audio_file(audio_file)
            logging.info(f"Uploading ({i}/{len(audio_files)}): {audio_file.title}{status}")
            try:
                upload_with_retries(tonie_api, tonie, audio_file)
            except Exception:
                logging.error(f"'{tonie.name}' is now incomplete: {i - 1} of "
                              f"{len(audio_files)} files uploaded")
                if previous_titles:
                    logging.error(f"These chapters were cleared and are no longer on "
                                  f"'{tonie.name}': {previous_titles}")
                raise
        
        # After upload, refresh the tonie data to get updated chapters
        try:
            # Refresh tonie data by getting it again from API
            households = tonie_api.get_households()
            for household in households:
                creative_tonies = tonie_api.get_all_creative_tonies_by_household(household)
                for updated_tonie in creative_tonies:
                    if updated_tonie.id == tonie.id:
                        # Copy updated chapters back to original tonie object
                        tonie.chapters = updated_tonie.chapters
                        break
        except Exception as e:
            logging.warning(f"Could not refresh tonie data after upload: {e}")
    else:
        for i, audio_file in enumerate(audio_files, 1):
            status = describe_audio_file(audio_file)
            logging.info(f"[DRY RUN] Would upload ({i}/{len(audio_files)}): {audio_file.title}{status}")
    
    logging.info(f"{'[DRY RUN] ' if dry_run else ''}Successfully updated '{tonie.name}'")

def main(argv=None):
    parse_args(argv)
    setup_logging()

    try:
        # Validate input path
        if not os.path.exists(args.input_path):
            raise FileNotFoundError(f"Input path does not exist: {args.input_path}")
        
        username, password = resolve_credentials(args)

        # Imported here so the module can be imported without the dependency installed
        from tonie_api.api import TonieAPI

        # Initialize Tonie API
        print("Connecting to Tonie API...")
        tonie_api = TonieAPI(username, password)
        
        # Get audio files
        print(f"Scanning for audio files in: {args.input_path}")
        if args.convert_video:
            print("Video conversion is enabled - will convert MKV, MP4, AVI, MOV files to MP3")
        else:
            print("Will auto-enable video conversion if no audio files are found")
        
        audio_files = get_audio_files(args.input_path)
        converted_count = sum(1 for af in audio_files if af.is_converted)
        
        print(f"Found {len(audio_files)} audio files")
        if converted_count > 0:
            print(f"  - {len(audio_files) - converted_count} original audio files")
            print(f"  - {converted_count} converted from video files")
            if not args.convert_video:
                print("  (Video conversion was automatically enabled)")
        elif args.convert_video:
            print("  (Video conversion was manually enabled but no video files were found)")

        capped_count = sum(1 for af in audio_files if af.is_capped)
        if capped_count > 0:
            print(f"  - {capped_count} truncated to the {args.max_duration:g} minute limit")
        
        # Get all Creative Tonies
        print("Fetching Creative Tonies...")
        all_tonies, tonie_households = get_all_creative_tonies(tonie_api)
        
        if not all_tonies:
            print("No Creative Tonies found in your account!")
            cleanup_converted_files()
            sys.exit(1)
        
        # Interactive or non-interactive mode
        if args.non_interactive:
            selected_tonies = select_tonies_by_name(all_tonies, tonie_households)
        else:
            # Interactive mode
            selected_tonies = display_tonies_menu(all_tonies, tonie_households, audio_files)
            
            if not selected_tonies:
                print("No tonies selected. Exiting.")
                cleanup_converted_files()
                sys.exit(0)
            
            # Confirm selection
            if not confirm_selection(selected_tonies, tonie_households, audio_files, args.dry_run):
                print("Operation cancelled.")
                cleanup_converted_files()
                sys.exit(0)
        
        # Check which tonies need updates
        updates_needed = []
        for tonie in selected_tonies:
            needs_update_result, reason = needs_update(tonie, audio_files, args.force_update)
            if needs_update_result:
                updates_needed.append((tonie, reason))
            else:
                if not args.non_interactive:
                    logging.info(f"'{tonie.name}' is already up to date")
        
        if not updates_needed and not args.force_update:
            print("\n" + "="*70)
            print("All selected Creative Tonies are already up to date!")
            print("Use --force-update to update anyway.")
            print("="*70)
            cleanup_converted_files()
            return
        
        # Perform updates
        print("\n" + "="*70)
        print(f"{'DRY RUN - PREVIEW' if args.dry_run else 'STARTING UPDATES'}")
        print("="*70)
        
        successful_updates = 0
        for i, (tonie, reason) in enumerate(updates_needed, 1):
            try:
                print(f"\n[{i}/{len(updates_needed)}] Processing '{tonie.name}'...")
                logging.info(f"Update reason: {reason}")
                update_tonie(tonie_api, tonie, tonie_households, audio_files, args.dry_run)
                successful_updates += 1
            except Exception as e:
                logging.error(f"Failed to update '{tonie.name}': {e}")
                continue
        
        print("\n" + "="*70)
        if not args.dry_run:
            print(f"UPDATES COMPLETED: {successful_updates}/{len(updates_needed)} successful")
        else:
            print(f"DRY RUN COMPLETED: {successful_updates}/{len(updates_needed)} tonies would be updated")
        print("="*70)
        
        # Clean up converted files
        cleanup_converted_files()
        
    except Exception as ex:
        logging.error(f"Error: {ex}", exc_info=True)
        cleanup_converted_files()
        sys.exit(1)

if __name__ == '__main__':
    main()
