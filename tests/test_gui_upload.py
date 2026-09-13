"""What the window says before an upload, what it does, and what it reports after."""
import threading

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox

import tony
from gui import app as gui_app
from gui import run as gui_run
from gui.app import MainWindow
from gui.run import TonieOutcome
from gui.sources import SourceItem


class FakeTonie:
    def __init__(self, tonie_id, name, chapters=()):
        from types import SimpleNamespace
        self.id, self.name = tonie_id, name
        self.chapters = [SimpleNamespace(title=t) for t in chapters]


class StubDialog:
    """Stands in for QMessageBox, recording what the user was actually asked.

    The confirmation is the last thing between a click and a Tonie's chapters being
    cleared, so the text it carries is tested rather than assumed - which needs the
    dialog replaced by something that returns instead of waiting for a person.
    """

    Ok = QMessageBox.Ok
    Cancel = QMessageBox.Cancel

    def __init__(self, answer):
        self._answer = answer
        self.asked = []

    def question(self, parent, title, text, *args, **kwargs):
        self.asked.append(text)
        return self._answer


def _dialog(monkeypatch, answer):
    stub = StubDialog(answer)
    monkeypatch.setattr(gui_app, "QMessageBox", stub)
    return stub


def _window(qtbot, monkeypatch, synchronous):
    monkeypatch.setattr("gui.app.signin.load_saved", lambda: ("me@example.com", "pw"))
    w = MainWindow(synchronous=synchronous)
    qtbot.addWidget(w)
    w.set_tonies([FakeTonie("t1", "Elephant", chapters=["Old A", "Old B"]),
                  FakeTonie("t2", "Lion")],
                 {"t1": "Home", "t2": "Attic"})
    w.sources.append(SourceItem(kind="file", value="/One.mp3", title="One",
                                duration=600.0))
    w.refresh_summary()
    return w


@pytest.fixture
def window(qtbot, monkeypatch, configure):
    """Work runs inline, because nothing here spins the event loop a Worker needs."""
    configure()
    return _window(qtbot, monkeypatch, synchronous=True)


@pytest.fixture
def threaded_window(qtbot, monkeypatch, configure):
    """The window as shipped, with its work on a real Worker thread."""
    configure()
    return _window(qtbot, monkeypatch, synchronous=False)


def _real_source(window, tmp_path, name="One.mp3"):
    """Swap the placeholder source for a file that really exists on disk.

    The threaded tests run tony.get_audio_files() for real, which refuses a path that
    is not there; nothing reads the bytes, because the duration limit is switched off.
    """
    path = tmp_path / name
    path.write_bytes(b"")
    window.sources.clear()
    window.sources.append(SourceItem(kind="file", value=str(path), title=path.stem,
                                     duration=10.0))
    window.no_duration_limit.setChecked(True)
    window.refresh_summary()
    return path


# ------------------------------------------------------------------ confirmation

def test_the_confirmation_names_every_tonie(window):
    window.check_tonie("Elephant", True)
    window.check_tonie("Lion", True)

    text = window.confirmation_text()

    assert "Elephant" in text
    assert "Lion" in text


def test_the_confirmation_totals_the_chapters_being_cleared(window):
    window.check_tonie("Elephant", True)   # holds 2
    window.check_tonie("Lion", True)       # holds 0

    assert "2 chapters" in window.confirmation_text()


def test_the_confirmation_names_a_tonie_that_will_be_skipped(window):
    """An up-to-date tonie is skipped unless Force update is on - say so first."""
    window.sources.clear()
    window.sources.append(SourceItem(kind="file", value="/Old A.mp3", title="Old A",
                                     duration=10.0))
    window.sources.append(SourceItem(kind="file", value="/Old B.mp3", title="Old B",
                                     duration=10.0))
    window.refresh_summary()
    window.check_tonie("Elephant", True)

    assert "skipped" in window.confirmation_text().lower()


def test_force_update_removes_the_skip_notice(window):
    window.sources.clear()
    window.sources.append(SourceItem(kind="file", value="/Old A.mp3", title="Old A",
                                     duration=10.0))
    window.sources.append(SourceItem(kind="file", value="/Old B.mp3", title="Old B",
                                     duration=10.0))
    window.refresh_summary()
    window.force_update.setChecked(True)
    window.check_tonie("Elephant", True)

    assert "skipped" not in window.confirmation_text().lower()


