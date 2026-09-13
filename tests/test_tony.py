"""Tests for tony.py.

The tests that measure or truncate audio shell out to a real ffmpeg rather than
mocking it, since the behaviour under test is precisely what ffmpeg does at a frame
boundary. They skip when ffmpeg is missing.
"""
import os
from types import SimpleNamespace

import pytest

import tony
from conftest import requires_ffmpeg


# --- format_duration -------------------------------------------------------

@pytest.mark.parametrize("seconds,expected", [
    (0, "0:00:00"),
    (9, "0:00:09"),
    (59.4, "0:00:59"),
    (59.6, "0:01:00"),      # rounds to the nearest second
    (60, "0:01:00"),
    (3599, "0:59:59"),
    (3600, "1:00:00"),
    (5399.03, "1:29:59"),   # what a 90 minute cap actually produces
    (5400, "1:30:00"),
])
def test_format_duration(seconds, expected):
    assert tony.format_duration(seconds) == expected


# --- truncate_title --------------------------------------------------------

def test_truncate_title_leaves_short_titles_alone():
    assert tony.truncate_title("Bedtime Story", 100) == "Bedtime Story"


def test_truncate_title_respects_the_limit():
    assert len(tony.truncate_title("x" * 200, 100)) <= 100


def test_truncate_title_breaks_on_a_word_boundary():
    title = "word " * 30  # 150 characters
    result = tony.truncate_title(title, 100)
    assert not result.endswith(" ")
    assert "..." not in result
    assert result == result.rstrip()


def test_truncate_title_ellipsizes_when_there_is_no_late_word_break():
    # A single long run of characters has no space to break on
    result = tony.truncate_title("x" * 150, 100)
    assert result.endswith("...")
    assert len(result) == 100


# --- normalize_title -------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (None, ""),
    ("", ""),
    ("  Padded  ", "padded"),
    ("MiXeD Case", "mixed case"),
    (123, "123"),
])
def test_normalize_title(value, expected):
    assert tony.normalize_title(value) == expected


# --- describe_audio_file ---------------------------------------------------

def test_describe_audio_file_says_nothing_for_a_plain_file(configure):
    configure()
    assert tony.describe_audio_file(tony.AudioTitle("/a.mp3", "A")) == ""


def test_describe_audio_file_reports_conversion(configure):
    configure()
    f = tony.AudioTitle("/a.mp3", "A", is_converted=True)
    assert tony.describe_audio_file(f) == " (converted from video)"


def test_describe_audio_file_reports_both_notes(configure):
    configure()
    f = tony.AudioTitle("/a.mp3", "A", is_converted=True, is_capped=True)
    assert tony.describe_audio_file(f) == " (converted from video, truncated to 90 min)"


# --- build_parser ----------------------------------------------------------

def test_parser_defaults():
    a = tony.build_parser().parse_args(["-u", "u", "-p", "p", "-i", "/tmp"])
    assert a.max_duration == 90.0
    assert a.no_duration_limit is False
    assert a.dry_run is False
    assert a.audio_bitrate == "128k"


def test_parser_rejects_a_non_numeric_max_duration():
    with pytest.raises(SystemExit):
        tony.build_parser().parse_args(["-u", "u", "-p", "p", "-i", "/tmp",
                                       "--max-duration", "ninety"])


# --- AudioTitle ------------------------------------------------------------

def test_audio_titles_compare_by_title_only():
    assert tony.AudioTitle("/one.mp3", "Same") == tony.AudioTitle("/two.mp3", "Same")
    assert tony.AudioTitle("/one.mp3", "A") != tony.AudioTitle("/one.mp3", "B")


# --- get_audio_duration ----------------------------------------------------

@requires_ffmpeg
def test_get_audio_duration_measures_a_real_file(configure, tone_file):
    configure()
    assert tony.get_audio_duration(tone_file(3)) == pytest.approx(3, abs=0.2)


@requires_ffmpeg
def test_get_audio_duration_returns_none_for_a_non_audio_file(configure, tmp_path):
    configure()
    junk = tmp_path / "not-audio.mp3"
    junk.write_text("this is not audio")
    assert tony.get_audio_duration(junk) is None


