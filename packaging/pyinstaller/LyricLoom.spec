# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build for LyricLoom.

Build from the repository root, using the project's Python 3.11 interpreter:

    python -m PyInstaller --noconfirm --clean packaging/pyinstaller/LyricLoom.spec

Output: ``dist/LyricLoom/`` with:

* ``LyricLoom.exe``        - windowed GUI
* ``LyricLoomWorker.exe``  - console worker (shared module graph)
* ``_internal/tools/bin/`` - whisper.cpp ``whisper-cli`` + ggml DLLs

The worker executable is a console build so its stdout result line can be read
by ``lyricloom.workers.run_worker``.  Both executables use the same Analysis and
therefore the same collected modules; the entry script dispatches on the
executable name.  This keeps the Linux ``--worker`` fallback functional.

Large model files are intentionally NOT bundled.  They are downloaded at
runtime into the per-user data directory handled by ``lyricloom.config``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

# SPECPATH is the directory containing this .spec file.
ROOT = Path(SPECPATH).resolve().parent.parent
IS_WINDOWS = sys.platform == "win32"
TOOLS_BIN = ROOT / "tools" / "bin"
ICON_FILE = ROOT / "packaging" / "windows" / "LyricLoom.ico"
VERSION_FILE = ROOT / "packaging" / "windows" / "version_info.txt"

datas: list[tuple[str, str]] = []
binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = []


def add_collection(package: str) -> None:
    """Collect package data, binaries and every importable submodule."""
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hidden)


