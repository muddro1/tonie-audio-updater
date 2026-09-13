import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tony  # noqa: E402

FFMPEG = shutil.which("ffmpeg")

requires_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")


@pytest.fixture
def configure(tmp_path):
    """Set tony's module-level args, the way main() does.

    Returns a callable taking extra command-line arguments. The required options are
    filled in, with the input path defaulting to a fresh tmp_path.
    """
    def _configure(*extra, input_path=None):
        return tony.parse_args([
            "-u", "user",
            "-p", "pass",
            "-i", str(input_path if input_path is not None else tmp_path),
            *extra,
        ])

    yield _configure
    tony.args = None


@pytest.fixture
def tone_file(tmp_path):
    """Write a real audio file of a given length, for the ffmpeg-backed tests."""
    def _tone(seconds, name="tone.mp3", frequency=440, directory=None):
        target = Path(directory if directory is not None else tmp_path) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        codec = {".mp3": "libmp3lame", ".wav": "pcm_s16le", ".m4a": "aac"}[target.suffix]
        subprocess.run(
            [FFMPEG, "-loglevel", "error",
             "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={seconds}",
             "-c:a", codec, "-b:a", "32k", "-y", str(target)],
            check=True, capture_output=True,
        )
        return target

    return _tone


@pytest.fixture(autouse=True)
def reset_converted_files():
    """Keep the cleanup global from leaking between tests."""
    yield
    tony._converted_files = []
