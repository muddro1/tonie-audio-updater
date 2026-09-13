"""What the source list holds, and what it contributes before anything is uploaded.

Expanding a source is deliberately cheap: a folder is scanned, a file is probed for its
duration, a link's metadata is read. Nothing is converted, truncated or downloaded until
Upload is pressed, so adding a folder of large videos does not freeze the window.
"""
import os
from dataclasses import dataclass, field
from typing import List, Optional

import tony


@dataclass
class SourceItem:
    """One row in the source list. A folder or link also has tickable children."""
    kind: str                       # "file" | "folder" | "link"
    value: str                      # path or URL, passed to -i when selected
    title: str
    duration: Optional[float] = None
    children: List["SourceItem"] = field(default_factory=list)
    selected: bool = True
    error: Optional[str] = None


def expand(value):
    """Turn a dropped or chosen path or link into a SourceItem, cheaply."""
    if tony.is_url(value):
        return _expand_link(value)
    if os.path.isdir(value):
        return _expand_folder(value)
    return _expand_file(value)


def _expand_file(path):
    return SourceItem(
        kind="file",
        value=path,
        title=os.path.splitext(os.path.basename(path))[0],
        duration=tony.get_audio_duration(path),
    )


def _expand_folder(path):
    item = SourceItem(kind="folder", value=path, title=os.path.basename(path.rstrip("/")))

    found = (tony.find_files(path, tony.AUDIO_EXTENSIONS)
             + tony.find_files(path, tony.VIDEO_EXTENSIONS))

    item.children = [_expand_file(child) for child in sorted(found)]
    return item


def _expand_link(url):
    item = SourceItem(kind="link", value=url, title=url)

    try:
        entries = tony.probe_url(url)
    except Exception as e:
        item.error = str(e)
        return item

    item.children = [
        SourceItem(kind="link", value=entry["url"], title=entry["title"],
                   duration=entry["duration"])
        for entry in entries
    ]

    if len(item.children) == 1:
        item.title = item.children[0].title
    elif item.children:
        item.title = f"{len(item.children)} videos"

    return item


def _leaves(items):
    for item in items:
        if item.children:
            yield from _leaves(item.children)
        elif item.selected:
            yield item


def resolved_paths(items):
    """The -i values for everything currently ticked."""
    return [leaf.value for leaf in _leaves(items)]


def totals(items):
    """(file count, total seconds) for everything currently ticked.

    An unknown duration counts toward the file count but contributes no time, so the
    total reads as a floor rather than silently pretending to be exact.
    """
    leaves = list(_leaves(items))
    seconds = sum(leaf.duration for leaf in leaves if leaf.duration is not None)
    return len(leaves), seconds
