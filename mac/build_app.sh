#!/usr/bin/env bash
# Build the SwiftUI app bundle. Needs only the Xcode command line tools.
set -euo pipefail
cd "$(dirname "$0")"

APP="dist/Tonie Audio Updater.app"
VERSION="${VERSION:-6.0}"

swift build -c release --product TonieUpdater
BIN="$(swift build -c release --show-bin-path)/TonieUpdater"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/TonieUpdater"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Tonie Audio Updater</string>
    <key>CFBundleDisplayName</key><string>Tonie Audio Updater</string>
    <key>CFBundleIdentifier</key><string>com.muddro1.tonie-audio-updater</string>
    <key>CFBundleExecutable</key><string>TonieUpdater</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>${VERSION}</string>
    <key>CFBundleVersion</key><string>${VERSION}</string>
    <key>LSMinimumSystemVersion</key><string>14.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSPrincipalClass</key><string>NSApplication</string>
</dict>
</plist>
PLIST

# Ad hoc: enough for this Mac's Keychain to recognise the app between launches
codesign --force --sign - "$APP"

echo
echo "Built: $(pwd)/$APP"
echo "It is not notarized. The first time, right-click it and choose Open."
