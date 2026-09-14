"""PATH for a Finder-launched app: augmented with common tool locations, never narrowed."""
from gui.__main__ import augment_path

MAC_CANDIDATES = ["/opt/homebrew/bin", "/opt/homebrew/sbin",
                  "/usr/local/bin", "/usr/local/sbin",
                  "/opt/local/bin", "/opt/local/sbin"]


def test_a_missing_directory_is_appended():
    result = augment_path(current="/usr/bin:/bin", candidates=["/opt/homebrew/bin"])
    assert result == "/usr/bin:/bin:/opt/homebrew/bin"


def test_an_already_present_directory_is_not_duplicated():
    result = augment_path(current="/usr/bin:/opt/homebrew/bin",
                          candidates=["/opt/homebrew/bin"])
    assert result == "/usr/bin:/opt/homebrew/bin"


def test_the_existing_path_always_comes_first():
    """Appended, not prepended - whatever the user already configured takes priority."""
    result = augment_path(current="/usr/bin", candidates=["/opt/homebrew/bin"])
    assert result.startswith("/usr/bin:")


def test_several_missing_directories_are_all_appended_in_order():
    result = augment_path(current="/usr/bin", candidates=["/a", "/b", "/c"])
    assert result == "/usr/bin:/a:/b:/c"


def test_an_empty_current_path_still_works():
    result = augment_path(current="", candidates=["/opt/homebrew/bin"])
    assert result == "/opt/homebrew/bin"


def test_no_candidates_present_leaves_path_unchanged():
    result = augment_path(current="/usr/bin:/bin", candidates=[])
    assert result == "/usr/bin:/bin"


def test_defaults_cover_apple_silicon_and_intel_homebrew_and_macports():
    """These are the three real installers this fix exists to find, each contributing a bin and sbin directory."""
    result = augment_path(current="/usr/bin:/bin:/usr/sbin:/sbin")
    for path in MAC_CANDIDATES:
        assert path in result.split(":")


def test_reproduces_the_actual_bug_and_confirms_the_fix(tmp_path, monkeypatch):
    """The exact scenario found in the field: a restricted PATH hides an installed tool."""
    import shutil
    import stat

    # A fake "ffmpeg" that exists only in a directory PATH does not yet include -
    # standing in for a real Homebrew install without depending on one being present.
    fake_bin = tmp_path / "fake-homebrew" / "bin"
    fake_bin.mkdir(parents=True)
    fake_ffmpeg = fake_bin / "ffmpeg"
    fake_ffmpeg.write_text("#!/bin/sh\necho fake\n")
    fake_ffmpeg.chmod(fake_ffmpeg.stat().st_mode | stat.S_IEXEC)

    restricted = "/usr/bin:/bin:/usr/sbin:/sbin"
    monkeypatch.setenv("PATH", restricted)
    assert shutil.which("ffmpeg") is None  # not found under the restricted PATH

    fixed = augment_path(current=restricted, candidates=[str(fake_bin)])
    monkeypatch.setenv("PATH", fixed)
    assert shutil.which("ffmpeg") == str(fake_ffmpeg)  # found once augmented


# ------------------------------------------------------- the entry point itself

def test_main_builds_a_visible_window_and_asks_for_credentials(qapp, monkeypatch):
    """gui.app.main() end to end, which nothing else in the suite runs.

    Two bugs on this branch - the CLI rejecting every link, and a fresh window unable
    to read a file - survived a passing suite because the entry point itself was never
    called. QApplication is stubbed (pytest-qt already owns the real singleton, and a
    second one would refuse to be built); everything else is the real thing.
    """
    import pytest

    pytest.importorskip("PySide6")

    import tony
    from gui import app as gui_app

    class StubApp:
        def __init__(self, argv):
            self.argv = argv

        def setApplicationName(self, name):
            self.name = name

        def exec(self):
            return 0

    opened = []

    class FakeSignInDialog:
        def __init__(self, parent=None, username="", message=None):
            opened.append(message)

        def exec(self):
            return 0          # the person closed the sheet without signing in

    monkeypatch.setattr(gui_app, "QApplication", StubApp)
    monkeypatch.setattr("gui.app.signin.load_saved", lambda: (None, None))
    monkeypatch.setattr("gui.app.signin.SignInDialog", FakeSignInDialog)
    monkeypatch.setattr(tony, "args", None)

    assert gui_app.main() == 0
    assert opened == [None]

    # Windows other tests built are still alive but were never shown, so the one
    # main() put on screen is the one that is visible.
    shown = [w for w in qapp.topLevelWidgets()
             if isinstance(w, gui_app.MainWindow) and w.isVisible()]
    try:
        assert len(shown) == 1
    finally:
        for window in shown:
            window.close()
            window.deleteLater()
