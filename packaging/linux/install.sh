#!/usr/bin/env bash
# Per-user installer for the LyricLoom Linux one-folder bundle.
#
# Usage:
#   ./install.sh              install into ~/.local
#   ./install.sh --uninstall  remove the app, launcher and menu entry
#
# Environment:
#   PREFIX                    installation prefix (default: ~/.local)
#   LYRICLOOM_INSTALL_DIR     full app directory override
#
# The install is entirely per-user: no sudo is required and nothing is written
# outside $PREFIX and the XDG applications directory.  User data (settings,
# logs, vocals and downloaded models) is left untouched by --uninstall.
set -euo pipefail

APP_NAME="LyricLoom"
PREFIX="${PREFIX:-$HOME/.local}"
APP_DIR="${LYRICLOOM_INSTALL_DIR:-$PREFIX/opt/LyricLoom}"
BIN_DIR="$PREFIX/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
SRC_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

case "${1:-}" in
    --uninstall|-u)
        rm -rf -- "$APP_DIR"
        rm -f -- "$BIN_DIR/lyricloom"
        rm -f -- "$DESKTOP_DIR/lyricloom.desktop"
        if command -v update-desktop-database >/dev/null 2>&1; then
            update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
        fi
        echo "Removed $APP_NAME from $APP_DIR."
        echo "Settings, logs and downloaded models were left in the LyricLoom data directory."
        exit 0
        ;;
    "")
        ;;
    *)
        echo "usage: $0 [--uninstall]" >&2
        exit 2
        ;;
esac

if [[ ! -d "$SRC_DIR/LyricLoom" ]]; then
    echo "LyricLoom/ was not found next to install.sh." >&2
    echo "Extract the complete tar.gz and run install.sh from its top level." >&2
    exit 1
fi

if [[ ! -f "$SRC_DIR/LyricLoom/LyricLoom" ]]; then
    echo "The LyricLoom executable is missing from the bundle." >&2
    exit 1
fi

chmod +x "$SRC_DIR/LyricLoom/LyricLoom" 2>/dev/null || true
mkdir -p -- "$PREFIX/opt" "$BIN_DIR" "$DESKTOP_DIR"

# Copy to a temporary directory first so a failed upgrade does not destroy a
# working installation.
STAGE_DIR="${APP_DIR}.new.$$"
rm -rf -- "$STAGE_DIR"
mkdir -p -- "$STAGE_DIR"
cp -a -- "$SRC_DIR/LyricLoom/." "$STAGE_DIR/"
install -m 0755 "$SRC_DIR/install.sh" "$STAGE_DIR/install.sh"
install -m 0644 "$SRC_DIR/LyricLoom.desktop" "$STAGE_DIR/LyricLoom.desktop"
rm -rf -- "$APP_DIR"
mv -- "$STAGE_DIR" "$APP_DIR"

# Command-line launcher.  The desktop entry uses the absolute path below, so
# ~/.local/bin does not have to be in PATH for menu launches.
cat > "$BIN_DIR/lyricloom" <<EOF
#!/bin/sh
exec "$APP_DIR/LyricLoom" "\$@"
EOF
chmod 0755 "$BIN_DIR/lyricloom"

# Install the menu entry with an absolute Exec path.  Escape '&' for sed.
EXEC_PATH="$APP_DIR/LyricLoom"
SED_EXEC_PATH="${EXEC_PATH//&/\\&}"
sed \
    -e "s|^Exec=.*|Exec=\"$SED_EXEC_PATH\"|" \
    "$SRC_DIR/LyricLoom.desktop" > "$DESKTOP_DIR/lyricloom.desktop"
chmod 0644 "$DESKTOP_DIR/lyricloom.desktop"

if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$DESKTOP_DIR/lyricloom.desktop" >/dev/null 2>&1 || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi

echo "Installed $APP_NAME in $APP_DIR"
echo "Launcher: $BIN_DIR/lyricloom"
echo "Menu entry: $DESKTOP_DIR/lyricloom.desktop"
echo "Models are downloaded by the app on first use."
