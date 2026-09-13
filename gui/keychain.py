"""The Tonie account password, kept in the macOS login Keychain.

Shells out to security(1) rather than taking a dependency. The password is passed as an
argv element, which is visible in `ps` for the lifetime of the call - a few
milliseconds, and only to this user - which is why the CLI's -p flag is discouraged but
this is not: -p sits in shell history and in the process list for the whole run.
"""
import subprocess

SERVICE = "tonie-audio-updater"


def store_password(username, password, service=SERVICE):
    """Write the password, replacing any existing entry for this account."""
    try:
        subprocess.run(
            ["security", "add-generic-password",
             "-a", username, "-s", service, "-w", password, "-U"],
            capture_output=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        # Do not let the original exception propagate: its str() embeds the full argv,
        # including the plaintext password passed via -w. Re-raise something that
        # carries the failure's exit code and stderr (which does not echo the
        # password) but never the argv or the password itself.
        stderr = e.stderr.decode(errors="replace").strip() if e.stderr else ""
        raise RuntimeError(
            f"security add-generic-password failed (exit {e.returncode}): {stderr}"
        ) from None


def load_password(username, service=SERVICE):
    """Read the password, or None if there is no entry."""
    result = subprocess.run(
        ["security", "find-generic-password", "-a", username, "-s", service, "-w"],
        capture_output=True, text=True,
    )

    if result.returncode != 0:
        return None

    # security appends a newline; a password could legitimately end in one, so strip
    # only the single trailing newline security itself adds
    return result.stdout[:-1] if result.stdout.endswith("\n") else result.stdout


def delete_password(username, service=SERVICE):
    """Remove the entry. Absent is not an error."""
    subprocess.run(
        ["security", "delete-generic-password", "-a", username, "-s", service],
        capture_output=True,
    )
