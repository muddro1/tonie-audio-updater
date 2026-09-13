"""Tests for -i accepting several paths, files as well as directories."""
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
