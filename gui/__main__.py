"""python -m gui

Fixes PATH before anything else runs. A .app launched by double-clicking in Finder, from
Launchpad, or via `open` is started by launchd with a minimal PATH -
/usr/bin:/bin:/usr/sbin:/sbin - which does not include Homebrew's or MacPorts' install
locations. tony.check_ffmpeg() and tony.check_ytdlp() both resolve their tool through a
bare subprocess call that relies on PATH, so under that restricted PATH they report an
installed tool as missing. Run from an interactive shell - the CLI's only use case - this
problem does not exist, since a shell's PATH already includes wherever the user's package
manager put things; it is specific to how macOS launches GUI apps.
"""
import os
import sys

# The three real locations FFmpeg or yt-dlp are installed to on macOS: Homebrew on
# Apple Silicon, Homebrew on Intel, and MacPorts. Order does not matter here since these
# are only ever appended, never given priority over whatever PATH already contains.
DEFAULT_CANDIDATES = [
    "/opt/homebrew/bin", "/opt/homebrew/sbin",
    "/usr/local/bin", "/usr/local/sbin",
    "/opt/local/bin", "/opt/local/sbin",
]


def augment_path(current=None, candidates=None):
    """Return current with any missing candidate directories appended.

    Existing entries always come first and keep their order, so anything the user has
    already configured continues to take priority. A candidate already present is never
    duplicated.
    """
    if current is None:
        current = os.environ.get("PATH", "")
    if candidates is None:
        candidates = DEFAULT_CANDIDATES

    entries = current.split(":") if current else []
    existing = set(entries)

    for candidate in candidates:
        if candidate not in existing:
            entries.append(candidate)
            existing.add(candidate)

    return ":".join(entries)


os.environ["PATH"] = augment_path()

from gui.app import main  # noqa: E402  (import after the PATH fix, deliberately)

if __name__ == "__main__":
    sys.exit(main())
