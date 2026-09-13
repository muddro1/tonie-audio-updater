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

        try:
            tony.update_tonie(api, tonie, households, audio_files,
                              dry_run=tony.args.dry_run, should_cancel=should_cancel)
        except Exception as e:
            logging.error(f"Failed to update '{tonie.name}': {e}")
            outcomes.append(TonieOutcome(tonie.name, "failed", str(e)))
            continue

        outcomes.append(TonieOutcome(tonie.name, "updated", reason))

    return outcomes
