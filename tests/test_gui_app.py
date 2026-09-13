"""The window, driven headless."""
import pytest

pytest.importorskip("PySide6")

import os

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QFileDialog

import tony
from conftest import requires_ffmpeg
from gui.app import MainWindow
from gui.sources import SourceItem


class FakeTonie:
    def __init__(self, tonie_id, name, chapters=()):
        from types import SimpleNamespace
        self.id, self.name = tonie_id, name
        self.chapters = [SimpleNamespace(title=t) for t in chapters]


def _window(qtbot, monkeypatch, synchronous):
    monkeypatch.setattr("gui.app.signin.load_saved", lambda: ("me@example.com", "pw"))
    w = MainWindow(synchronous=synchronous)
    qtbot.addWidget(w)
    w.set_tonies(
        [FakeTonie("t1", "Elephant"), FakeTonie("t2", "Lion", chapters=["One"])],
        {"t1": "Home", "t2": "Attic"},
    )
    return w


@pytest.fixture
def window(qtbot, monkeypatch):
    """Work runs inline, because nothing here spins the event loop a Worker needs."""
    return _window(qtbot, monkeypatch, synchronous=True)


@pytest.fixture
def threaded_window(qtbot, monkeypatch):
    """The window as shipped, with its work on a real Worker thread."""
    return _window(qtbot, monkeypatch, synchronous=False)


def _drop(window, mime):
    """Deliver a drop to the window, the way a drag from Finder or a browser does."""
    event = QDropEvent(QPointF(1, 1), Qt.CopyAction, mime,
                       Qt.LeftButton, Qt.NoModifier)
    window.dropEvent(event)


@requires_ffmpeg
def test_adding_a_folder_updates_the_summary(window, configure, tone_file, tmp_path):
    configure()
    tone_file(30, "a.mp3")
    tone_file(30, "b.mp3", frequency=300)

    window.add_source(str(tmp_path))

    assert "2 files" in window.summary_text()
    assert "0:01:00" in window.summary_text()


@requires_ffmpeg
def test_adding_a_loose_file_and_a_folder_combines_them(window, configure, tone_file,
                                                        tmp_path):
    configure()
    folder = tmp_path / "folder"
    tone_file(10, "inside.mp3", directory=folder)
    loose = tone_file(10, "loose.mp3", frequency=300)

    window.add_source(str(folder))
    window.add_source(str(loose))

    assert "2 files" in window.summary_text()


def test_a_playlist_link_expands_into_tickable_rows(window, configure, monkeypatch):
    configure()
    monkeypatch.setattr(tony, "probe_url", lambda url: [
        {"url": "https://example.com/1", "title": "One", "duration": 600.0},
        {"url": "https://example.com/2", "title": "Two", "duration": 600.0},
    ])

    window.add_source("https://example.com/playlist")

    assert "2 files" in window.summary_text()

    window.sources[0].children[1].selected = False
    window.refresh_summary()

    assert "1 file" in window.summary_text()
    assert "0:10:00" in window.summary_text()


def test_going_over_the_limit_warns(window, configure, monkeypatch):
    configure()
    monkeypatch.setattr(tony, "probe_url", lambda url: [
        {"url": "https://example.com/1", "title": "Long", "duration": 6000.0},
    ])

    window.add_source("https://example.com/x")

    assert window.is_over_limit() is True
    assert "90" in window.summary_text()


def test_a_link_that_fails_is_shown_not_dropped(window, configure, monkeypatch):
    configure()

    def explode(url):
        raise RuntimeError("Private video")

    monkeypatch.setattr(tony, "probe_url", explode)

    window.add_source("https://example.com/private")

    assert len(window.sources) == 1
    assert "Private video" in window.sources[0].error


def test_upload_is_disabled_without_sources_or_tonies(window):
    assert window.upload_button.isEnabled() is False

    window.sources.append(SourceItem(kind="file", value="/a.mp3", title="a",
                                     duration=10.0))
    window.refresh_summary()
    assert window.upload_button.isEnabled() is False

    window.check_tonie("Elephant", True)
    assert window.upload_button.isEnabled() is True


def test_selecting_several_tonies(window):
    window.check_tonie("Elephant", True)
    window.check_tonie("Lion", True)

    assert [t.name for t in window.selected_tonies()] == ["Elephant", "Lion"]


def test_select_needing_update_ticks_only_those(window, configure):
    configure()
    window.sources.append(SourceItem(kind="file", value="/One.mp3", title="One",
                                     duration=10.0))
    window.select_needing_update()

    # Lion already holds a chapter called One, so only Elephant needs it
    assert [t.name for t in window.selected_tonies()] == ["Elephant"]