def test_get_audio_duration_returns_none_when_ffmpeg_is_missing(configure):
    configure("--ffmpeg-path", "/nonexistent/ffmpeg")
    assert tony.get_audio_duration("/some/file.mp3") is None


# --- enforce_max_duration: the single-file cap -----------------------------

@requires_ffmpeg
def test_a_single_over_long_file_is_truncated_to_within_the_limit(configure, tone_file):
    source = tone_file(120, "Long.mp3")
    configure("--max-duration", "1")  # 60 seconds
    files = [tony.AudioTitle(str(source), "Long")]
    temp_files = []

    tony.enforce_max_duration(files, temp_files)

    assert files[0].is_capped is True
    assert tony.get_audio_duration(files[0].filepath) <= 60
    assert temp_files == [files[0].filepath]


@requires_ffmpeg
def test_truncation_never_modifies_the_source_file(configure, tone_file):
    source = tone_file(120, "Long.mp3")
    before = source.read_bytes()
    configure("--max-duration", "1")
    files = [tony.AudioTitle(str(source), "Long")]

    tony.enforce_max_duration(files, [])

    assert source.read_bytes() == before
    assert files[0].filepath != str(source)


@requires_ffmpeg
def test_the_truncated_copy_never_lands_in_the_input_directory(configure, tone_file, tmp_path):
    """A copy beside the source would be picked up as an extra file on the next run."""
    source = tone_file(120, "Long.mp3")
    configure("--max-duration", "1")
    files = [tony.AudioTitle(str(source), "Long")]

    tony.enforce_max_duration(files, [])

    assert os.path.dirname(files[0].filepath) != str(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Long.mp3"]


@requires_ffmpeg
def test_a_file_under_the_limit_is_left_alone(configure, tone_file):
    source = tone_file(30, "Short.mp3")
    configure("--max-duration", "1")
    files = [tony.AudioTitle(str(source), "Short")]
    temp_files = []

    tony.enforce_max_duration(files, temp_files)

    assert files[0].is_capped is False
    assert files[0].filepath == str(source)
    assert temp_files == []


@requires_ffmpeg
def test_no_duration_limit_skips_the_check_entirely(configure, tone_file):
    source = tone_file(120, "Long.mp3")
    configure("--max-duration", "1", "--no-duration-limit")
    files = [tony.AudioTitle(str(source), "Long")]

    tony.enforce_max_duration(files, [])

    assert files[0].is_capped is False
    assert files[0].duration is None


@requires_ffmpeg
def test_truncation_that_cannot_succeed_raises_rather_than_uploading(configure, tone_file):
    """Uploading clears the Tonie's chapters first, so a doomed upload must not start."""
    source = tone_file(30, "Short.mp3")
    configure("--max-duration", "0.01")  # 0.6s, under the safety margin

    with pytest.raises(RuntimeError, match="could not be truncated"):
        tony.enforce_max_duration([tony.AudioTitle(str(source), "Short")], [])


def test_the_check_is_skipped_when_ffmpeg_is_missing(configure):
    configure("--ffmpeg-path", "/nonexistent/ffmpeg", "--max-duration", "1")
    files = [tony.AudioTitle("/some/file.mp3", "File")]

    tony.enforce_max_duration(files, [])

    assert files[0].is_capped is False


# --- enforce_max_duration: several files ----------------------------------

@requires_ffmpeg
def test_several_files_over_the_limit_are_warned_about_never_truncated(
        configure, tone_file, caplog):
    a = tone_file(40, "A.mp3")
    b = tone_file(40, "B.mp3", frequency=300)
    configure("--max-duration", "1")  # 60s total limit, 80s of audio
    files = [tony.AudioTitle(str(a), "A"), tony.AudioTitle(str(b), "B")]
    temp_files = []

    tony.enforce_max_duration(files, temp_files)

    assert [f.is_capped for f in files] == [False, False]
    assert temp_files == []
    assert "over the 1 minute Creative Tonie limit" in caplog.text


@requires_ffmpeg
def test_several_files_under_the_limit_produce_no_warning(configure, tone_file, caplog):
    a = tone_file(10, "A.mp3")
    b = tone_file(10, "B.mp3", frequency=300)
    configure("--max-duration", "1")
    files = [tony.AudioTitle(str(a), "A"), tony.AudioTitle(str(b), "B")]

    tony.enforce_max_duration(files, [])

    assert "over the" not in caplog.text
    assert [f.duration == pytest.approx(10, abs=0.2) for f in files] == [True, True]


# --- cleanup --------------------------------------------------------------

@requires_ffmpeg
def test_cleanup_removes_the_truncated_copy_and_its_directory(configure, tone_file):
    source = tone_file(120, "Long.mp3")
    configure("--max-duration", "1")
    files = [tony.AudioTitle(str(source), "Long")]
    temp_files = []
    tony.enforce_max_duration(files, temp_files)
    tony._converted_files = temp_files
    capped = temp_files[0]

    tony.cleanup_converted_files()

    assert not os.path.exists(capped)
    assert not os.path.exists(os.path.dirname(capped))


@requires_ffmpeg
def test_keep_converted_leaves_the_truncated_copy_in_place(configure, tone_file):
    source = tone_file(120, "Long.mp3")
    configure("--max-duration", "1", "--keep-converted")
    files = [tony.AudioTitle(str(source), "Long")]
    temp_files = []
    tony.enforce_max_duration(files, temp_files)
    tony._converted_files = temp_files

    tony.cleanup_converted_files()

    assert os.path.exists(temp_files[0])
    os.remove(temp_files[0])


# --- get_audio_files ------------------------------------------------------

@requires_ffmpeg
def test_get_audio_files_finds_audio_and_sorts_by_title(configure, tone_file, tmp_path):
    tone_file(2, "Zebra.mp3")
    tone_file(2, "apple.mp3", frequency=300)
    configure()

    files = tony.get_audio_files(str(tmp_path))

    assert [f.title for f in files] == ["apple", "Zebra"]


def test_get_audio_files_rejects_a_missing_directory(configure):
    configure()
    with pytest.raises(FileNotFoundError):
        tony.get_audio_files("/no/such/directory")


def test_get_audio_files_raises_when_the_directory_is_empty(configure, tmp_path):
    configure()
    with pytest.raises(ValueError, match="No audio files"):
        tony.get_audio_files(str(tmp_path))


# --- credentials ----------------------------------------------------------

def test_password_is_not_required_on_the_command_line():
    """It would be visible in `ps` output and shell history."""
    a = tony.build_parser().parse_args(["-i", "/tmp"])
    assert a.password is None
    assert a.username is None


def test_credentials_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("TONIE_USERNAME", "env-user")
    monkeypatch.setenv("TONIE_PASSWORD", "env-pass")
    a = tony.build_parser().parse_args(["-i", "/tmp"])

    assert tony.resolve_credentials(a) == ("env-user", "env-pass")


def test_command_line_credentials_win_over_the_environment(monkeypatch):
    monkeypatch.setenv("TONIE_USERNAME", "env-user")
    monkeypatch.setenv("TONIE_PASSWORD", "env-pass")
    a = tony.build_parser().parse_args(["-i", "/tmp", "-u", "flag-user", "-p", "flag-pass"])

    assert tony.resolve_credentials(a) == ("flag-user", "flag-pass")


def test_missing_credentials_are_prompted_for(monkeypatch):
    monkeypatch.delenv("TONIE_USERNAME", raising=False)
    monkeypatch.delenv("TONIE_PASSWORD", raising=False)
    monkeypatch.setattr("builtins.input", lambda _: "typed-user")
    monkeypatch.setattr(tony.getpass, "getpass", lambda _: "typed-pass")
    a = tony.build_parser().parse_args(["-i", "/tmp"])

    assert tony.resolve_credentials(a) == ("typed-user", "typed-pass")


def test_an_empty_prompted_password_is_an_error(monkeypatch):
    monkeypatch.delenv("TONIE_PASSWORD", raising=False)
    monkeypatch.setattr(tony.getpass, "getpass", lambda _: "")
    a = tony.build_parser().parse_args(["-i", "/tmp", "-u", "user"])

    with pytest.raises(ValueError, match="[Pp]assword"):
        tony.resolve_credentials(a)
