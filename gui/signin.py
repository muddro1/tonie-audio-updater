"""The Tonie account credentials: a sheet to type them, and where they are kept.

The username is not a secret and lives in QSettings so it can prefill the field. The
password lives only in the login Keychain, and only when "Remember" is ticked.
"""
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
                               QLabel, QLineEdit, QVBoxLayout)

from gui.keychain import SERVICE, delete_password, load_password, store_password

SETTINGS_ORG = "tonie-audio-updater"
SETTINGS_APP = "gui"
USERNAME_KEY = "account/username"


def _settings():
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def load_saved():
    """(username, password), either of which may be None."""
    username = _settings().value(USERNAME_KEY) or None
    if not username:
        return None, None
    return username, load_password(username, service=SERVICE)


def save(username, password, remember):
    """Remember the username always; the password only if asked."""
    _settings().setValue(USERNAME_KEY, username)
    if remember:
        store_password(username, password, service=SERVICE)
    else:
        delete_password(username, service=SERVICE)


def forget(username):
    """Sign out: drop the username and the stored password."""
    settings = _settings()
    settings.remove(USERNAME_KEY)
    settings.sync()
    if username:
        delete_password(username, service=SERVICE)


class SignInDialog(QDialog):
    """Asks for the account credentials. Shown on first run, or after a rejection."""

    def __init__(self, parent=None, username="", message=None):
        super().__init__(parent)
        self.setWindowTitle("Sign in to Tonie")
        self.setModal(True)

        layout = QVBoxLayout(self)

        if message:
            warning = QLabel(message)
            warning.setWordWrap(True)
            layout.addWidget(warning)

        form = QFormLayout()
        self._username = QLineEdit(username)
        self._username.setPlaceholderText("you@example.com")
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.Password)
        form.addRow("Username", self._username)
        form.addRow("Password", self._password)
        layout.addLayout(form)

        self._remember = QCheckBox("Remember in Keychain")
        self._remember.setChecked(True)
        layout.addWidget(self._remember)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._ok = buttons.button(QDialogButtonBox.Ok)
        self._ok.setText("Sign in")
        self._ok.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._username.textChanged.connect(self._refresh_ok)
        self._password.textChanged.connect(self._refresh_ok)
        self._refresh_ok()

    def _refresh_ok(self):
        self._ok.setEnabled(bool(self._username.text().strip())
                            and bool(self._password.text()))

    def username(self):
        return self._username.text().strip()

    def password(self):
        return self._password.text()

    def remember(self):
        return self._remember.isChecked()
