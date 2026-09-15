"""The window, driven headless."""
import pytest

pytest.importorskip("PySide6")

import os
from types import SimpleNamespace

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QFileDialog

import tony
from conftest import requires_ffmpeg
from gui import tonie_images
from gui.app import MainWindow
from gui.sources import SourceItem


class FakeTonie:
    def __init__(self, name, id=None, chapters=()):
        self.name = name
        self.id = id if id is not None else name
        # A str has its own .title() method, so hasattr(c, "title") would wrongly
        # call a plain string "already chapter-shaped" - check isinstance instead.
        self.chapters = [SimpleNamespace(title=c) if isinstance(c, str) else c
                         for c in chapters]
        self.imageUrl = None


def _window(qtbot, monkeypatch, synchronous):
    monkeypatch.setattr("gui.app.signin.load_saved", lambda: ("me@example.com", "pw"))
    w = MainWindow(synchronous=synchronous)
    qtbot.addWidget(w)
    w.set_tonies(
        [FakeTonie("Elephant", id="t1"), FakeTonie("Lion", id="t2", chapters=["One"])],
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


def _select_top_level_rows(window, indices):
    """Select the top-level source rows at these indices, the way a real click-drag
    or Cmd-click selection would - through the tree widget, not the model."""
    tree = window.source_tree
    tree.clearSelection()
    for i in indices:
        tree.topLevelItem(i).setSelected(True)


def test_removing_one_source_leaves_the_others(window):
    window.sources = [
        SourceItem(kind="file", value="/a.mp3", title="a", duration=1.0),
        SourceItem(kind="file", value="/b.mp3", title="b", duration=2.0),
        SourceItem(kind="file", value="/c.mp3", title="c", duration=3.0),
    ]
    window.refresh_summary()
    _select_top_level_rows(window, [1])

    window.remove_selected_source()

    assert [s.title for s in window.sources] == ["a", "c"]


def test_removing_several_selected_sources_at_once(window):
    """The gap this closes: only one source could be removed per click before."""
    window.sources = [
        SourceItem(kind="file", value="/a.mp3", title="a", duration=1.0),
        SourceItem(kind="file", value="/b.mp3", title="b", duration=2.0),
        SourceItem(kind="file", value="/c.mp3", title="c", duration=3.0),
        SourceItem(kind="file", value="/d.mp3", title="d", duration=4.0),
    ]
    window.refresh_summary()
    _select_top_level_rows(window, [0, 2, 3])  # a, c, d - a non-contiguous selection

    window.remove_selected_source()

    assert [s.title for s in window.sources] == ["b"]


def test_the_tree_actually_allows_selecting_more_than_one_row(window):
    """The root cause: without ExtendedSelection, a real Cmd-click or Shift-click
    cannot add to the selection - only one row is ever interactively selectable, no
    matter how many rows the other tests here select programmatically.

    setSelected(True) - what _select_top_level_rows and every other test above uses
    - sets selection state directly and ignores selectionMode() entirely; it would
    report 2 selected rows whether or not multi-select actually works, so it cannot
    stand in for this check. This asserts on the widget's own configuration instead,
    which is what a real click depends on."""
    assert (window.source_tree.selectionMode()
           == window.source_tree.SelectionMode.ExtendedSelection)


def test_selecting_a_child_row_removes_its_whole_top_level_source(window):
    """Remove has never operated below whole-source granularity; multi-select must
    not change that - selecting a file inside a folder still drops the folder."""
    folder = SourceItem(kind="folder", value="/music", title="music")
    folder.children = [
        SourceItem(kind="file", value="/music/x.mp3", title="x", duration=1.0),
    ]
    window.sources = [folder,
                      SourceItem(kind="file", value="/keep.mp3", title="keep",
                                duration=2.0)]
    window.refresh_summary()

    child_row = window.source_tree.topLevelItem(0).child(0)
    window.source_tree.clearSelection()
    child_row.setSelected(True)

    window.remove_selected_source()

    assert [s.title for s in window.sources] == ["keep"]


def test_removing_with_nothing_selected_does_nothing(window):
    window.sources = [SourceItem(kind="file", value="/a.mp3", title="a", duration=1.0)]
    window.refresh_summary()
    window.source_tree.clearSelection()

    window.remove_selected_source()

    assert [s.title for s in window.sources] == ["a"]


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
    # Each link's entries carry its own address: two genuinely different links never
    # hand back the same video twice, and the preview drops a repeated source.
    monkeypatch.setattr(tony, "probe_url", lambda url: [
        {"url": f"{url}/1", "title": "One", "duration": 600.0},
        {"url": f"{url}/2", "title": "Two", "duration": 600.0},
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


def _chapter(title, seconds):
    return SimpleNamespace(title=title, seconds=seconds)


def test_a_tonie_with_chapters_can_be_expanded_to_show_them(window, configure,
                                                            monkeypatch):
    configure()
    monkeypatch.setattr(tonie_images, "fetch_all", lambda tonies, **kw: {})
    tonie = FakeTonie("Elephant", chapters=["placeholder"])
    tonie.chapters = [_chapter("Bedtime Story", 724.0), _chapter("Moon Song", 511.0)]

    window.set_tonies([tonie], {})

    row = window._tonie_rows()[0]
    assert row.childCount() == 2
    assert row.child(0).text(0) == "1. Bedtime Story"
    assert row.child(1).text(0) == "2. Moon Song"


def test_chapter_rows_show_their_duration(window, configure, monkeypatch):
    configure()
    monkeypatch.setattr(tonie_images, "fetch_all", lambda tonies, **kw: {})
    tonie = FakeTonie("Elephant")
    tonie.chapters = [_chapter("Bedtime Story", 724.0)]

    window.set_tonies([tonie], {})

    assert window._tonie_rows()[0].child(0).text(2) == tony.format_duration(724.0)


def test_a_tonie_with_no_chapters_has_no_children(window, configure, monkeypatch):
    configure()
    monkeypatch.setattr(tonie_images, "fetch_all", lambda tonies, **kw: {})
    tonie = FakeTonie("Elephant")
    tonie.chapters = []

    window.set_tonies([tonie], {})

    assert window._tonie_rows()[0].childCount() == 0


def test_signing_in_sets_an_icon_when_an_image_is_cached(window, configure, monkeypatch,
                                                         tmp_path):
    configure()
    image_path = tmp_path / "t1.image"
    image_path.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\nIDATx\x9cc\xf8\x0f\x00\x01"
        b"\x01\x01\x00\x1b\xb6\xee\x05\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    tonie = FakeTonie("Elephant")
    tonie.id = "t1"

    window.set_tonies([tonie], {}, image_paths={"t1": image_path})

    assert not window._tonie_rows()[0].icon(0).isNull()


def test_a_tonie_with_no_cached_image_gets_no_icon(window, configure):
    configure()
    tonie = FakeTonie("Elephant")
    tonie.id = "t1"

    window.set_tonies([tonie], {}, image_paths={"t1": None})

    assert window._tonie_rows()[0].icon(0).isNull()


def test_sign_in_fetches_images_for_every_tonie(window, configure, monkeypatch):
    """The end-to-end path: signing in populates icons via fetch_all, not a stub.

    _sign_in_job itself is left in place - it is the one place that calls
    tonie_images.fetch_all - and only its two network-reaching dependencies
    (TonieAPI's login and tony.get_all_creative_tonies) are stubbed out. Replacing
    _sign_in_job wholesale, as a first draft of this test did, would bypass the very
    call this test exists to check.
    """
    pytest.importorskip("tonie_api")
    configure()
    seen = {}

    def fake_fetch_all(tonies, **kwargs):
        seen["tonies"] = tonies
        return {t.id: None for t in tonies}

    monkeypatch.setattr(tonie_images, "fetch_all", fake_fetch_all)
    monkeypatch.setattr("tonie_api.api.TonieAPI", lambda username, password: object())
    monkeypatch.setattr(tony, "get_all_creative_tonies",
                        lambda api: ([FakeTonie("Elephant")], {}))

    window._username, window._password = "me@example.com", "pw"
    window.refresh_tonies()

    assert "tonies" in seen


# ------------------------------------------------- video sources the engine honors

def _video_file(path, seconds=2):
    """A real, tiny video file - enough for ffmpeg to convert into audio."""
    import subprocess

    from conftest import FFMPEG
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [FFMPEG, "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc=size=32x32:rate=5:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-b:a", "32k",
         "-shortest", "-y", str(path)],
        check=True, capture_output=True,
    )
    return path


@requires_ffmpeg
def test_a_ticked_video_turns_conversion_on_by_itself(window, configure, tone_file,
                                                      tmp_path):
    """The window lists videos as uploadable, so the state it builds must convert them.

    With the box unticked the engine only auto-converts when there is no audio at all,
    so a folder holding one MP3 beside two MKVs would upload the MP3 and silently drop
    the videos - against a confirmation that counted all three.
    """
    configure()
    tone_file(2, "a.mp3")
    _video_file(tmp_path / "b.mkv")
    _video_file(tmp_path / "c.mkv")

    window.add_source(str(tmp_path))

    assert window.current_state().convert_video is True
    assert "3 files" in window.summary_text()


@requires_ffmpeg
def test_the_upload_holds_every_file_the_preview_counted(window, configure, tone_file,
                                                         tmp_path):
    """End to end: what the state sends to the engine is what the preview promised."""
    from gui.state import apply as apply_state

    configure()
    tone_file(2, "a.mp3")
    _video_file(tmp_path / "b.mkv")

    window.add_source(str(tmp_path))
    window.no_duration_limit.setChecked(True)

    state = window.current_state()
    apply_state(state)
    files = tony.get_audio_files(tony.args.input_paths)

    try:
        assert sorted(f.title for f in files) == ["a", "b"]
        assert len(files) == len(window.current_state().sources)
    finally:
        tony.cleanup_converted_files()


@requires_ffmpeg
def test_a_video_beside_a_link_is_not_dropped(window, configure, monkeypatch,
                                              tmp_path):
    """A link's download makes audio_files non-empty, which used to stop the engine
    ever auto-converting the videos added alongside it."""
    configure()
    _video_file(tmp_path / "b.mkv")
    monkeypatch.setattr(tony, "probe_url", lambda url: [
        {"url": "https://example.com/1", "title": "Remote", "duration": 60.0},
    ])

    window.add_source(str(tmp_path))
    window.add_source("https://example.com/x")

    assert window.current_state().convert_video is True


def test_a_link_that_looks_like_a_video_file_does_not_force_conversion(window,
                                                                      configure,
                                                                      monkeypatch):
    """A link is downloaded, never converted - its address is not a local file."""
    configure()
    monkeypatch.setattr(tony, "probe_url", lambda url: [
        {"url": "https://example.com/story.mp4", "title": "Story", "duration": 60.0},
    ])

    window.add_source("https://example.com/story.mp4")

    assert window.current_state().convert_video is False


@requires_ffmpeg
def test_the_confirmation_counts_a_repeated_file_once(window, configure, tone_file,
                                                      tmp_path):
    """Adding a file and the folder holding it must not count it twice."""
    configure()
    target = tone_file(2, "once.mp3")

    window.add_source(str(tmp_path))
    window.add_source(str(target))

    assert "1 file" in window.summary_text()
    assert window.current_state().sources == [str(target)]


# ------------------------------------------------------------ signing in and out

class FakeSignInDialog:
    """Stands in for the credential sheet, recording what it was told to say."""

    shown = []

    def __init__(self, parent=None, username="", message=None, accept=False):
        FakeSignInDialog.shown.append(message)
        self._accept = accept

    def exec(self):
        return 1 if self._accept else 0

    def username(self):
        return "me@example.com"

    def password(self):
        return "pw"

    def remember(self):
        return True


@pytest.fixture
def sheet(monkeypatch):
    """Every sign-in sheet the window opens, in order, by the message it carried."""
    FakeSignInDialog.shown = []
    monkeypatch.setattr("gui.app.signin.SignInDialog", FakeSignInDialog)
    return FakeSignInDialog.shown


def _sign_the_window_in(window):
    """Put the window in the state a successful sign-in leaves it in."""
    window._username = "me@example.com"
    window._signed_in((object(), [FakeTonie("Elephant", id="t1")], {"t1": "Home"}, {}))
    return window


def test_signing_in_reveals_the_sign_out_button(window, configure):
    configure()
    assert window.sign_out_button.isHidden() is True

    _sign_the_window_in(window)

    assert window.sign_out_button.isHidden() is False
    assert window.account_button.text() == "Signed in as me@example.com"


def test_signing_out_forgets_the_account_and_empties_the_window(window, configure,
                                                                monkeypatch):
    """The Keychain is not touched here - forget() has its own tests; what matters is
    that the button reaches it, with the username that was signed in."""
    configure()
    forgotten = []
    monkeypatch.setattr("gui.app.signin.forget", lambda username:
                        forgotten.append(username))
    _sign_the_window_in(window)

    window.sign_out_button.click()

    assert forgotten == ["me@example.com"]
    assert window._api is None
    assert window._username is None
    assert window._password is None
    assert window.account_button.text() == "Sign In..."
    assert window.sign_out_button.isHidden() is True
    assert window._tonie_rows() == []
    assert window.selected_tonies() == []


def test_signing_out_then_in_asks_for_credentials_again(window, configure, monkeypatch,
                                                        sheet):
    configure()
    monkeypatch.setattr("gui.app.signin.forget", lambda username: None)
    _sign_the_window_in(window)

    window.sign_out()
    window.account_button.click()

    assert sheet == [None]      # the sheet was opened, with no error message


def test_the_account_button_does_not_pass_qts_checked_flag_as_a_message(window,
                                                                        configure,
                                                                        sheet):
    """clicked(bool) would otherwise land in sign_in's message parameter."""
    configure()

    window.account_button.click()

    assert sheet == [None]


# ------------------------------------------------------- a sign-in that is refused

def _failing_sign_in(monkeypatch, message):
    monkeypatch.setattr("gui.app._sign_in_job",
                        lambda username, password: (_ for _ in ()).throw(
                            ValueError(message)))


def test_a_refused_password_reopens_the_sheet_with_the_reason(window, configure,
                                                              monkeypatch, sheet):
    configure()
    _failing_sign_in(monkeypatch, "Failed to acquire session token")
    window._username, window._password = "me@example.com", "wrong"

    window.refresh_tonies()

    assert sheet == ["Failed to acquire session token"]


def test_the_traceback_stays_out_of_the_log_pane(window, configure, monkeypatch,
                                                 sheet):
    """The pane is read by someone who wants to know whether their audio arrived."""
    configure()
    _failing_sign_in(monkeypatch, "Failed to acquire session token")
    window._username, window._password = "me@example.com", "wrong"

    window.refresh_tonies()

    log = window.log.toPlainText()
    assert "Failed to acquire session token" in log
    assert "Traceback" not in log
    assert len(log.strip().splitlines()) == 1
    assert window.banner_label.text() == "Failed to acquire session token"


def test_a_refused_sign_in_on_a_real_thread_reopens_the_sheet(threaded_window,
                                                              configure, qtbot,
                                                              monkeypatch, sheet):
    """The path users get: the failure arrives from a Worker thread."""
    configure()
    _failing_sign_in(monkeypatch, "Failed to acquire session token")
    window = threaded_window
    window._username, window._password = "me@example.com", "wrong"

    window.refresh_tonies()
    qtbot.waitUntil(lambda: bool(sheet), timeout=10000)
    qtbot.waitUntil(lambda: window.add_folder_button.isEnabled(), timeout=10000)

    assert sheet == ["Failed to acquire session token"]
    assert "Traceback" not in window.log.toPlainText()


# ------------------------------------------- a window nothing has configured yet

@requires_ffmpeg
def test_a_freshly_launched_window_can_read_a_file(window, monkeypatch, tone_file):
    """The shipped app starts with tony.args unset - nothing parses arguments for it.

    Reading a duration goes through tony.args.ffmpeg_path, so every source added
    before the first upload came back carrying an AttributeError instead of a length,
    and was dropped from the upload as a failed source. Every test in the suite used
    the `configure` fixture, which sets tony.args, and so could not see it.
    """
    monkeypatch.setattr(tony, "args", None)
    target = tone_file(3, "solo.mp3")

    window.add_source(str(target))

    assert [s.error for s in window.sources] == [None]
    assert window.sources[0].duration == 3.0
    assert "1 file" in window.summary_text()


def test_a_freshly_launched_window_can_probe_a_link(window, monkeypatch):
    """The same, for a link: probe_url reads tony.args.ytdlp_path."""
    monkeypatch.setattr(tony, "args", None)
    seen = {}

    def probe(url):
        seen["ytdlp_path"] = tony.args.ytdlp_path
        return [{"url": url, "title": "One", "duration": 60.0}]

    monkeypatch.setattr(tony, "probe_url", probe)

    window.add_source("https://example.com/x")

    assert seen["ytdlp_path"] == "yt-dlp"
    assert [s.error for s in window.sources] == [None]


def test_the_engine_is_configured_from_the_windows_own_controls(window, monkeypatch,
                                                                tone_file):
    """Not from defaults: whatever the Advanced panel says is what expansion uses."""
    monkeypatch.setattr(tony, "args", None)
    target = tone_file(2, "solo.mp3")
    window.ffmpeg_path.setText("/custom/ffmpeg")
    window.max_duration.setValue(45.0)

    window.add_source(str(target))

    assert tony.args.ffmpeg_path == "/custom/ffmpeg"
    assert tony.args.max_duration == 45.0
