"""The credential sheet and what it remembers."""
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings

from gui import signin

TEST_ORG, TEST_APP = "tonie-test", f"signin-test"


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    monkeypatch.setattr(signin, "SETTINGS_ORG", TEST_ORG)
    monkeypatch.setattr(signin, "SETTINGS_APP", TEST_APP)
    monkeypatch.setattr(signin, "SERVICE", "tonie-audio-updater-signin-test")
    yield
    QSettings(TEST_ORG, TEST_APP).clear()
    signin.forget("someone@example.com")


def test_nothing_saved_yet():
    assert signin.load_saved() == (None, None)


def test_save_then_load_round_trips():
    signin.save("someone@example.com", "hunter2", remember=True)
    assert signin.load_saved() == ("someone@example.com", "hunter2")


def test_not_remembering_keeps_the_username_but_not_the_password():
    """The username is not a secret, and prefilling it is the point."""
    signin.save("someone@example.com", "hunter2", remember=False)
    assert signin.load_saved() == ("someone@example.com", None)


def test_forget_clears_both():
    signin.save("someone@example.com", "hunter2", remember=True)
    signin.forget("someone@example.com")
    assert signin.load_saved() == (None, None)


def test_the_dialog_reports_what_was_typed(qtbot):
    dialog = signin.SignInDialog(username="prefilled@example.com")
    qtbot.addWidget(dialog)

    assert dialog.username() == "prefilled@example.com"

    dialog._password.setText("typed")
    assert dialog.password() == "typed"
    assert dialog.remember() is True


def test_the_password_field_is_masked(qtbot):
    from PySide6.QtWidgets import QLineEdit

    dialog = signin.SignInDialog()
    qtbot.addWidget(dialog)

    assert dialog._password.echoMode() == QLineEdit.Password


def test_sign_in_is_disabled_until_both_fields_have_content(qtbot):
    dialog = signin.SignInDialog()
    qtbot.addWidget(dialog)

    assert dialog._ok.isEnabled() is False
    dialog._username.setText("someone@example.com")
    assert dialog._ok.isEnabled() is False
    dialog._password.setText("hunter2")
    assert dialog._ok.isEnabled() is True
