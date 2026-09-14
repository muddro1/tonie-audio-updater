#!/usr/bin/env bash
# Build the unsigned .app bundle.
set -euo pipefail

cd "$(dirname "$0")"

rm -rf build dist
# Run through the interpreter rather than the "pyinstaller" console script, which
# is only on PATH when the venv holding it is active. PYTHON overrides which one.
"${PYTHON:-python3}" -m PyInstaller --clean --noconfirm tonie_gui.spec

echo
echo "Built: $(pwd)/dist/Tonie Audio Updater.app"
echo
echo "It is unsigned. The first time, right-click it and choose Open rather than"
echo "double-clicking, to get past Gatekeeper. macOS remembers the choice."