def test_the_confirmation_warns_when_over_the_limit(window):
    window.sources.clear()
    window.sources.append(SourceItem(kind="file", value="/Long.mp3", title="Long",
                                     duration=6000.0))
    window.refresh_summary()
    window.check_tonie("Elephant", True)

    text = window.confirmation_text()

    assert "90" in text
    assert "over" in text.lower()


def test_the_dialog_is_shown_exactly_what_confirmation_text_says(window, monkeypatch):
    """The dialog displays this string and nothing of its own, so a test that reads
    confirmation_text() is reading what the user was asked."""
    dialog = _dialog(monkeypatch, StubDialog.Cancel)
    window.check_tonie("Elephant", True)
    window._api = object()

    window.start_upload()

    assert dialog.asked == [window.confirmation_text()]


# ----------------------------------------------------------------------- summary

def test_the_summary_reports_each_outcome(window):
    outcomes = [
        TonieOutcome("Elephant", "updated", "No chapters on tonie"),
        TonieOutcome("Lion", "skipped", "Up to date"),
        TonieOutcome("Zebra", "failed", "network went away"),
    ]

    text = window.summary_of(outcomes)

    assert "Elephant" in text and "updated" in text.lower()
    assert "Lion" in text and "skipped" in text.lower()
    assert "Zebra" in text and "network went away" in text


def test_the_summary_calls_out_a_cancelled_tonie(window):
    text = window.summary_of([
        TonieOutcome("Elephant", "cancelled", "Stopped partway; this Tonie may be incomplete"),
    ])

    assert "incomplete" in text.lower()


def test_the_summary_puts_the_bad_news_first(window):
    text = window.summary_of([
        TonieOutcome("Skipped one", "skipped"),
        TonieOutcome("Updated one", "updated"),
        TonieOutcome("Failed one", "failed", "boom"),
    ])

    assert text.splitlines()[0].startswith("Failed one")


# ---------------------------------------------------------------------- cleanup

def test_temp_files_are_cleaned_up_after_a_run(window, monkeypatch):
    called = []
    monkeypatch.setattr(tony, "cleanup_converted_files", lambda: called.append(True))

    window.on_run_finished([TonieOutcome("Elephant", "updated")])

    assert called == [True]


def test_temp_files_are_cleaned_up_after_a_failure(window, monkeypatch):
    called = []
    monkeypatch.setattr(tony, "cleanup_converted_files", lambda: called.append(True))

    window.on_run_failed("it broke")

    assert called == [True]


def test_cleanup_runs_when_the_run_fails_before_the_job_can_clean_up(window,
                                                                     monkeypatch):
    """The discriminating failure: _upload_job's own finally never runs.

    Gathering the files happens outside that try, so a failure here can only be
    cleaned up by on_run_failed - which is why the count is exactly one.
    """
    called = []
    monkeypatch.setattr(tony, "cleanup_converted_files", lambda: called.append(True))

    def no_files(paths):
        raise ValueError("No audio files found")

    monkeypatch.setattr(tony, "get_audio_files", no_files)
    _dialog(monkeypatch, StubDialog.Ok)
    window._api = object()
    window.check_tonie("Elephant", True)

    window.start_upload()

    assert called == [True]
    assert "No audio files found" in window.banner_label.text()
    assert window.add_folder_button.isEnabled() is True


def test_cleanup_runs_when_the_upload_itself_raises(window, monkeypatch):
    """Both paths run: _upload_job's finally, then on_run_failed. Neither is enough
    on its own, and cleaning up twice removes nothing that is still there."""
    called = []
    monkeypatch.setattr(tony, "cleanup_converted_files", lambda: called.append(True))
    monkeypatch.setattr(tony, "get_audio_files", lambda paths: ["audio"])

    def boom(*a, **k):
        raise RuntimeError("the network went away")

    monkeypatch.setattr(gui_run, "upload_to_tonies", boom)
    _dialog(monkeypatch, StubDialog.Ok)
    window._api = object()
    window.check_tonie("Elephant", True)

    window.start_upload()

    assert called == [True, True]
    assert "the network went away" in window.log.toPlainText()
    assert window.banner_label.text().startswith("Upload failed: ")


# ------------------------------------------------------------------ starting it

def test_cancelling_the_confirmation_uploads_nothing(window, monkeypatch):
    dispatched = []
    monkeypatch.setattr(gui_app, "_upload_job",
                        lambda *a: dispatched.append(a))
    _dialog(monkeypatch, StubDialog.Cancel)
    window._api = object()
    window.check_tonie("Elephant", True)
    window.force_update.setChecked(True)

    window.start_upload()

    assert dispatched == []
    # apply() was never reached, so the engine still holds what configure() set
    assert tony.args.force_update is False
    assert window.add_folder_button.isEnabled() is True


