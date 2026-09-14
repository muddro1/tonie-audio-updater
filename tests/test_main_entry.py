"""main() itself: what it accepts as an input before anything else happens.

Nothing else in the suite calls main(), which is how a check that rejected every link
before it reached the code that handles links survived 232 passing tests. These run
main() for real, with only the two network-reaching pieces stubbed: the TonieAPI
constructor (imported inside main(), so it is patched where it lives) and, where a run
gets that far, the yt-dlp invocation.

main() catches everything and exits 1, so a failure is read from the log rather than
from the exception: the message is what tells the URL-rejection bug apart from any
other failure.
"""
import pytest

import tony


class _Sentinel(Exception):
    """Raised by the stubbed TonieAPI: proof the run got past input validation."""


@pytest.fixture
def no_network(monkeypatch):
    """Stop the run at the first network call, loudly and identifiably."""
    pytest.importorskip("tonie_api")

    def explode(username, password):
        raise _Sentinel("reached the Tonie API")

    monkeypatch.setattr("tonie_api.api.TonieAPI", explode)


def _run(argv, caplog):
    """Run main() and hand back everything it logged."""
    with caplog.at_level("DEBUG"):
        with pytest.raises(SystemExit) as exit_info:
            tony.main(argv)
    assert exit_info.value.code == 1
    return caplog.text


URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_a_link_is_not_rejected_as_a_missing_path(no_network, caplog):
    """The headline case: a link has nothing on disk, and must not be checked for."""
    text = _run(["-i", URL, "-u", "x", "-p", "y"], caplog)

    assert "Input path does not exist" not in text
    assert "reached the Tonie API" in text


def test_a_missing_local_path_still_raises(no_network, caplog):
    """The regression guard: the link fix must not swallow a real missing file."""
    text = _run(["-i", "/no/such/thing", "-u", "x", "-p", "y"], caplog)

    assert "Input path does not exist: /no/such/thing" in text
    assert "reached the Tonie API" not in text


def test_a_link_beside_a_missing_path_still_raises(no_network, caplog):
    text = _run(["-i", URL, "/no/such/thing", "-u", "x", "-p", "y"], caplog)

    assert "Input path does not exist: /no/such/thing" in text
    assert "reached the Tonie API" not in text


def test_a_real_local_path_is_accepted(no_network, caplog, tmp_path):
    text = _run(["-i", str(tmp_path), "-u", "x", "-p", "y"], caplog)

    assert "Input path does not exist" not in text
    assert "reached the Tonie API" in text
