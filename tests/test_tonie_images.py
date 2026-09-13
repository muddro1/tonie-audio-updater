"""Each Tonie's own picture: fetched once, cached on disk, never a hard failure."""
from types import SimpleNamespace

import pytest

from gui import tonie_images


def _tonie(id="t1", image_url="https://example.com/t1.jpg"):
    return SimpleNamespace(id=id, name=id, imageUrl=image_url)


def _fake_get(monkeypatch, content=b"fake-image-bytes", status=200, calls=None):
    """Stand in for requests.get, counting calls so a cache hit is provably free."""
    def fake(url, timeout=None):
        if calls is not None:
            calls.append(url)
        return SimpleNamespace(
            content=content, status_code=status,
            raise_for_status=(lambda: None) if status == 200 else _raise,
        )

    def _raise():
        import requests
        raise requests.exceptions.RequestException(f"status {status}")

    monkeypatch.setattr(tonie_images.requests, "get", fake)


def test_fetch_writes_the_bytes_and_returns_the_path(tmp_path, monkeypatch):
    _fake_get(monkeypatch, content=b"hello")

    path = tonie_images.fetch_and_cache(_tonie(), base_dir=tmp_path)

    assert path is not None
    assert path.read_bytes() == b"hello"


def test_a_second_fetch_is_free(tmp_path, monkeypatch):
    calls = []
    _fake_get(monkeypatch, calls=calls)

    first = tonie_images.fetch_and_cache(_tonie(), base_dir=tmp_path)
    second = tonie_images.fetch_and_cache(_tonie(), base_dir=tmp_path)

    assert first == second
    assert len(calls) == 1


def test_two_tonies_get_two_separate_files(tmp_path, monkeypatch):
    _fake_get(monkeypatch)

    a = tonie_images.fetch_and_cache(_tonie("t1"), base_dir=tmp_path)
    b = tonie_images.fetch_and_cache(_tonie("t2"), base_dir=tmp_path)

    assert a != b


def test_a_tonie_with_no_image_url_is_skipped_without_a_network_call(tmp_path,
                                                                     monkeypatch):
    calls = []
    _fake_get(monkeypatch, calls=calls)

    result = tonie_images.fetch_and_cache(_tonie(image_url=None), base_dir=tmp_path)

    assert result is None
    assert calls == []


def test_a_failed_fetch_returns_none_rather_than_raising(tmp_path, monkeypatch):
    _fake_get(monkeypatch, status=404)

    result = tonie_images.fetch_and_cache(_tonie(), base_dir=tmp_path)

    assert result is None


def test_a_network_error_returns_none_rather_than_raising(tmp_path, monkeypatch):
    import requests

    def explode(url, timeout=None):
        raise requests.exceptions.ConnectionError("no route to host")

    monkeypatch.setattr(tonie_images.requests, "get", explode)

    assert tonie_images.fetch_and_cache(_tonie(), base_dir=tmp_path) is None


def test_a_failed_fetch_leaves_no_partial_file_behind(tmp_path, monkeypatch):
    _fake_get(monkeypatch, status=500)

    tonie_images.fetch_and_cache(_tonie(), base_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_fetch_all_covers_every_tonie(tmp_path, monkeypatch):
    _fake_get(monkeypatch)

    result = tonie_images.fetch_all([_tonie("t1"), _tonie("t2")], base_dir=tmp_path)

    assert set(result) == {"t1", "t2"}
    assert all(path is not None for path in result.values())


def test_fetch_all_does_not_let_one_failure_lose_the_rest(tmp_path, monkeypatch):
    def fake(url, timeout=None):
        if "bad" in url:
            raise __import__("requests").exceptions.RequestException("gone")
        return SimpleNamespace(content=b"ok", status_code=200,
                               raise_for_status=lambda: None)

    monkeypatch.setattr(tonie_images.requests, "get", fake)

    result = tonie_images.fetch_all(
        [_tonie("t1", "https://example.com/bad.jpg"), _tonie("t2")], base_dir=tmp_path)

    assert result["t1"] is None
    assert result["t2"] is not None


def test_cache_dir_is_created_if_missing():
    path = tonie_images.cache_dir()
    assert path.is_dir()
