#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import json
import os
import sys
import glob
import tempfile
import subprocess
from pathlib import Path
from argparse import ArgumentParser
from dataclasses import dataclass

from tonie_api.api import TonieAPI
from tonie_api.models import Config, CreativeTonie, User

@dataclass(eq=False)
class AudioTitle:
    filepath: str
    title: str
    is_converted: bool = False  # Track if this was converted from video
    
    def __eq__(self, other):
        return self.title == other.title    

usage = f"""
Tonie Audio Updater - Upload audio files to Creative Tonies

Python {sys.version}
Usage: {os.path.basename(__file__)} [options]
"""

parser = ArgumentParser(usage=usage)
parser.add_argument("-u", "--username", dest="username", required=True, 
                    help="Tonie account username")
parser.add_argument("-p", "--password", dest="password", required=True, 
                    help="Tonie account password")
parser.add_argument("-i", "--input-path", dest="input_path", required=True, 
                    help="Path to directory containing audio files (MP3, WAV, M4A, OGG) and optionally video files")
parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="Show what would be done without actually updating")
parser.add_argument("--non-interactive", dest="non_interactive", action="store_true",
                    help="Run in non-interactive mode (updates first tonie)")
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

args = parser.parse_args()

# Setup logger
logging.basicConfig(stream=sys.stdout, level=logging.INFO, 
                   format='%(asctime)s | %(levelname)s | %(message)s')

def check_ffmpeg():
    """Check if ffmpeg is available"""
    try:
        subprocess.run([args.ffmpeg_path, "-version"], 
                      capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

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
    """Convert video file to MP3 using ffmpeg"""
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
    
    # Support multiple audio formats
    audio_extensions = ['*.mp3', '*.wav', '*.m4a', '*.ogg']
    video_extensions = ['*.mkv', '*.mp4', '*.avi', '*.mov', '*.wmv', '*.flv']
    
    # Get audio files first
    for extension in audio_extensions:
        for audio_file in glob.glob(os.path.join(input_path, extension)):
            title = os.path.splitext(os.path.basename(audio_file))[0]
            # Truncate title to 100 characters
            title = truncate_title(title, 100)
            audio_files.append(AudioTitle(filepath=audio_file, title=title))
    
    # Check if we need to auto-enable video conversion
    auto_convert_video = False
    if not audio_files and not args.convert_video:
        # No audio files found, check if there are video files
        video_files = []
        for extension in video_extensions:
            video_files.extend(glob.glob(os.path.join(input_path, extension)))
        
        if video_files:
            logging.info(f"No audio files found, but found {len(video_files)} video files")
            logging.info("Automatically enabling video conversion...")
            auto_convert_video = True
    
    # Handle video files if conversion is enabled (manually or automatically)
    if args.convert_video or auto_convert_video:
        if not check_ffmpeg():
            logging.error(f"ffmpeg not found at '{args.ffmpeg_path}'. Please install ffmpeg or specify correct path with --ffmpeg-path")
            raise FileNotFoundError("ffmpeg is required for video conversion")
        
        video_files = []
        for extension in video_extensions:
            video_files.extend(glob.glob(os.path.join(input_path, extension)))
        
        if video_files:
            if auto_convert_video:
                logging.info(f"Auto-converting {len(video_files)} video files to audio")
            else:
                logging.info(f"Found {len(video_files)} video files to convert")
            
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
    
    # Store converted files list for cleanup
    global _converted_files
    _converted_files = converted_files
    
    return audio_files

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
        
        # Clean up temp directory if empty
        if _converted_files:
            temp_dir = os.path.dirname(_converted_files[0])
            try:
                if temp_dir.startswith(tempfile.gettempdir()) and not os.listdir(temp_dir):
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
    
    if not hasattr(tonie, 'chapters') or not tonie.chapters:
        return True, "No chapters on tonie"
    
    if len(audio_files) != len(tonie.chapters):
        return True, f"Different number of files ({len(audio_files)} vs {len(tonie.chapters)} chapters)"
    
    # Normalize titles for comparison
    audio_titles = [normalize_title(af.title) for af in audio_files]
    tonie_titles = [normalize_title(chapter.title) if hasattr(chapter, 'title') else "" for chapter in tonie.chapters]
    
    # Sort both lists for comparison (in case order doesn't matter)
    audio_titles_sorted = sorted(audio_titles)
    tonie_titles_sorted = sorted(tonie_titles)
    
    # Debug logging
    logging.debug(f"Audio titles (normalized): {audio_titles_sorted}")
    logging.debug(f"Tonie titles (normalized): {tonie_titles_sorted}")
    
    if audio_titles_sorted != tonie_titles_sorted:
        # Find differences
        missing_in_tonie = set(audio_titles_sorted) - set(tonie_titles_sorted)
        extra_in_tonie = set(tonie_titles_sorted) - set(audio_titles_sorted)
        
        if missing_in_tonie:
            return True, f"Missing audio files on tonie: {list(missing_in_tonie)[:3]}"
        if extra_in_tonie:
            return True, f"Extra chapters on tonie: {list(extra_in_tonie)[:3]}"
        return True, "Title mismatch detected"
    
    return False, "Up to date"

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
        except KeyboardInterrupt:
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
    
    print(f"{action} the following Creative Tonies with {len(audio_files)} audio files")
    if converted_count > 0:
        print(f"({converted_count} converted from video):")
    else:
        print(":")
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
        except KeyboardInterrupt:
            print("\nExiting...")
            cleanup_converted_files()
            sys.exit(0)

def update_tonie(tonie_api, tonie, tonie_households, audio_files, dry_run=False):
    """Update a single Creative Tonie with audio files"""
    household = tonie_households.get(tonie.id, 'Unknown')
    logging.info(f"{'[DRY RUN] ' if dry_run else ''}Updating '{tonie.name}' (Household: {household}) with {len(audio_files)} files")
    
    if not dry_run:
        # Clear existing chapters
        logging.info(f"Clearing all chapters from '{tonie.name}'")
        tonie_api.clear_all_chapter_of_tonie(tonie)
        
        # Upload new files
        for i, audio_file in enumerate(audio_files, 1):
            status = " (converted from video)" if audio_file.is_converted else ""
            logging.info(f"Uploading ({i}/{len(audio_files)}): {audio_file.title}{status}")
            tonie_api.upload_file_to_tonie(tonie, audio_file.filepath, audio_file.title)
        
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
            status = " (converted from video)" if audio_file.is_converted else ""
            logging.info(f"[DRY RUN] Would upload ({i}/{len(audio_files)}): {audio_file.title}{status}")
    
    logging.info(f"{'[DRY RUN] ' if dry_run else ''}Successfully updated '{tonie.name}'")

def main():
    try:
        # Validate input path
        if not os.path.exists(args.input_path):
            raise FileNotFoundError(f"Input path does not exist: {args.input_path}")
        
        # Initialize Tonie API
        print("Connecting to Tonie API...")
        tonie_api = TonieAPI(args.username, args.password)
        
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
        
        # Get all Creative Tonies
        print("Fetching Creative Tonies...")
        all_tonies, tonie_households = get_all_creative_tonies(tonie_api)
        
        if not all_tonies:
            print("No Creative Tonies found in your account!")
            cleanup_converted_files()
            sys.exit(1)
        
        # Interactive or non-interactive mode
        if args.non_interactive:
            # Non-interactive: use first tonie (backward compatibility)
            selected_tonies = [all_tonies[0]]
            logging.info(f"Non-interactive mode: updating '{all_tonies[0].name}'")
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