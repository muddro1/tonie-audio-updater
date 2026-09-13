"""Telling the user which external tool is missing, and what it costs them."""
import pytest

pytest.importorskip("PySide6")

import tony
from gui.app import MainWindow


@pytest.fixture
def window(qtbot, monkeypatch, configure):
    configure()
    monkeypatch.setattr("gui.app.signin.load_saved", lambda: ("me@example.com", "pw"))
    w = MainWindow()
    qtbot.addWidget(w)
    return w


def test_no_banner_when_both_tools_are_present(window, monkeypatch):
    monkeypatch.setattr(tony, "check_ffmpeg", lambda: True)
    monkeypatch.setattr(tony, "check_ytdlp", lambda: True)

    window.refresh_banner()

    assert window.tool_warnings() == []
    assert window.banner.isVisible() is False


def test_missing_ffmpeg_is_named_with_its_install_command(window, monkeypatch):
    monkeypatch.setattr(tony, "check_ffmpeg", lambda: False)
    monkeypatch.setattr(tony, "check_ytdlp", lambda: True)

    window.refresh_banner()

    assert "brew install ffmpeg" in window.banner_text()
    assert "video" in window.banner_text().lower()


def test_missing_ffmpeg_also_disables_links(window, monkeypatch):
    """yt-dlp needs ffmpeg, so say so rather than failing later for an odd reason."""
    monkeypatch.setattr(tony, "check_ffmpeg", lambda: False)
    monkeypatch.setattr(tony, "check_ytdlp", lambda: True)

    window.refresh_banner()

    assert "link" in window.banner_text().lower()


def test_missing_ytdlp_is_named_without_blaming_ffmpeg(window, monkeypatch):
    monkeypatch.setattr(tony, "check_ffmpeg", lambda: True)
    monkeypatch.setattr(tony, "check_ytdlp", lambda: False)

    window.refresh_banner()

    assert "brew install yt-dlp" in window.banner_text()
    assert "ffmpeg" not in window.banner_text().lower()


def test_both_missing_lists_both(window, monkeypatch):
    monkeypatch.setattr(tony, "check_ffmpeg", lambda: False)
    monkeypatch.setattr(tony, "check_ytdlp", lambda: False)

    window.refresh_banner()

    assert len(window.tool_warnings()) == 2


def test_a_missing_tool_never_disables_uploading_plain_audio(window, monkeypatch):
    """Files and folders still work; only what needs the tool is unavailable."""
    from gui.sources import SourceItem

    monkeypatch.setattr(tony, "check_ffmpeg", lambda: False)
    monkeypatch.setattr(tony, "check_ytdlp", lambda: False)
    window.refresh_banner()

    window.sources.append(SourceItem(kind="file", value="/a.mp3", title="a",
                                     duration=10.0))
    window.refresh_summary()

    assert window.isEnabled() is True
