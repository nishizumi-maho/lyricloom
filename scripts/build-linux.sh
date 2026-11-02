#!/usr/bin/env bash
# Builds the Linux release: whisper.cpp helper, PyInstaller one-folder app,
# .desktop file, install script, tar.gz and SHA256 checksum.
#
# Prerequisites:
#   * Python 3.11 and .venv from scripts/setup-dev.sh
#   * cmake, ninja, a C++ compiler and git (for whisper.cpp)
#   * tar and sha256sum
#   * Optional Vulkan SDK/loader (detected automatically; otherwise CPU)
#
# Run from anywhere:
#   bash scripts/build-linux.sh
#
# Environment:
#   LYRICLOOM_WHISPER_VULKAN=auto|1|0   default auto (Vulkan when VULKAN_SDK+glslc)
#
# Outputs under dist/:
#   LyricLoom/                                   PyInstaller one-folder bundle
#   LyricLoom-<version>-linux-x86_64.tar.gz      release archive
#   LyricLoom-<version>-linux-x86_64.tar.gz.sha256
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
    echo "Python virtual environment not found at $PYTHON." >&2
    echo "Run scripts/setup-dev.sh first, or set PYTHON=/path/to/python3.11." >&2
    exit 1
fi

PY_VERSION="$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
if [[ "$PY_VERSION" != "3.11" ]]; then
    echo "The build environment uses Python $PY_VERSION; LyricLoom requires Python 3.11." >&2
    exit 1
fi

VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' lyricloom/__init__.py | head -n 1)"
if [[ -z "$VERSION" ]]; then
    echo "Could not read VERSION from lyricloom/__init__.py." >&2
    exit 1
fi

DIST="$ROOT/dist"
BUILD="$ROOT/build"
TOOLS_BIN="$ROOT/tools/bin"
WHISPER_CLI="$TOOLS_BIN/whisper-cli"
WHISPER_SRC="$ROOT/tools/src/whisper.cpp"

# --------------------------------------------------------------------------- whisper.cpp
if [[ ! -f "$WHISPER_CLI" ]]; then
    for tool in git cmake ninja; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            echo "Missing build tool: $tool" >&2
            echo "On Debian/Ubuntu: sudo apt install build-essential cmake ninja-build git" >&2
            exit 1
        fi
    done

    VULKAN_MODE="${LYRICLOOM_WHISPER_VULKAN:-auto}"
    case "$VULKAN_MODE" in
        1|on|ON|true|TRUE)
            VULKAN=ON
            ;;
        0|off|OFF|false|FALSE)
            VULKAN=OFF
            ;;
        auto|AUTO|"")
            if [[ -n "${VULKAN_SDK:-}" ]] && command -v glslc >/dev/null 2>&1; then
                VULKAN=ON
            else
                VULKAN=OFF
            fi
            ;;
        *)
            echo "LYRICLOOM_WHISPER_VULKAN must be auto, 1 or 0." >&2
            exit 2
            ;;
    esac

    echo "Building whisper.cpp v1.9.5 ($([[ "$VULKAN" == "ON" ]] && echo Vulkan || echo CPU))..."
    if [[ ! -d "$WHISPER_SRC" ]]; then
        mkdir -p "$(dirname "$WHISPER_SRC")"
        git clone --depth 1 --branch v1.9.5 https://github.com/ggml-org/whisper.cpp.git "$WHISPER_SRC"
    fi

    JOBS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)"
    cmake -S "$WHISPER_SRC" -B "$WHISPER_SRC/build" -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_SHARED_LIBS=OFF \
        -DWHISPER_BUILD_TESTS=OFF \
        -DWHISPER_BUILD_EXAMPLES=ON \
        "-DGGML_VULKAN=$VULKAN"
    cmake --build "$WHISPER_SRC/build" --config Release --parallel "$JOBS"

    BUILT_CLI="$WHISPER_SRC/build/bin/whisper-cli"
    if [[ ! -f "$BUILT_CLI" ]]; then
        BUILT_CLI="$(find "$WHISPER_SRC/build" -type f -name whisper-cli -print -quit)"
    fi
    if [[ ! -f "$BUILT_CLI" ]]; then
        echo "whisper-cli was not produced by the whisper.cpp build." >&2
        exit 1
    fi

    mkdir -p "$TOOLS_BIN"
    cp -f "$BUILT_CLI" "$WHISPER_CLI"
    chmod 0755 "$WHISPER_CLI"
fi

chmod 0755 "$WHISPER_CLI" 2>/dev/null || true
if [[ ! -f "$WHISPER_CLI" ]]; then
    echo "whisper-cli is missing from $TOOLS_BIN." >&2
    exit 1
fi

# --------------------------------------------------------------------------- PyInstaller
if ! "$PYTHON" -c "import PyInstaller" >/dev/null 2>&1; then
    echo "PyInstaller is not installed. Run scripts/setup-dev.sh first." >&2
    exit 1
fi

echo "Building LyricLoom $VERSION with PyInstaller..."
mkdir -p "$DIST" "$BUILD"
rm -rf "$DIST/LyricLoom" "$BUILD/LyricLoom"
"$PYTHON" -m PyInstaller --noconfirm --clean --distpath "$DIST" --workpath "$BUILD" \
    "$ROOT/packaging/pyinstaller/LyricLoom.spec"

if [[ ! -f "$DIST/LyricLoom/LyricLoom" ]]; then
    echo "PyInstaller did not produce dist/LyricLoom/LyricLoom." >&2
    exit 1
fi
if [[ ! -f "$DIST/LyricLoom/LyricLoomWorker" ]]; then
    echo "PyInstaller did not produce dist/LyricLoom/LyricLoomWorker." >&2
    exit 1
fi
chmod 0755 "$DIST/LyricLoom/LyricLoom"

# --------------------------------------------------------------------------- release archive
STAGE_NAME="LyricLoom-$VERSION-linux-x86_64"
STAGE="$DIST/$STAGE_NAME"
ARCHIVE="$DIST/$STAGE_NAME.tar.gz"

rm -rf "$STAGE" "$ARCHIVE"
mkdir -p "$STAGE"
cp -a "$DIST/LyricLoom" "$STAGE/LyricLoom"
cp -f "$ROOT/packaging/linux/install.sh" "$STAGE/install.sh"
cp -f "$ROOT/packaging/linux/LyricLoom.desktop" "$STAGE/LyricLoom.desktop"
chmod 0755 "$STAGE/install.sh" "$STAGE/LyricLoom/LyricLoom"

echo "Creating $ARCHIVE..."
tar -C "$DIST" -czf "$ARCHIVE" "$STAGE_NAME"
if command -v sha256sum >/dev/null 2>&1; then
    (cd "$DIST" && sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256")
else
    (cd "$DIST" && shasum -a 256 "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256")
fi
rm -rf "$STAGE"

echo ""
echo "Linux build complete (whisper.cpp: $([[ -n "${VULKAN:-}" ]] && echo "$VULKAN" || echo prebuilt))."
echo "  App:     $DIST/LyricLoom"
echo "  Archive: $ARCHIVE"
echo "  Install: extract the archive and run ./install.sh"
