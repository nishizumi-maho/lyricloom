#!/usr/bin/env bash
# Creates .venv with Python 3.11 and installs LyricLoom in editable mode with
# test/build extras.  CPU-only torch wheels are used for public builds.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -n "${PYTHON:-}" ]]; then
    PYTHON_BIN="$PYTHON"
elif command -v python3.11 >/dev/null 2>&1; then
    PYTHON_BIN="python3.11"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "Python 3.11 was not found on PATH." >&2
    exit 1
fi

VERSION="$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
if [[ "$VERSION" != "3.11" ]]; then
    echo "Found Python $VERSION; LyricLoom requires Python 3.11." >&2
    echo "Set PYTHON=/path/to/python3.11 or install Python 3.11." >&2
    exit 1
fi

if [[ ! -x ".venv/bin/python" ]]; then
    if [[ -d ".venv" ]]; then
        echo ".venv exists but does not contain bin/python. Remove it and re-run." >&2
        exit 1
    fi
    echo "Creating .venv with $PYTHON_BIN..."
    "$PYTHON_BIN" -m venv .venv
fi

PY=".venv/bin/python"
VENV_VERSION="$("$PY" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
if [[ "$VENV_VERSION" != "3.11" ]]; then
    echo ".venv uses Python $VENV_VERSION; remove it and re-run this script." >&2
    exit 1
fi

"$PY" -m pip install --upgrade pip setuptools wheel
echo "Installing CPU-only torch/torchaudio..."
"$PY" -m pip install "torch==2.4.1" "torchaudio==2.4.1" --index-url https://download.pytorch.org/whl/cpu
echo "Installing LyricLoom in editable mode with dev extras..."
"$PY" -m pip install -e ".[dev]"
"$PY" -m pip check

# audio-separator invokes `ffmpeg`; link imageio-ffmpeg's static binary into the
# venv when the system does not already provide one.  A system ffmpeg is fine.
if ! command -v ffmpeg >/dev/null 2>&1; then
    FFMPEG="$("$PY" -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())" 2>/dev/null || true)"
    if [[ -n "$FFMPEG" && -x "$FFMPEG" ]]; then
        ln -sf "$FFMPEG" .venv/bin/ffmpeg
        echo "ffmpeg shim installed: .venv/bin/ffmpeg"
    fi
fi

cat <<EOF

Development environment ready.
  GUI:  .venv/bin/lyricloom-app
  CLI:  .venv/bin/lyricloom
Models are downloaded by the app on first use; they are not installed by this script.
EOF
