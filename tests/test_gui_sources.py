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


def test_a_failed_link_is_skipped_but_a_good_source_still_resolves():
    good = SourceItem(kind="file", value="/music/good.mp3", title="good", selected=True)
    bad = SourceItem(kind="link", value="https://example.com/private", title="private",
                      selected=True, error="Could not read: Private video")

    assert resolved_paths([good, bad]) == ["/music/good.mp3"]

    count, seconds = totals([good, bad])
    assert count == 1


def test_a_failed_link_stays_in_the_list_with_its_reason():
    bad = SourceItem(kind="link", value="https://example.com/private", title="private",
                      selected=True, error="Could not read: Private video")

    assert [bad][0].error == "Could not read: Private video"
    assert resolved_paths([bad]) == []


def test_an_empty_ticked_folder_contributes_nothing():
    folder = SourceItem(kind="folder", value="/empty", title="empty", selected=True)
    folder.children = []

    assert resolved_paths([folder]) == []
    assert totals([folder]) == (0, 0.0)


def test_a_folder_with_children_still_resolves_them():
    folder = SourceItem(kind="folder", value="/music", title="music")
    folder.children = [
        SourceItem(kind="file", value="/music/a.mp3", title="a", duration=10.0,
                   selected=True),
        SourceItem(kind="file", value="/music/b.mp3", title="b", duration=20.0,
                   selected=True),
    ]

    assert resolved_paths([folder]) == ["/music/a.mp3", "/music/b.mp3"]
    assert totals([folder]) == (2, 30.0)


def test_a_link_that_probes_to_nothing_gets_an_error(configure, monkeypatch):
    configure()
    monkeypatch.setattr(tony, "probe_url", lambda url: [])

    item = expand("https://example.com/playlist?list=all-deleted")

    assert item.error is not None
    assert item.children == []
    assert resolved_paths([item]) == []
    count, seconds = totals([item])
    assert count == 0
    assert seconds == 0.0


# --------------------------------------------------------------- duplicate sources

def test_the_same_file_added_twice_resolves_once(configure, tmp_path):
    """The engine dedupes by realpath, so the preview must too - or the confirmation
    dialog promises a file count the upload will not honor."""
    path = tmp_path / "once.mp3"
    path.write_bytes(b"")
    configure()

    first = SourceItem(kind="file", value=str(path), title="once", duration=10.0)
    second = SourceItem(kind="file", value=str(path), title="once", duration=10.0)

    assert resolved_paths([first, second]) == [str(path)]
    assert totals([first, second]) == (1, 10.0)


def test_a_file_named_beside_the_folder_holding_it_resolves_once(configure, tmp_path):
    path = tmp_path / "inside.mp3"
    path.write_bytes(b"")
    configure()

    folder = SourceItem(kind="folder", value=str(tmp_path), title=tmp_path.name)
    folder.children = [SourceItem(kind="file", value=str(path), title="inside",
                                  duration=10.0)]
    loose = SourceItem(kind="file", value=str(path), title="inside", duration=10.0)

    assert resolved_paths([folder, loose]) == [str(path)]
    assert totals([folder, loose]) == (1, 10.0)


def test_two_paths_to_the_same_file_resolve_once(configure, tmp_path):
    """Two spellings of one file - the engine resolves both with realpath."""
    path = tmp_path / "once.mp3"
    path.write_bytes(b"")
    indirect = tmp_path / "sub" / ".." / "once.mp3"
    (tmp_path / "sub").mkdir()
    configure()

    first = SourceItem(kind="file", value=str(path), title="once", duration=10.0)
    second = SourceItem(kind="file", value=str(indirect), title="once", duration=10.0)

    assert resolved_paths([first, second]) == [str(path)]
    assert totals([first, second]) == (1, 10.0)


def test_the_same_link_added_twice_resolves_once(configure):
    """A URL is deduped by the address itself, the way collect_input_files does it -
    realpath would mangle it into a path under the working directory."""
    configure()
    first = SourceItem(kind="link", value="https://example.com/1", title="One",
                       duration=60.0)
    second = SourceItem(kind="link", value="https://example.com/1", title="One",
                        duration=60.0)

    assert resolved_paths([first, second]) == ["https://example.com/1"]
    assert totals([first, second]) == (1, 60.0)


def test_different_links_are_both_kept(configure):
    configure()
    first = SourceItem(kind="link", value="https://example.com/1", title="One",
                       duration=60.0)
    second = SourceItem(kind="link", value="https://example.com/2", title="Two",
                        duration=90.0)

    assert resolved_paths([first, second]) == ["https://example.com/1",
                                               "https://example.com/2"]
    assert totals([first, second]) == (2, 150.0)
