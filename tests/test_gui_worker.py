"""The worker thread, its log bridge, and cancellation."""
import logging
import threading

import pytest

import tony
from gui.worker import Worker

pytest.importorskip("PySide6")


def test_the_worker_returns_its_result(qtbot):
    worker = Worker(lambda: 21 * 2)
    with qtbot.waitSignal(worker.done, timeout=3000) as blocker:
        worker.start()
    assert blocker.args[0] == 42


def test_the_worker_reports_a_failure_rather_than_raising(qtbot):
    def explode():
        raise RuntimeError("it broke")

    worker = Worker(explode)
    with qtbot.waitSignal(worker.failed, timeout=3000) as blocker:
        worker.start()
    assert "it broke" in blocker.args[0]


def test_engine_log_lines_reach_the_signal(qtbot):
    def logs():
        logging.getLogger().info("Uploading (1/3): Bedtime Story")
        return None

    worker = Worker(logs)
    lines = []
    worker.line.connect(lines.append)
    with qtbot.waitSignal(worker.done, timeout=3000):
        worker.start()

    assert any("Bedtime Story" in line for line in lines)


def test_the_bridge_is_removed_when_the_worker_ends(qtbot):
    before = len(logging.getLogger().handlers)
    worker = Worker(lambda: None)
    with qtbot.waitSignal(worker.done, timeout=3000):
        worker.start()
    assert len(logging.getLogger().handlers) == before


def test_a_concurrent_run_is_rejected_without_touching_the_logger(qtbot):
    root = logging.getLogger()
    handlers_at_start = list(root.handlers)
    level_at_start = root.level

    gate = threading.Event()
    entered = threading.Event()

    def blocking_work():
        entered.set()
        gate.wait(timeout=3)
        return None

    first = Worker(blocking_work)
    first.start()
    assert entered.wait(timeout=3)

    handlers_mid_run = list(root.handlers)
    level_mid_run = root.level

    second = Worker(lambda: None)
    with qtbot.waitSignal(second.failed, timeout=3000) as blocker:
        second.start()

    assert "already running" in blocker.args[0].lower()
    # The invariant this fix exists to protect: a rejected second worker must not
    # have touched the root logger's handlers or level at all.
    assert list(root.handlers) == handlers_mid_run
    assert root.level == level_mid_run

    with qtbot.waitSignal(first.done, timeout=3000):
        gate.set()

    assert list(root.handlers) == handlers_at_start
    assert root.level == level_at_start


def test_a_worker_can_run_again_once_the_lock_is_free(qtbot):
    root = logging.getLogger()
    handlers_before = list(root.handlers)
    level_before = root.level

    worker = Worker(lambda: 1 + 1)
    with qtbot.waitSignal(worker.done, timeout=3000) as blocker:
        worker.start()

    assert blocker.args[0] == 2
    assert list(root.handlers) == handlers_before
    assert root.level == level_before


def test_cancel_is_visible_to_the_work(qtbot):
    seen = []

    def check(worker):
        seen.append(worker.cancelled)
        return None

    worker = Worker(lambda: check(worker))
    worker.cancel()
    with qtbot.waitSignal(worker.done, timeout=3000):
        worker.start()

    assert seen == [True]


# --- the engine side ------------------------------------------------------

class _Tonie:
    def __init__(self):
        self.id, self.name, self.chapters = "t1", "Elephant", []


class _API:
    def __init__(self):
        self.uploaded = []

    def clear_all_chapter_of_tonie(self, tonie):
        pass

    def upload_file_to_tonie(self, tonie, path, title):
        self.uploaded.append(title)

    def get_households(self):
        return []


def test_update_tonie_stops_between_files_when_asked(configure):
    configure()
    api = _API()
    files = [tony.AudioTitle(f"/{n}.mp3", n) for n in ("One", "Two", "Three")]

    # Cancel once the first file is up
    tony.update_tonie(api, _Tonie(), {"t1": "Home"}, files,
                      should_cancel=lambda: len(api.uploaded) >= 1)

    assert api.uploaded == ["One"]


def test_update_tonie_without_the_hook_uploads_everything(configure):
    configure()
    api = _API()
    files = [tony.AudioTitle(f"/{n}.mp3", n) for n in ("One", "Two")]

    tony.update_tonie(api, _Tonie(), {"t1": "Home"}, files)

    assert api.uploaded == ["One", "Two"]
