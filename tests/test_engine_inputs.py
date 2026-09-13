"""Tests for -i accepting several paths, files as well as directories."""
import json
import subprocess

import pytest

import tony
from conftest import requires_ffmpeg


@requires_ffmpeg
def test_a_directory_still_works(configure, tone_file, tmp_path):
    tone_file(2, "a.mp3")
    configure()
    files = tony.get_audio_files([str(tmp_path)])
    assert [f.title for f in files] == ["a"]


@requires_ffmpeg
def test_a_named_file_is_accepted(configure, tone_file, tmp_path):
    target = tone_file(2, "only.mp3")
    tone_file(2, "ignored.mp3", frequency=300)
    configure()
    files = tony.get_audio_files([str(target)])
    assert [f.title for f in files] == ["only"]


@requires_ffmpeg
def test_a_directory_and_a_file_combine(configure, tone_file, tmp_path):
    folder = tmp_path / "folder"
    tone_file(2, "inside.mp3", directory=folder)
    loose = tone_file(2, "loose.mp3", frequency=300)
    configure()
    files = tony.get_audio_files([str(folder), str(loose)])
    assert sorted(f.title for f in files) == ["inside", "loose"]


@requires_ffmpeg
def test_the_same_file_named_twice_appears_once(configure, tone_file, tmp_path):
    target = tone_file(2, "once.mp3")
    configure()
    files = tony.get_audio_files([str(target), str(target)])
    assert len(files) == 1


def test_a_named_file_with_an_unsupported_extension_is_rejected(configure, tmp_path):
    junk = tmp_path / "notes.txt"
    junk.write_text("hello")
    configure()
    with pytest.raises(ValueError, match="notes.txt"):
        tony.get_audio_files([str(junk)])


def test_a_missing_path_names_itself(configure):
    configure()
    with pytest.raises(FileNotFoundError, match="/no/such/thing"):
        tony.get_audio_files(["/no/such/thing"])


def test_the_parser_takes_several_inputs():
    a = tony.build_parser().parse_args(["-i", "/one", "/two", "/three"])
    assert a.input_paths == ["/one", "/two", "/three"]


def test_the_parser_still_takes_one_input():
    a = tony.build_parser().parse_args(["-i", "/only"])
    assert a.input_paths == ["/only"]


@pytest.mark.parametrize("value,expected", [
    ("https://example.com/watch?v=a", True),
    ("http://example.com/watch?v=a", True),
    ("HTTPS://EXAMPLE.COM/x", True),
    ("/Users/me/file.mp3", False),
    ("~/Music", False),
    ("file.mp3", False),
    ("", False),
])
def test_is_url(value, expected):
    assert tony.is_url(value) is expected


def _fake_ytdlp(monkeypatch, payload, returncode=0, stderr=""):
    """Replace the yt-dlp invocation with canned JSON."""
    def fake_run(cmd, *a, **kw):
        return subprocess.CompletedProcess(
            cmd, returncode, stdout=json.dumps(payload), stderr=stderr)
    monkeypatch.setattr(tony.subprocess, "run", fake_run)


def test_probe_url_reads_a_single_video(configure, monkeypatch):
    configure()
    _fake_ytdlp(monkeypatch, {
        "id": "abc", "title": "The Sleepy Fox", "duration": 724.0,
        "webpage_url": "https://example.com/watch?v=abc",
    })

    items = tony.probe_url("https://example.com/watch?v=abc")

    assert items == [{
        "url": "https://example.com/watch?v=abc",
        "title": "The Sleepy Fox",
        "duration": 724.0,
    }]


def test_probe_url_expands_a_playlist(configure, monkeypatch):
    configure()
    _fake_ytdlp(monkeypatch, {
        "_type": "playlist", "title": "Bedtime",
        "entries": [
            {"title": "One", "duration": 60.0, "url": "https://example.com/1"},
            {"title": "Two", "duration": 90.0, "url": "https://example.com/2"},
        ],
    })

    items = tony.probe_url("https://example.com/playlist?list=xyz")

    assert [i["title"] for i in items] == ["One", "Two"]
    assert [i["duration"] for i in items] == [60.0, 90.0]


def test_probe_url_tolerates_a_missing_duration(configure, monkeypatch):
    configure()
    _fake_ytdlp(monkeypatch, {
        "_type": "playlist",
        "entries": [{"title": "Live", "url": "https://example.com/live"}],
    })

    assert tony.probe_url("https://example.com/x")[0]["duration"] is None


