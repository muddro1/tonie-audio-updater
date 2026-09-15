"""Tests for tony.py.

The tests that measure or truncate audio shell out to a real ffmpeg rather than
mocking it, since the behaviour under test is precisely what ffmpeg does at a frame
boundary. They skip when ffmpeg is missing.
"""
import logging
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


def test_get_audio_duration_does_not_ask_ffmpeg_to_decode(configure, monkeypatch):
    """Regression guard for a real bug: -f null - fully decodes the file just to read
    a duration already sitting in the startup banner. Invisible on the few-second clips
    every other test here uses; on a real video it made a "cheap" GUI preview take as
    long as playing the file. Assert on the command itself, not just correctness,
    since a reintroduced -f null - would still return the right number - slowly."""
    configure()
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return SimpleNamespace(stderr="Duration: 00:00:05.00, start: 0.0", returncode=1)

    monkeypatch.setattr(tony.subprocess, "run", fake_run)

    tony.get_audio_duration("/some/file.mp4")

    assert "-f" not in seen["cmd"]
    assert "null" not in seen["cmd"]


@requires_ffmpeg
def test_get_audio_duration_reads_a_real_videos_duration_without_decoding_it(configure,
                                                                             tmp_path):
    """The case that actually broke: nothing before this exercised a video file, so
    the full-decode cost stayed invisible until someone loaded a real one."""
    import subprocess
    import time

    video = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=20",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
         "-y", str(video)],
        check=True, capture_output=True,
    )

    configure()
    start = time.time()
    duration = tony.get_audio_duration(str(video))
    elapsed = time.time() - start

    assert duration == pytest.approx(20, abs=0.5)
    # A full decode of even this short a clip takes noticeably longer than reading
    # its header; a generous bound catches a regression without being timing-fragile.
    assert elapsed < 5.0


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

    files = tony.get_audio_files([str(tmp_path)])

    assert [f.title for f in files] == ["apple", "Zebra"]


def test_get_audio_files_rejects_a_missing_directory(configure):
    configure()
    with pytest.raises(FileNotFoundError):
        tony.get_audio_files(["/no/such/directory"])


def test_get_audio_files_raises_when_the_directory_is_empty(configure, tmp_path):
    configure()
    with pytest.raises(ValueError, match="No audio files"):
        tony.get_audio_files([str(tmp_path)])


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


# --- file discovery is case-insensitive -----------------------------------

@requires_ffmpeg
def test_uppercase_audio_extensions_are_found(configure, tone_file, tmp_path):
    """Files straight off a ripper or camera are often .MP3 / .MOV."""
    tone_file(2, "Shouty.mp3")
    (tmp_path / "Shouty.mp3").rename(tmp_path / "Shouty.MP3")
    configure()

    files = tony.get_audio_files([str(tmp_path)])

    assert [f.title for f in files] == ["Shouty"]


@requires_ffmpeg
def test_mixed_case_extensions_are_all_found(configure, tone_file, tmp_path):
    for name, renamed in [("a.mp3", "a.MP3"), ("b.mp3", "b.Mp3"), ("c.mp3", "c.mp3")]:
        tone_file(2, name)
        if name != renamed:
            (tmp_path / name).rename(tmp_path / renamed)
    configure()

    files = tony.get_audio_files([str(tmp_path)])

    assert sorted(f.title for f in files) == ["a", "b", "c"]


@requires_ffmpeg
def test_each_file_is_only_found_once(configure, tone_file, tmp_path):
    """A case-insensitive match must not report the same file twice."""
    tone_file(2, "once.mp3")
    configure()

    files = tony.get_audio_files([str(tmp_path)])

    assert len(files) == 1


@requires_ffmpeg
def test_uppercase_video_extensions_are_converted(configure, tone_file, tmp_path):
    """.MOV off a phone or camera should convert like .mov does."""
    source = tone_file(3, "Clip.m4a")
    source.rename(tmp_path / "Clip.MOV")
    configure("--convert-video")

    files = tony.get_audio_files([str(tmp_path)])

    assert [f.title for f in files] == ["Clip"]
    assert files[0].is_converted is True
    tony.cleanup_converted_files()


def test_find_files_ignores_directories(tmp_path):
    (tmp_path / "nested.mp3").mkdir()
    (tmp_path / "real.mp3").write_text("")

    found = tony.find_files(str(tmp_path), tony.AUDIO_EXTENSIONS)

    assert [os.path.basename(p) for p in found] == ["real.mp3"]


def test_find_files_ignores_other_extensions(tmp_path):
    for name in ("keep.mp3", "skip.txt", "skip.pdf", "noext"):
        (tmp_path / name).write_text("")

    found = tony.find_files(str(tmp_path), tony.AUDIO_EXTENSIONS)

    assert [os.path.basename(p) for p in found] == ["keep.mp3"]


# --- upload recovery ------------------------------------------------------

class FakeTonie:
    def __init__(self, name="Elephant", chapters=()):
        self.id = "t1"
        self.name = name
        self.chapters = [SimpleNamespace(title=t) for t in chapters]