def test_nothing_is_asked_when_no_tonie_is_ticked(window, monkeypatch):
    dialog = _dialog(monkeypatch, StubDialog.Ok)
    window._api = object()

    window.start_upload()

    assert dialog.asked == []
    assert "Creative Tonie" in window.banner_label.text()


def test_nothing_is_asked_when_there_is_no_audio(window, monkeypatch):
    dialog = _dialog(monkeypatch, StubDialog.Ok)
    window._api = object()
    window.sources.clear()
    window.refresh_summary()
    window.check_tonie("Elephant", True)

    window.start_upload()

    assert dialog.asked == []
    assert "audio" in window.banner_label.text().lower()


def test_confirming_uploads_and_reports_every_tonie(window, monkeypatch):
    seen = {}

    def fake_upload(api, tonies, households, audio_files, should_cancel=None):
        seen.update(api=api, tonies=[t.name for t in tonies], households=households,
                    audio_files=audio_files, should_cancel=should_cancel)
        return [TonieOutcome("Elephant", "updated", "No chapters on tonie"),
                TonieOutcome("Lion", "skipped", "Up to date")]

    monkeypatch.setattr(tony, "get_audio_files", lambda paths: ["audio"])
    monkeypatch.setattr(gui_run, "upload_to_tonies", fake_upload)
    _dialog(monkeypatch, StubDialog.Ok)
    api = object()
    window._api = api
    window.check_tonie("Elephant", True)
    window.check_tonie("Lion", True)
    window.force_update.setChecked(True)

    window.start_upload()

    # The window configured the engine through apply(), not by building args itself
    assert tony.args.force_update is True
    assert seen["api"] is api
    assert seen["tonies"] == ["Elephant", "Lion"]
    assert seen["audio_files"] == ["audio"]
    assert seen["should_cancel"]() is False

    log = window.log.toPlainText()
    assert "Elephant: updated" in log
    assert "Lion: skipped" in log
    assert window.banner_label.text() == "1 skipped, 1 updated"
    assert window.add_folder_button.isEnabled() is True


def test_an_empty_result_says_so_rather_than_claiming_success(window):
    window.on_run_finished([])

    assert window.banner_label.text() == "Nothing to do"


# -------------------------------------------------------------- on a real thread

def test_the_upload_runs_on_a_real_worker_thread(threaded_window, qtbot, monkeypatch,
                                                 tmp_path):
    """The path users actually get: dispatched to a Worker, delivered by the loop."""
    window = threaded_window
    ran_on = []

    def fake_update(api, tonie, households, audio_files, dry_run=False,
                    should_cancel=None):
        ran_on.append(threading.current_thread())

    monkeypatch.setattr(tony, "update_tonie", fake_update)
    _dialog(monkeypatch, StubDialog.Ok)
    _real_source(window, tmp_path)
    window._api = object()
    window.check_tonie("Elephant", True)

    window.start_upload()

    # Locked the moment the work is dispatched, before the loop has run at all
    assert window.add_folder_button.isEnabled() is False
    assert window.cancel_button.isEnabled() is True

    qtbot.waitUntil(lambda: window.add_folder_button.isEnabled(), timeout=10000)

    assert ran_on and ran_on[0] is not threading.main_thread()
    assert "Elephant: updated" in window.log.toPlainText()
    assert window.banner_label.text() == "1 updated"
    assert window.cancel_button.isEnabled() is False


def test_cancelling_stops_before_the_next_tonie(threaded_window, qtbot, monkeypatch,
                                                tmp_path):
    """Cancel is pressed on the UI thread while the work is really in flight."""
    window = threaded_window
    started, release = threading.Event(), threading.Event()

    def fake_update(api, tonie, households, audio_files, dry_run=False,
                    should_cancel=None):
        started.set()
        release.wait(10)

    monkeypatch.setattr(tony, "update_tonie", fake_update)
    _dialog(monkeypatch, StubDialog.Ok)
    _real_source(window, tmp_path)
    window._api = object()
    window.check_tonie("Elephant", True)
    window.check_tonie("Lion", True)

    window.start_upload()
    qtbot.waitUntil(started.is_set, timeout=10000)

    window.cancel_upload()
    release.set()
    qtbot.waitUntil(lambda: window.add_folder_button.isEnabled(), timeout=10000)

    log = window.log.toPlainText()
    assert "Elephant: updated" in log
    assert "Lion: cancelled" in log
    assert window.banner_label.text() == "1 cancelled, 1 updated"
