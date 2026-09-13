"""Runs slow engine work off the UI thread, and turns its logging into Qt signals.

The engine already logs every step worth showing - which file is uploading, what was
truncated, what is being retried - so progress needs no new engine surface. A logging
handler installed for the duration of the run forwards records as a signal.

Only one Worker may mutate the root logger at a time. The UI is expected to run one
upload at a time, but nothing yet enforces that (the parts of the plan that would -
Tasks 10 and 11 - do not exist while this module is being written), and the failure
mode of two Workers touching the same logger concurrently is silent: a stale handler
would leak one run's log lines into another's window, or a wrongly restored level
would quietly drop INFO records again. A module-level lock, taken non-blocking, turns
that into a loud, immediate failure instead.
"""
import logging
import threading
import traceback

from PySide6.QtCore import QThread, Signal

_run_lock = threading.Lock()


class _LogBridge(logging.Handler):
    """Forwards log records to a Qt signal, dropping the timestamp and level the CLI
    prints - a GUI log pane shows the message text only."""

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
    """Runs one callable, reporting its log lines, result, or failure.

    At most one Worker may run at a time. A Worker started while another is still
    running fails immediately, rather than blocking or corrupting the first run's
    logger save/restore.
    """

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
        acquired = _run_lock.acquire(blocking=False)
        if not acquired:
            self.failed.emit("Cannot start: another upload is already running.")
            return

        try:
            root = logging.getLogger()
            bridge = _LogBridge(self.line.emit)
            previous_level = root.level

            try:
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
        finally:
            if acquired:
                _run_lock.release()