def add_tree(source: Path, destination: str) -> None:
    """Copy a small source tree verbatim into the bundle.

    PyInstaller's datas entries are ``(source_file, destination_directory)``, not
    ``(source_file, destination_file)``; passing the file name as the destination would create a
    directory named ``utils.py`` and break the runtime import.
    """
    if not source.is_dir():
        return
    for path in sorted(source.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            relative_parent = path.relative_to(source).parent
            target = destination if str(relative_parent) == "." else f"{destination}/{relative_parent.as_posix()}"
            datas.append((str(path), target))


# --------------------------------------------------------------------------- heavy runtime
# audio-separator has JSON model databases and dynamically imported backends.
add_collection("audio_separator")
# torchaudio is used by the MMS forced-alignment worker (and by the vendored MTL code).
add_collection("torchaudio")
# The vendored LyricsAlignment-MTL wrapper imports librosa/g2p_en directly at runtime,
# so PyInstaller cannot discover those imports by following the module graph.
add_collection("fugashi")
add_collection("ipadic")
add_collection("pykakasi")
add_collection("soundfile")
# soundfile 0.13+ is a single module and keeps libsndfile in the separate
# _soundfile_data package; collect_all("soundfile") cannot see that package.
add_collection("_soundfile_data")
add_collection("soxr")
add_collection("imageio_ffmpeg")
add_collection("certifi")

hiddenimports += collect_submodules("mutagen")
hiddenimports += [
    "torch",
    "torchaudio",
    "onnxruntime",
    "onnxruntime.capi._pybind_state",
    "librosa",
    "resampy",
    "samplerate",
    "g2p_en",
    "nltk",
    "inflect",
    "unidecode",
]

# The vendored MTL package lives as source files under lyricloom/vendor/mtl.  It is
# imported by insert_path + ``import wrapper`` at runtime, not as a dotted package.
add_tree(ROOT / "lyricloom" / "vendor" / "mtl", "lyricloom/vendor/mtl")
datas.extend(collect_data_files("librosa"))
datas.extend(collect_data_files("g2p_en"))
datas.extend(collect_data_files("lyricloom", includes=["assets/*"]))

# All four worker modules are launched by name through importlib.
hiddenimports += [
    "lyricloom.workers.launcher",
    "lyricloom.workers.separate",
    "lyricloom.workers.align_ctc",
    "lyricloom.workers.align_mtl",
    "lyricloom.workers.download",
]

# --------------------------------------------------------------------------- Qt
# PySide6's hook collects the modules imported by the GUI.  The multimedia
# plugins are requested explicitly because playback is a core feature and the
# hook's plugin set has changed between Qt releases.
datas.extend(
    collect_data_files(
        "PySide6",
        includes=[
            "plugins/multimedia/*",
            "plugins/audio/*",
        ],
    )
)
# PySide6 wheels ship the FFmpeg runtime used by the multimedia plugin beside
# the Qt DLLs.  Collect it explicitly for Windows and Linux wheels.
for pattern in (
    "avcodec-*.dll",
    "avformat-*.dll",
    "avutil-*.dll",
    "swresample-*.dll",
    "swscale-*.dll",
    "avdevice-*.dll",
    "avfilter-*.dll",
    "libavcodec.so*",
    "libavformat.so*",
    "libavutil.so*",
    "libswresample.so*",
    "libswscale.so*",
):
    binaries.extend(collect_dynamic_libs("PySide6", search_patterns=[pattern]))

# --------------------------------------------------------------------------- whisper.cpp
# The helper is staged by scripts/build-windows.ps1 / scripts/build-linux.sh.
# It is deliberately not part of the repository (tools/bin is ignored).
whisper_files = []
if TOOLS_BIN.is_dir():
    for path in sorted(TOOLS_BIN.iterdir()):
        if not path.is_file():
            continue
        name = path.name.lower()
        if name.startswith(("whisper-cli", "whisper.dll", "ggml", "libwhisper", "libggml")):
            whisper_files.append(path)

whisper_cli = next((p for p in whisper_files if p.name.lower().startswith("whisper-cli")), None)
if whisper_cli is None:
    raise SystemExit(
        "whisper-cli was not found in tools/bin.\n"
        "Run scripts/build-windows.ps1 or scripts/build-linux.sh first "
        "(they build whisper.cpp v1.9.5 and stage the artifacts), or copy a "
        "prebuilt whisper-cli plus its ggml libraries into tools/bin."
    )

for path in whisper_files:
    datas.append((str(path), "tools/bin"))

# --------------------------------------------------------------------------- setup engine assets
# A frozen build sets up WSL itself: the script and a wheel of this exact version are bundled under
# _internal/wsl/.  scripts/build-windows.ps1 builds the wheel with
#   python -m pip wheel --no-deps . -w build\wsl
# before PyInstaller runs.  A source checkout builds nothing.
WSL_DIR = ROOT / "packaging" / "wsl"
WSL_BUILD = ROOT / "build" / "wsl"
WSL_SCRIPT = WSL_DIR / "setup-lyricloom-wsl.sh"
if not WSL_SCRIPT.is_file():
    raise SystemExit(f"the WSL setup script is missing: {WSL_SCRIPT}")
datas.append((str(WSL_SCRIPT), "wsl"))
wsl_wheels = sorted(WSL_BUILD.glob("lyricloom-*.whl"))
if wsl_wheels:
    datas.append((str(wsl_wheels[-1]), "wsl"))
elif IS_WINDOWS:
    raise SystemExit(
        "build/wsl/ has no LyricLoom wheel.\n"
        "Build it first with: python -m pip wheel --no-deps . -w build\\wsl"
    )
# The probe is sent to WSL interpreters on stdin, so it must exist as a source file too.
PROBE_SCRIPT = ROOT / "lyricloom" / "workers" / "probe_gpu.py"
if not PROBE_SCRIPT.is_file():
    raise SystemExit(f"the WSL GPU probe is missing: {PROBE_SCRIPT}")
datas.append((str(PROBE_SCRIPT), "lyricloom/workers"))
hiddenimports += ["lyricloom.setup"]

# --------------------------------------------------------------------------- Analysis and executables
entry_script = ROOT / "packaging" / "pyinstaller" / "entry.py"
icon = str(ICON_FILE) if ICON_FILE.is_file() else None
version = str(VERSION_FILE) if IS_WINDOWS and VERSION_FILE.is_file() else None

a = Analysis(
    [str(entry_script)],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe_gui = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LyricLoom",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
    version=version,
)

exe_worker = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LyricLoomWorker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
    version=version,
)

coll = COLLECT(
    exe_gui,
    exe_worker,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LyricLoom",
)
