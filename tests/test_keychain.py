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


def test_a_password_ending_in_a_space_survives():
    # This is the case a naive `.strip()` would corrupt: our code removes only the
    # single trailing newline `security` itself appends, so a real trailing space
    # in the password must remain.
    trailing_space = "hunter2 "
    keychain.store_password("someone@example.com", trailing_space, service=TEST_SERVICE)
    assert keychain.load_password("someone@example.com", service=TEST_SERVICE) == trailing_space


def test_a_password_containing_a_newline_is_hex_encoded_by_security_itself():
    # `security find-generic-password -w` prints one value per line; if the stored
    # password itself contains a newline (trailing or embedded), a raw print would
    # be ambiguous, so `security` hex-encodes the whole value instead of returning
    # it as typed. That happens inside `security`, before our code ever sees the
    # output - our single-trailing-newline strip has nothing to do with it, and
    # there is no reliable client-side fix: the hex form is indistinguishable from
    # a password that is itself a literal hex string. Pinned here so this is a
    # known, documented limitation rather than a surprise.
    with_newline = "hunter2\n"
    keychain.store_password("someone@example.com", with_newline, service=TEST_SERVICE)
    loaded = keychain.load_password("someone@example.com", service=TEST_SERVICE)
    assert loaded == with_newline.encode().hex()
