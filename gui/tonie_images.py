"""Each Creative Tonie's own picture, fetched once and cached on disk.

The Tonie API returns an imageUrl per Tonie - a photo of the physical figure, and a far
better way to tell "Elephant" from "Lion" at a glance than the name column alone. The
artwork for a given Tonie does not change, so it is fetched once and reused from then on
rather than downloaded on every launch.

Nothing here ever raises. A Tonie with no image, an unreachable URL, or any other failure
just means no icon for that row - never a crashed sign-in.
"""
import logging
from pathlib import Path

import requests

log = logging.getLogger(__name__)


def cache_dir():
    """Where cached Tonie images live, created on first use."""
    path = Path.home() / "Library" / "Caches" / "tonie-audio-updater" / "tonie-images"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cached_path(tonie_id, base_dir=None):
    """The path a cached image for this Tonie would have, whether or not it exists yet."""
    return (base_dir if base_dir is not None else cache_dir()) / f"{tonie_id}.image"


def fetch_and_cache(tonie, base_dir=None):
    """Return the local path to this Tonie's image, fetching and caching it if needed.

    A cache hit costs nothing: the path is returned directly with no network call.
    """
    if not getattr(tonie, "imageUrl", None):
        return None

    path = cached_path(tonie.id, base_dir)
    if path.exists():
        return path

    try:
        response = requests.get(tonie.imageUrl, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        log.debug(f"Could not fetch the image for '{tonie.name}': {e}")
        return None

    # Write beside the destination and rename into place, so a failure partway through
    # the write can never leave a half-downloaded file where fetch_and_cache would
    # mistake it for a good cache hit next time.
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(response.content)
    tmp.rename(path)
    return path


def fetch_all(tonies, base_dir=None):
    """fetch_and_cache for every Tonie, returning {tonie_id: path_or_None}.

    One Tonie's failure never costs the others theirs.
    """
    return {tonie.id: fetch_and_cache(tonie, base_dir) for tonie in tonies}
