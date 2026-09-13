"""Uploading one prepared set of files to several Creative Tonies.

Kept free of Qt so the behaviour that matters - skipping what is already up to date,
carrying on past a failure, stopping when cancelled - can be tested without a widget.
"""
import logging
from dataclasses import dataclass

import tony


@dataclass
class TonieOutcome:
    """What happened to one Tonie in the run."""
    name: str
    status: str      # "updated" | "skipped" | "failed" | "cancelled"
    detail: str = ""


def upload_to_tonies(api, tonies, households, audio_files, should_cancel=None):
    """Upload audio_files to each Tonie in turn, returning one outcome each.

    A Tonie already holding these files is skipped unless --force-update is set, which
    is the decision the CLI's main() makes. A Tonie that fails does not abandon the ones
    after it. Cancelling stops before the next Tonie starts, and everything not yet
    attempted is reported as cancelled rather than silently dropped.

    A Tonie whose own upload is interrupted partway - the engine polls should_cancel
    before each file - is reported cancelled, not updated: its chapters were already
    cleared, so claiming success would tell the user their audio is on the device when
    it is not. A cancellation that arrives only after a Tonie's upload has fully
    finished must not retroactively relabel that Tonie; it only stops the ones after it.
    """
    outcomes = []
    cancelled = False

    for tonie in tonies:
        if cancelled or (should_cancel is not None and should_cancel()):
            cancelled = True
            outcomes.append(TonieOutcome(tonie.name, "cancelled", "Not started"))
            continue

        needed, reason = tony.needs_update(tonie, audio_files, tony.args.force_update)

        if not needed:
            logging.info(f"'{tonie.name}' is already up to date")
            outcomes.append(TonieOutcome(tonie.name, "skipped", reason))
            continue

        logging.info(f"Update reason for '{tonie.name}': {reason}")

        # Wrap should_cancel so we can tell, after the call returns, whether the engine
        # actually stopped early on THIS Tonie - as opposed to a cancellation that only
        # arrives in the gap before the next Tonie starts, which must not relabel this
        # one. The engine polls the hook before each file, so a recorded True means
        # precisely "stopped early here".
        interrupted = False

        def probe(_should_cancel=should_cancel):
            nonlocal interrupted
            if _should_cancel is not None and _should_cancel():
                interrupted = True
                return True
            return False

        try:
            tony.update_tonie(api, tonie, households, audio_files,
                              dry_run=tony.args.dry_run,
                              should_cancel=probe if should_cancel is not None else None)
        except Exception as e:
            logging.error(f"Failed to update '{tonie.name}': {e}")
            outcomes.append(TonieOutcome(tonie.name, "failed", str(e)))
            continue

        if interrupted:
            cancelled = True
            logging.warning(f"'{tonie.name}' was cancelled partway through and may be "
                            f"incomplete")
            outcomes.append(TonieOutcome(
                tonie.name, "cancelled",
                "Stopped partway through the upload; this Tonie may be incomplete"))
            continue

        outcomes.append(TonieOutcome(tonie.name, "updated", reason))

    return outcomes
