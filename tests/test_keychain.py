"""Keychain round trip, against a service name nothing else uses."""
import uuid

import pytest

from gui import keychain

TEST_SERVICE = f"tonie-audio-updater-test-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def clean_up():
    yield
    keychain.delete_password("someone@example.com", service=TEST_SERVICE)


def test_store_then_load():
    keychain.store_password("someone@example.com", "hunter2", service=TEST_SERVICE)
    assert keychain.load_password("someone@example.com", service=TEST_SERVICE) == "hunter2"


def test_loading_something_absent_returns_none():
    assert keychain.load_password("nobody@example.com", service=TEST_SERVICE) is None


def test_storing_again_overwrites():
    keychain.store_password("someone@example.com", "first", service=TEST_SERVICE)
    keychain.store_password("someone@example.com", "second", service=TEST_SERVICE)
    assert keychain.load_password("someone@example.com", service=TEST_SERVICE) == "second"


def test_delete_removes_it():
    keychain.store_password("someone@example.com", "hunter2", service=TEST_SERVICE)
    keychain.delete_password("someone@example.com", service=TEST_SERVICE)
    assert keychain.load_password("someone@example.com", service=TEST_SERVICE) is None


def test_deleting_something_absent_is_not_an_error():
    keychain.delete_password("nobody@example.com", service=TEST_SERVICE)


def test_a_password_with_awkward_characters_survives():
    awkward = "p@ss w'rd\"$`\\!"
    keychain.store_password("someone@example.com", awkward, service=TEST_SERVICE)
    assert keychain.load_password("someone@example.com", service=TEST_SERVICE) == awkward