class FakeAPI:
    """Records calls, and can be told to fail a given upload a number of times."""

    def __init__(self, fail_on=None, fail_times=0):
        self.calls = []
        self.fail_on = fail_on
        self.fail_times = fail_times
        self._failures = 0

    def clear_all_chapter_of_tonie(self, tonie):
        self.calls.append("clear")

    def upload_file_to_tonie(self, tonie, filepath, title):
        if title == self.fail_on and self._failures < self.fail_times:
            self._failures += 1
            self.calls.append(f"upload:{title}:fail")
            raise ConnectionError("network went away")
        self.calls.append(f"upload:{title}")

    def get_households(self):
        return []


def test_existing_chapters_are_logged_before_they_are_cleared(configure, caplog):
    """Clearing is unavoidable, so a record of what was there is the only safety net."""
    configure()
    tonie = FakeTonie(chapters=["Old One", "Old Two"])
    api = FakeAPI()

    with caplog.at_level(logging.INFO):
        tony.update_tonie(api, tonie, {"t1": "Home"}, [tony.AudioTitle("/a.mp3", "New")])

    assert "Old One" in caplog.text
    assert "Old Two" in caplog.text
    # The record has to come before the clear, or it is worthless
    order = [r.message for r in caplog.records]
    logged = next(i for i, m in enumerate(order) if "Old One" in m)
    cleared = next(i for i, m in enumerate(order) if "Clearing" in m)
    assert logged < cleared


def test_a_transient_upload_failure_is_retried(configure):
    configure("--upload-retries", "3", "--retry-delay", "0")
    api = FakeAPI(fail_on="Two", fail_times=2)
    files = [tony.AudioTitle("/a.mp3", "One"), tony.AudioTitle("/b.mp3", "Two")]

    tony.update_tonie(api, FakeTonie(), {"t1": "Home"}, files)

    assert api.calls == [
        "clear", "upload:One",
        "upload:Two:fail", "upload:Two:fail", "upload:Two",
    ]


def test_an_upload_that_keeps_failing_raises(configure):
    configure("--upload-retries", "2", "--retry-delay", "0")
    api = FakeAPI(fail_on="One", fail_times=99)

    with pytest.raises(ConnectionError):
        tony.update_tonie(api, FakeTonie(), {"t1": "Home"},
                          [tony.AudioTitle("/a.mp3", "One")])

    assert api.calls.count("upload:One:fail") == 2


def test_a_failed_upload_reports_what_was_lost(configure, caplog):
    configure("--upload-retries", "1", "--retry-delay", "0")
    api = FakeAPI(fail_on="New", fail_times=99)
    tonie = FakeTonie(chapters=["Old One"])

    with pytest.raises(ConnectionError):
        tony.update_tonie(api, tonie, {"t1": "Home"},
                          [tony.AudioTitle("/a.mp3", "New")])

    assert "Old One" in caplog.text
    assert "no longer on" in caplog.text.lower() or "lost" in caplog.text.lower()


def test_a_dry_run_neither_clears_nor_uploads(configure):
    configure("--dry-run")
    api = FakeAPI()

    tony.update_tonie(api, FakeTonie(chapters=["Old"]), {"t1": "Home"},
                      [tony.AudioTitle("/a.mp3", "New")], dry_run=True)

    assert api.calls == []


# --- selecting a tonie without the menu -----------------------------------

def test_select_tonie_by_exact_name(configure):
    configure("--tonie", "Elephant")
    tonies = [FakeTonie("Lion"), FakeTonie("Elephant")]

    assert tony.select_tonies_by_name(tonies, {}) == [tonies[1]]


def test_selecting_by_name_ignores_case_and_padding(configure):
    configure("--tonie", "  eLePhAnT ")
    tonies = [FakeTonie("Lion"), FakeTonie("Elephant")]

    assert tony.select_tonies_by_name(tonies, {}) == [tonies[1]]


def test_an_unknown_name_is_an_error_listing_what_exists(configure):
    configure("--tonie", "Giraffe")
    tonies = [FakeTonie("Lion"), FakeTonie("Elephant")]

    with pytest.raises(ValueError) as excinfo:
        tony.select_tonies_by_name(tonies, {})

    assert "Giraffe" in str(excinfo.value)
    assert "Lion" in str(excinfo.value)
    assert "Elephant" in str(excinfo.value)


def test_an_ambiguous_name_is_an_error(configure):
    """Two households can hold Tonies with the same name - picking one would be a guess."""
    configure("--tonie", "Elephant")
    a, b = FakeTonie("Elephant"), FakeTonie("Elephant")
    b.id = "t2"

    with pytest.raises(ValueError, match="[Aa]mbiguous|more than one"):
        tony.select_tonies_by_name([a, b], {"t1": "Upstairs", "t2": "Downstairs"})


def test_non_interactive_without_a_name_is_an_error(configure):
    """Defaulting to the first Tonie the API happens to return clears a random Tonie."""
    configure("--non-interactive")

    with pytest.raises(ValueError, match="--tonie"):
        tony.select_tonies_by_name([FakeTonie("Lion"), FakeTonie("Elephant")], {})