def test_the_state_reflects_the_advanced_controls(window):
    window.dry_run.setChecked(True)
    window.max_duration.setValue(60.0)

    state = window.current_state()

    assert state.dry_run is True
    assert state.max_duration == 60.0


def test_controls_are_disabled_while_running(window, qtbot):
    window.set_running(True)
    assert window.upload_button.isEnabled() is False
    assert window.add_folder_button.isEnabled() is False
    assert window.cancel_button.isEnabled() is True

    window.set_running(False)
    assert window.add_folder_button.isEnabled() is True
    assert window.cancel_button.isEnabled() is False


@requires_ffmpeg
def test_several_files_chosen_at_once_are_all_expanded(threaded_window, configure,
                                                       tone_file, qtbot, monkeypatch):
    """Threaded, because only a real Worker can be refused by the single-flight lock.

    Run inline, one-Worker-per-file would still complete every file in turn - each
    run() returns before the next begins - so this could not tell a batch from the
    bug it replaced.
    """
    configure()
    chosen = [str(tone_file(5, "a.mp3")),
              str(tone_file(5, "b.mp3", frequency=300)),
              str(tone_file(5, "c.mp3", frequency=600))]
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        staticmethod(lambda *a, **k: (chosen, "")))
    window = threaded_window

    window.choose_files()
    qtbot.waitUntil(lambda: window.add_folder_button.isEnabled(), timeout=10000)

    assert [s.title for s in window.sources] == ["a", "b", "c"]
    assert "3 files" in window.summary_text()


def test_dropping_several_links_expands_them_all(threaded_window, configure, qtbot,
                                                 monkeypatch):
    configure()
    monkeypatch.setattr(tony, "probe_url", lambda url: [
        {"url": url, "title": url.rsplit("/", 1)[-1], "duration": 60.0},
    ])
    window = threaded_window

    mime = QMimeData()
    mime.setText("https://example.com/one\nhttps://example.com/two")
    _drop(window, mime)
    qtbot.waitUntil(lambda: window.add_folder_button.isEnabled(), timeout=10000)

    assert [s.title for s in window.sources] == ["one", "two"]
    assert "2 files" in window.summary_text()


@requires_ffmpeg
def test_dropping_several_files_expands_them_all(threaded_window, configure, tone_file,
                                                 qtbot):
    configure()
    dropped = [tone_file(5, "one.mp3"), tone_file(5, "two.mp3", frequency=300)]
    window = threaded_window

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in dropped])
    _drop(window, mime)
    qtbot.waitUntil(lambda: window.add_folder_button.isEnabled(), timeout=10000)

    assert [s.title for s in window.sources] == ["one", "two"]
    assert "2 files" in window.summary_text()


def test_a_source_expands_on_a_real_worker_thread(threaded_window, configure, qtbot,
                                                  monkeypatch):
    """The path users actually run: dispatched to a Worker, delivered by the loop."""
    configure()
    monkeypatch.setattr(tony, "probe_url", lambda url: [
        {"url": "https://example.com/1", "title": "One", "duration": 600.0},
        {"url": "https://example.com/2", "title": "Two", "duration": 600.0},
    ])
    window = threaded_window

    window.add_sources(["https://example.com/a", "https://example.com/b"])

    # Locked the moment the work is dispatched, before the loop has run at all
    assert window.add_folder_button.isEnabled() is False
    assert window.upload_button.isEnabled() is False
    assert window.cancel_button.isEnabled() is True

    qtbot.waitUntil(lambda: window.add_folder_button.isEnabled(), timeout=10000)

    assert len(window.sources) == 2
    assert "4 files" in window.summary_text()
    assert window.cancel_button.isEnabled() is False


def test_one_unreadable_file_does_not_sink_the_rest_of_the_batch(threaded_window,
                                                                 configure, qtbot,
                                                                 monkeypatch, tmp_path):
    """A batch shares one Worker; it must not share one failure."""
    configure()
    paths = []
    for name in ("a.mp3", "bad.mp3", "c.mp3"):
        path = tmp_path / name
        path.write_bytes(b"")
        paths.append(str(path))

    def duration(path):
        if os.path.basename(path) == "bad.mp3":
            raise RuntimeError("Unreadable file")
        return 10.0

    monkeypatch.setattr(tony, "get_audio_duration", duration)
    window = threaded_window

    window.add_sources(paths)
    qtbot.waitUntil(lambda: window.add_folder_button.isEnabled(), timeout=10000)

    assert [s.title for s in window.sources] == ["a", "bad", "c"]
    assert [s.error for s in window.sources] == [None, "Unreadable file", None]
    # The bad one is shown but contributes nothing to the upload
    assert "2 files" in window.summary_text()
