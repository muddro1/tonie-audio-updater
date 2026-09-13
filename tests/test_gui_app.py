"""The window, driven headless."""
import pytest

pytest.importorskip("PySide6")

import tony
from conftest import requires_ffmpeg
from gui.app import MainWindow
from gui.sources import SourceItem


class FakeTonie:
    def __init__(self, tonie_id, name, chapters=()):
        from types import SimpleNamespace
        self.id, self.name = tonie_id, name
        self.chapters = [SimpleNamespace(title=t) for t in chapters]


@pytest.fixture
def window(qtbot, monkeypatch):
    monkeypatch.setattr("gui.app.signin.load_saved", lambda: ("me@example.com", "pw"))
    w = MainWindow()
    qtbot.addWidget(w)
    w.set_tonies(
        [FakeTonie("t1", "Elephant"), FakeTonie("t2", "Lion", chapters=["One"])],
        {"t1": "Home", "t2": "Attic"},
    )
    return w


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
