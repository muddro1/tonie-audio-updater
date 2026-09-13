"""Runs slow engine work off the UI thread, and turns its logging into Qt signals.

The engine already logs every step worth showing - which file is uploading, what was
truncated, what is being retried - so progress needs no new engine surface. A logging
handler installed for the duration of the run forwards records as a signal.
"""
import logging
import traceback

from PySide6.QtCore import QThread, Signal


class _LogBridge(logging.Handler):
    """Forwards log records to a Qt signal, formatted as the CLI formats them."""

    def __init__(self, emit_line):
        super().__init__()
        self._emit_line = emit_line
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record):
        try:
            self._emit_line(self.format(record))
        except Exception:
            pass  # A failing log handler must never break the run


class Worker(QThread):
    """Runs one callable, reporting its log lines, result, or failure."""

    line = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *fn_args, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._fn_args = fn_args
        self._cancelled = False

    @property
    def cancelled(self):
        """Polled by the work itself, between units it can safely stop between."""
        return self._cancelled

    def cancel(self):
        self._cancelled = True

    def run(self):
        root = logging.getLogger()
        bridge = _LogBridge(self.line.emit)
        previous_level = root.level

        root.addHandler(bridge)
        if previous_level > logging.INFO or previous_level == logging.NOTSET:
            root.setLevel(logging.INFO)

        try:
            self.done.emit(self._fn(*self._fn_args))
        except Exception as e:
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")
        finally:
            root.removeHandler(bridge)
            root.setLevel(previous_level)
