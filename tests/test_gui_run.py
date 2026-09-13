"""Uploading one set of files to several Tonies."""
from types import SimpleNamespace

import pytest

import tony
from gui.run import upload_to_tonies


class FakeTonie:
    def __init__(self, tonie_id, name, chapters=()):
        self.id, self.name = tonie_id, name
        self.chapters = [SimpleNamespace(title=t) for t in chapters]


class FakeAPI:
    def __init__(self, fail_for=()):
        self.calls = []
        self.fail_for = set(fail_for)

    def clear_all_chapter_of_tonie(self, tonie):
        self.calls.append(f"clear:{tonie.name}")

    def upload_file_to_tonie(self, tonie, path, title):
        if tonie.name in self.fail_for:
            raise ConnectionError("network went away")
        self.calls.append(f"upload:{tonie.name}:{title}")

    def get_households(self):
        return []


def _files(*titles):
    return [tony.AudioTitle(f"/{t}.mp3", t) for t in titles]


HOUSEHOLDS = {"t1": "Home", "t2": "Home", "t3": "Attic"}


def test_uploads_to_every_selected_tonie(configure):
    configure()
    api = FakeAPI()
    tonies = [FakeTonie("t1", "Elephant"), FakeTonie("t2", "Lion")]

    outcomes = upload_to_tonies(api, tonies, HOUSEHOLDS, _files("One"))

    assert [o.status for o in outcomes] == ["updated", "updated"]
    assert api.calls == [
        "clear:Elephant", "upload:Elephant:One",
        "clear:Lion", "upload:Lion:One",
    ]


def test_an_up_to_date_tonie_is_skipped(configure):
    configure()
    api = FakeAPI()
    tonies = [FakeTonie("t1", "Elephant", chapters=["One"]), FakeTonie("t2", "Lion")]

    outcomes = upload_to_tonies(api, tonies, HOUSEHOLDS, _files("One"))

    assert [(o.name, o.status) for o in outcomes] == [
        ("Elephant", "skipped"), ("Lion", "updated")]
    assert "clear:Elephant" not in api.calls


def test_force_update_uploads_to_an_up_to_date_tonie(configure):
    configure("--force-update")
    api = FakeAPI()
    tonies = [FakeTonie("t1", "Elephant", chapters=["One"])]

    outcomes = upload_to_tonies(api, tonies, HOUSEHOLDS, _files("One"))

    assert outcomes[0].status == "updated"
    assert "clear:Elephant" in api.calls


def test_one_failure_does_not_abandon_the_rest(configure):
    configure("--upload-retries", "1", "--retry-delay", "0")
    api = FakeAPI(fail_for={"Elephant"})
    tonies = [FakeTonie("t1", "Elephant"), FakeTonie("t2", "Lion")]

    outcomes = upload_to_tonies(api, tonies, HOUSEHOLDS, _files("One"))

    assert [(o.name, o.status) for o in outcomes] == [
        ("Elephant", "failed"), ("Lion", "updated")]
    assert "upload:Lion:One" in api.calls


def test_a_failure_carries_its_reason(configure):
    configure("--upload-retries", "1", "--retry-delay", "0")
    api = FakeAPI(fail_for={"Elephant"})

    outcomes = upload_to_tonies(api, [FakeTonie("t1", "Elephant")], HOUSEHOLDS,
                                _files("One"))

    assert "network went away" in outcomes[0].detail


def test_cancelling_stops_before_the_next_tonie(configure):
    configure()
    api = FakeAPI()
    tonies = [FakeTonie("t1", "Elephant"), FakeTonie("t2", "Lion")]
    cancelled = []

    def should_cancel():
        return bool(cancelled)

    def cancel_after_first(*_):
        cancelled.append(True)

    original = tony.update_tonie

    def spy(*a, **kw):
        result = original(*a, **kw)
        cancel_after_first()
        return result

    tony.update_tonie = spy
    try:
        outcomes = upload_to_tonies(api, tonies, HOUSEHOLDS, _files("One"),
                                    should_cancel=should_cancel)
    finally:
        tony.update_tonie = original

    assert [(o.name, o.status) for o in outcomes] == [
        ("Elephant", "updated"), ("Lion", "cancelled")]
    assert "clear:Lion" not in api.calls


def test_a_dry_run_touches_nothing(configure):
    configure("--dry-run")
    api = FakeAPI()

    outcomes = upload_to_tonies(api, [FakeTonie("t1", "Elephant")], HOUSEHOLDS,
                                _files("One"))

    assert outcomes[0].status == "updated"
    assert api.calls == []


def test_a_cancellation_mid_upload_is_reported_cancelled_not_updated(configure):
    """The engine polls should_cancel before each file; if it fires partway through a
    Tonie's own upload, that Tonie must be reported cancelled - not updated - since its
    chapters were already cleared and only some files landed."""
    configure()
    api = FakeAPI()
    tonies = [FakeTonie("t1", "Elephant")]
    uploaded = []

    def should_cancel():
        return len(uploaded) >= 1

    original_upload = api.upload_file_to_tonie

    def tracking_upload(tonie, path, title):
        original_upload(tonie, path, title)
        uploaded.append(title)

    api.upload_file_to_tonie = tracking_upload

    outcomes = upload_to_tonies(api, tonies, HOUSEHOLDS, _files("One", "Two"),
                                should_cancel=should_cancel)

    assert outcomes[0].status == "cancelled"
    assert "incomplete" in outcomes[0].detail
    assert api.calls == ["clear:Elephant", "upload:Elephant:One"]


def test_a_cancellation_after_completion_still_reports_updated(configure):
    """Regression guard: a should_cancel flag that only flips after a Tonie's upload has
    fully finished must not relabel that already-completed Tonie as cancelled."""
    configure()
    api = FakeAPI()
    tonies = [FakeTonie("t1", "Elephant"), FakeTonie("t2", "Lion")]
    cancelled = []

    def should_cancel():
        return bool(cancelled)

    def cancel_after_first(*_):
        cancelled.append(True)

    original = tony.update_tonie

    def spy(*a, **kw):
        result = original(*a, **kw)
        cancel_after_first()
        return result

    tony.update_tonie = spy
    try:
        outcomes = upload_to_tonies(api, tonies, HOUSEHOLDS, _files("One"),
                                    should_cancel=should_cancel)
    finally:
        tony.update_tonie = original

    assert [(o.name, o.status) for o in outcomes] == [
        ("Elephant", "updated"), ("Lion", "cancelled")]
    assert "clear:Lion" not in api.calls
