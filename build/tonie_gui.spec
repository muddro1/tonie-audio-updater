# PyInstaller spec for the Tonie Audio Updater GUI.
#
# Build with: ./build/build_app.sh
#
# The result is unsigned. macOS will refuse to open it on a double click the first
# time; right-click and choose Open, which offers the override, and the choice sticks.
#
# Written against PyInstaller 6.x. Older PyInstaller (5.x) spec files pass a
# `cipher=` to Analysis/PYZ and a.zipped_data/a.zipfiles to PYZ/COLLECT for
# bytecode encryption; that feature was removed in PyInstaller 6, so none of that
# appears below.
import os

# SPECPATH is the directory holding this spec file, which PyInstaller defines however
# it was invoked - so the build does not depend on being started from inside build/.
PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(PROJECT_ROOT, "gui", "__main__.py")],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=["tony"],
    hookspath=[],
    runtime_hooks=[],
    # FFmpeg and yt-dlp are deliberately not bundled; the app detects them
    excludes=["tkinter", "matplotlib", "numpy"],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Tonie Audio Updater",
    console=False,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    name="Tonie Audio Updater",
)

app = BUNDLE(
    coll,
    name="Tonie Audio Updater.app",
    bundle_identifier="com.muddro1.tonie-audio-updater",
    info_plist={
        "CFBundleShortVersionString": "4.1",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "13.0",
    },
)