def test_probe_url_skips_unavailable_playlist_entries(configure, monkeypatch):
    """yt-dlp reports a removed or private video as a null entry."""
    configure()
    _fake_ytdlp(monkeypatch, {
        "_type": "playlist",
        "entries": [
            {"title": "Fine", "duration": 10.0, "url": "https://example.com/1"},
            None,
        ],
    })

    assert [i["title"] for i in tony.probe_url("https://example.com/x")] == ["Fine"]


def test_probe_url_raises_with_the_reason(configure, monkeypatch):
    configure()

    def fake_run(cmd, *a, **kw):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="ERROR: Private video")

    monkeypatch.setattr(tony.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Private video"):
        tony.probe_url("https://example.com/private")


def test_check_ytdlp_is_false_when_absent(configure):
    configure("--ytdlp-path", "/nonexistent/yt-dlp")
    assert tony.check_ytdlp() is False


import os


def _fake_download(monkeypatch, tmp_path, titles):
    """Stand in for a yt-dlp download: write real files, report them as it does."""
    written = []

    def fake_run(cmd, *a, **kw):
        if "-o" not in cmd:
            # check_ytdlp's "--version" probe, or anything else that isn't the
            # download invocation itself - report success without downloading.
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        out_dir = cmd[cmd.index("-o") + 1].rsplit("/", 1)[0]
        os.makedirs(out_dir, exist_ok=True)
        lines = []
        for title in titles:
            path = os.path.join(out_dir, f"{title}.mp3")
            with open(path, "wb") as f:
                f.write(b"\xff\xfb\x90\x00" * 64)  # plausible mp3 bytes
            written.append(path)
            lines.append(json.dumps({"title": title, "filepath": path}))
        return subprocess.CompletedProcess(cmd, 0, stdout="\n".join(lines), stderr="")

    monkeypatch.setattr(tony.subprocess, "run", fake_run)
    return written


def test_download_url_returns_paths_and_titles(configure, monkeypatch, tmp_path):
    configure()
    _fake_download(monkeypatch, tmp_path, ["The Sleepy Fox"])

    got = tony.download_url("https://example.com/watch?v=abc", str(tmp_path))

    assert len(got) == 1
    assert got[0]["title"] == "The Sleepy Fox"
    assert os.path.exists(got[0]["filepath"])


def test_download_url_raises_with_the_reason(configure, monkeypatch, tmp_path):
    configure()

    def fake_run(cmd, *a, **kw):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="ERROR: Video unavailable")

    monkeypatch.setattr(tony.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Video unavailable"):
        tony.download_url("https://example.com/gone", str(tmp_path))


def test_get_audio_files_downloads_a_url(configure, monkeypatch, tmp_path):
    configure("--no-duration-limit")
    _fake_download(monkeypatch, tmp_path, ["Downloaded Story"])

    files = tony.get_audio_files(["https://example.com/watch?v=abc"])

    assert [f.title for f in files] == ["Downloaded Story"]
    assert files[0].is_downloaded is True


def test_a_downloaded_file_is_registered_for_cleanup(configure, monkeypatch, tmp_path):
    configure("--no-duration-limit")
    _fake_download(monkeypatch, tmp_path, ["Downloaded Story"])

    files = tony.get_audio_files(["https://example.com/watch?v=abc"])
    path = files[0].filepath

    assert path in tony._converted_files
    tony.cleanup_converted_files()
    assert not os.path.exists(path)


def test_a_url_title_is_truncated_like_a_filename(configure, monkeypatch, tmp_path):
    configure("--no-duration-limit")
    _fake_download(monkeypatch, tmp_path, ["x" * 200])

    files = tony.get_audio_files(["https://example.com/watch?v=abc"])

    assert len(files[0].title) <= 100


def test_urls_and_paths_mix(configure, monkeypatch, tone_file, tmp_path):
    local = tone_file(2, "local.mp3")
    configure("--no-duration-limit")
    _fake_download(monkeypatch, tmp_path / "dl", ["Remote"])

    files = tony.get_audio_files([str(local), "https://example.com/watch?v=abc"])

    assert sorted(f.title for f in files) == ["Remote", "local"]


def test_a_url_without_ytdlp_is_a_clear_error(configure):
    configure("--ytdlp-path", "/nonexistent/yt-dlp")

    with pytest.raises(FileNotFoundError, match="yt-dlp"):
        tony.get_audio_files(["https://example.com/watch?v=abc"])
