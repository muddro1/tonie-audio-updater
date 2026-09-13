"""The source list: what a folder, a file or a link contributes before uploading."""
import pytest

import tony
from conftest import requires_ffmpeg
from gui.sources import SourceItem, expand, resolved_paths, totals


@requires_ffmpeg
def test_a_folder_expands_to_its_files(configure, tone_file, tmp_path):
    tone_file(3, "a.mp3")
    tone_file(4, "b.mp3", frequency=300)
    configure()

    item = expand(str(tmp_path))

    assert item.kind == "folder"
    assert len(item.children) == 2
    assert sorted(c.title for c in item.children) == ["a", "b"]


@requires_ffmpeg
def test_a_file_is_a_leaf_with_its_duration(configure, tone_file):
    target = tone_file(3, "solo.mp3")
    configure()

    item = expand(str(target))

    assert item.kind == "file"
    assert item.children == []
    assert item.duration == pytest.approx(3, abs=0.2)


def test_a_link_expands_to_its_videos(configure, monkeypatch):
    configure()
    monkeypatch.setattr(tony, "probe_url", lambda url: [
        {"url": "https://example.com/1", "title": "One", "duration": 60.0},
        {"url": "https://example.com/2", "title": "Two", "duration": 90.0},
    ])

    item = expand("https://example.com/playlist")

    assert item.kind == "link"
    assert [c.title for c in item.children] == ["One", "Two"]
    assert [c.value for c in item.children] == [
        "https://example.com/1", "https://example.com/2"]


def test_a_single_video_link_is_one_child(configure, monkeypatch):
    configure()
    monkeypatch.setattr(tony, "probe_url", lambda url: [
        {"url": "https://example.com/1", "title": "Only", "duration": 60.0},
    ])

    item = expand("https://example.com/watch?v=1")

    assert len(item.children) == 1
    assert item.children[0].title == "Only"


def test_a_link_that_fails_records_the_reason(configure, monkeypatch):
    configure()

    def explode(url):
        raise RuntimeError("Could not read: Private video")

    monkeypatch.setattr(tony, "probe_url", explode)

    item = expand("https://example.com/private")

    assert item.error is not None
    assert "Private video" in item.error
    assert item.children == []


def test_resolved_paths_takes_only_ticked_children():
    item = SourceItem(kind="link", value="https://example.com/p", title="Playlist")
    item.children = [
        SourceItem(kind="link", value="https://example.com/1", title="One", selected=True),
        SourceItem(kind="link", value="https://example.com/2", title="Two", selected=False),
    ]

    assert resolved_paths([item]) == ["https://example.com/1"]


def test_resolved_paths_across_mixed_sources():
    folder = SourceItem(kind="folder", value="/music", title="music")
    folder.children = [SourceItem(kind="file", value="/music/a.mp3", title="a",
                                  selected=True)]
    loose = SourceItem(kind="file", value="/b.mp3", title="b", selected=True)

    assert resolved_paths([folder, loose]) == ["/music/a.mp3", "/b.mp3"]


def test_an_unticked_leaf_contributes_nothing():
    loose = SourceItem(kind="file", value="/b.mp3", title="b", selected=False)
    assert resolved_paths([loose]) == []


def test_totals_counts_and_sums_ticked_children_only():
    folder = SourceItem(kind="folder", value="/music", title="music")
    folder.children = [
        SourceItem(kind="file", value="/1.mp3", title="1", duration=60.0, selected=True),
        SourceItem(kind="file", value="/2.mp3", title="2", duration=30.0, selected=True),
        SourceItem(kind="file", value="/3.mp3", title="3", duration=99.0, selected=False),
    ]

    assert totals([folder]) == (2, 90.0)


def test_totals_tolerates_an_unknown_duration():
    item = SourceItem(kind="file", value="/1.mp3", title="1", duration=None, selected=True)
    count, seconds = totals([item])
    assert count == 1
    assert seconds == 0.0
