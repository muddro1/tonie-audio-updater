#!/usr/bin/env bash
# Build the unsigned .app bundle.
set -euo pipefail

# Captured before cd changes what a relative PYTHON would be relative to.
ORIGINAL_DIR="$(pwd)"

cd "$(dirname "$0")"

# Run through the interpreter rather than the "pyinstaller" console script, which
# is only on PATH when the venv holding it is active. PYTHON overrides which one.
PYTHON="${PYTHON:-python3}"
if [[ "$PYTHON" == */* && "$PYTHON" != /* ]]; then
    # A relative path - e.g. PYTHON=.venv-dev/bin/python - means relative to
    # wherever this script was run from, not to build/ where we just cd'd to.
    # A bare command name (no "/" at all) is left alone and found on PATH instead.
    PYTHON="$ORIGINAL_DIR/$PYTHON"
fi

rm -rf build dist
"$PYTHON" -m PyInstaller --clean --noconfirm tonie_gui.spec

echo
echo "Built: $(pwd)/dist/Tonie Audio Updater.app"
echo
echo "It is unsigned. The first time, right-click it and choose Open rather than"
echo "double-clicking, to get past Gatekeeper. macOS remembers the choice."
