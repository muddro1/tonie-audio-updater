"""The GUI's controls become an argv list, so both front ends share one parser."""
import pytest

import tony
from gui.state import GuiState, apply, build_argv


def test_defaults_match_the_bare_cli():
    """A default GuiState must produce exactly what the CLI produces with no flags."""
    gui = apply(GuiState(sources=["/tmp"]))
    cli = tony.build_parser().parse_args(["-i", "/tmp"])

    ignored = {"input_paths", "username", "password"}
    gui_values = {k: v for k, v in vars(gui).items() if k not in ignored}
    cli_values = {k: v for k, v in vars(cli).items() if k not in ignored}

    assert gui_values == cli_values


def test_sources_become_input_paths():
    argv = build_argv(GuiState(sources=["/a", "/b.mp3", "https://example.com/x"]))
    parsed = tony.build_parser().parse_args(argv)
    assert parsed.input_paths == ["/a", "/b.mp3", "https://example.com/x"]


def test_a_source_that_looks_like_a_flag_is_still_a_source():
    """A file named '--dry-run.mp3' must not become a flag."""
    argv = build_argv(GuiState(sources=["--dry-run.mp3"]))
    parsed = tony.build_parser().parse_args(argv)
    assert parsed.input_paths == ["--dry-run.mp3"]
    assert parsed.dry_run is False


def test_boolean_controls_emit_their_flags():
    argv = build_argv(GuiState(
        sources=["/tmp"], convert_video=True, trim_silence=True, keep_converted=True,
        no_duration_limit=True, dry_run=True, force_update=True))
    parsed = tony.build_parser().parse_args(argv)

    assert parsed.convert_video is True
    assert parsed.trim_silence is True
    assert parsed.keep_converted is True
    assert parsed.no_duration_limit is True
    assert parsed.dry_run is True
    assert parsed.force_update is True


def test_unset_booleans_emit_nothing():
    argv = build_argv(GuiState(sources=["/tmp"]))
    assert "--dry-run" not in argv
    assert "--trim-silence" not in argv


def test_value_controls_round_trip():
    argv = build_argv(GuiState(
        sources=["/tmp"], audio_bitrate="192k", silence_threshold="-40dB",
        min_silence_duration=3.5, max_duration=60.0, upload_retries=5,
        retry_delay=0.5, ffmpeg_path="/opt/ffmpeg", ytdlp_path="/opt/yt-dlp"))
    parsed = tony.build_parser().parse_args(argv)

    assert parsed.audio_bitrate == "192k"
    assert parsed.silence_threshold == "-40dB"
    assert parsed.min_silence_duration == 3.5
    assert parsed.max_duration == 60.0
    assert parsed.upload_retries == 5
    assert parsed.retry_delay == 0.5
    assert parsed.ffmpeg_path == "/opt/ffmpeg"
    assert parsed.ytdlp_path == "/opt/yt-dlp"


def test_apply_sets_the_module_level_args():
    apply(GuiState(sources=["/tmp"], max_duration=45.0))
    assert tony.args.max_duration == 45.0


def test_every_parser_option_has_a_control():
    """A flag added to build_parser() without a GuiState field is a drift bug."""
    parser_dests = {
        action.dest for action in tony.build_parser()._actions
        if action.dest not in ("help", "input_paths", "username", "password")
    }
    state_fields = set(GuiState.__dataclass_fields__) - {"sources"}

    assert parser_dests == state_fields, (
        f"only in parser: {parser_dests - state_fields}; "
        f"only in GuiState: {state_fields - parser_dests}"
    )