def test_non_interactive_with_one_tonie_needs_no_name(configure):
    configure("--non-interactive")
    only = FakeTonie("Lion")

    assert tony.select_tonies_by_name([only], {}) == [only]


# --- needs_update ---------------------------------------------------------

def _files(*titles):
    return [tony.AudioTitle(f"/{t}.mp3", t) for t in titles]


def test_matching_files_and_chapters_need_no_update(configure):
    configure()
    needed, reason = tony.needs_update(FakeTonie(chapters=["One", "Two"]),
                                       _files("One", "Two"))
    assert needed is False
    assert reason == "Up to date"


def test_a_tonie_with_no_chapters_needs_an_update(configure):
    configure()
    assert tony.needs_update(FakeTonie(), _files("One"))[0] is True


def test_a_different_file_count_needs_an_update(configure):
    configure()
    assert tony.needs_update(FakeTonie(chapters=["One"]), _files("One", "Two"))[0] is True


def test_a_different_title_needs_an_update(configure):
    configure()
    needed, reason = tony.needs_update(FakeTonie(chapters=["One", "Two"]),
                                       _files("One", "Three"))
    assert needed is True
    assert "Three" in reason


def test_reordered_chapters_need_an_update(configure):
    """Chapter order is playback order, so a reorder is a real change."""
    configure()
    needed, reason = tony.needs_update(FakeTonie(chapters=["Two", "One"]),
                                       _files("One", "Two"))
    assert needed is True
    assert "order" in reason.lower()


def test_duplicate_titles_are_compared_by_count(configure):
    """Sorted set comparison treated ['A','A','B'] and ['A','B','B'] as equal."""
    configure()
    assert tony.needs_update(FakeTonie(chapters=["A", "A", "B"]),
                             _files("A", "B", "B"))[0] is True


def test_identical_duplicate_titles_need_no_update(configure):
    configure()
    assert tony.needs_update(FakeTonie(chapters=["A", "A", "B"]),
                             _files("A", "A", "B"))[0] is False


def test_titles_match_regardless_of_case_and_padding(configure):
    configure()
    assert tony.needs_update(FakeTonie(chapters=["  ONE  ", "Two"]),
                             _files("one", "two"))[0] is False


def test_force_update_overrides_everything(configure):
    configure()
    needed, reason = tony.needs_update(FakeTonie(chapters=["One"]), _files("One"),
                                       force_update=True)
    assert needed is True
    assert "orce" in reason


# --- small cleanups -------------------------------------------------------

def test_audio_titles_can_go_in_a_set():
    """Defining __eq__ without __hash__ makes a class unhashable."""
    assert len({tony.AudioTitle("/a.mp3", "Same"),
                tony.AudioTitle("/b.mp3", "Same")}) == 1


def test_min_silence_duration_is_parsed_as_a_number():
    a = tony.build_parser().parse_args(["-i", "/tmp", "--min-silence-duration", "3.5"])
    assert a.min_silence_duration == 3.5


def test_a_non_numeric_min_silence_duration_is_rejected_at_parse_time():
    with pytest.raises(SystemExit):
        tony.build_parser().parse_args(["-i", "/tmp", "--min-silence-duration", "soon"])


def test_end_of_input_exits_cleanly_at_the_menu(configure, monkeypatch):
    """Piping input used to end in an EOFError traceback."""
    configure()
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))

    with pytest.raises(SystemExit) as excinfo:
        tony.display_tonies_menu([FakeTonie("Lion")], {"t1": "Home"},
                                 _files("One"))

    assert excinfo.value.code == 0


def test_end_of_input_exits_cleanly_at_the_confirmation(configure, monkeypatch):
    configure()
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))

    with pytest.raises(SystemExit) as excinfo:
        tony.confirm_selection([FakeTonie("Lion")], {"t1": "Home"}, _files("One"))

    assert excinfo.value.code == 0


def test_non_interactive_never_blocks_on_a_credential_prompt(monkeypatch):
    """A cron job has no TTY - prompting there hangs or dies on EOF."""
    monkeypatch.delenv("TONIE_USERNAME", raising=False)
    monkeypatch.delenv("TONIE_PASSWORD", raising=False)

    def explode(_):
        raise AssertionError("prompted in non-interactive mode")

    monkeypatch.setattr("builtins.input", explode)
    monkeypatch.setattr(tony.getpass, "getpass", explode)
    a = tony.build_parser().parse_args(["-i", "/tmp", "--non-interactive"])

    with pytest.raises(ValueError, match="TONIE_PASSWORD|TONIE_USERNAME"):
        tony.resolve_credentials(a)


def test_end_of_input_at_the_credential_prompt_is_a_clean_error(monkeypatch):
    monkeypatch.delenv("TONIE_USERNAME", raising=False)
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))
    a = tony.build_parser().parse_args(["-i", "/tmp"])

    with pytest.raises(ValueError, match="[Nn]o username"):
        tony.resolve_credentials(a)
