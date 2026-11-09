#!/usr/bin/env bash
# Per-user installer for the LyricLoom Linux one-folder bundle.
#
# Usage:
#   ./install.sh              install into ~/.local
#   ./install.sh --uninstall  remove the app, launcher and menu entry; asks once
#                             (default No) whether to remove LyricLoom's data
#   ./install.sh --purge      remove the app and LyricLoom's data without asking
#
# Environment:
#   PREFIX                    installation prefix (default: ~/.local)
#   LYRICLOOM_INSTALL_DIR     full app directory override; must be a dedicated
#                             directory named LyricLoom
#
# The install is entirely per-user: no sudo is required and nothing is written
# outside $PREFIX and the XDG applications directory.  User data is never
# deleted by --uninstall unless you answer yes or use --purge.  The music
# library and the .lrc files next to the music are never touched.
set -euo pipefail

APP_NAME="LyricLoom"
PREFIX="${PREFIX:-$HOME/.local}"
APP_DIR="${LYRICLOOM_INSTALL_DIR:-$PREFIX/opt/LyricLoom}"
BIN_DIR="$PREFIX/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DATA_DIR_DEFAULT="${XDG_DATA_HOME:-$HOME/.local/share}/lyricloom"
DATA_DIR="${LYRICLOOM_DATA_DIR:-$DATA_DIR_DEFAULT}"
SRC_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

die() {
    echo "$*" >&2
    exit 1
}

validate_app_dir() {
    local dir="$1" depth=0 part
    [[ -n "$dir" ]] || die "Refusing to use an empty installation directory."
    case "$dir" in
        /|"$HOME"|"$HOME/"|.|..)
            die "Refusing to use '$dir' as the installation directory: it is not a LyricLoom folder."
            ;;
    esac
    case "/$dir/" in
        */../*)
            die "Refusing to use '$dir' as the installation directory: '..' is not allowed."
            ;;
    esac
    [[ "$(basename -- "$dir")" == "$APP_NAME" ]] || \
        die "Refusing to use '$dir' as the installation directory: its last component must be '$APP_NAME'."
    local IFS='/'
    for part in $dir; do
        [[ -n "$part" ]] && depth=$((depth + 1))
    done
    unset IFS
    (( depth >= 3 )) || \
        die "Refusing to use '$dir' as the installation directory: it is too close to the filesystem root."
}

json_value() {
    # Reads a string value from settings.json without requiring Python.
    local file="$1" key="$2"
    [[ -f "$file" ]] || return 0
    sed -n 's/.*"'"$key"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$file" | head -n 1
}

normalize_dir() {
    local value="$1"
    value="${value//\\//}"
    while [[ "$value" == */ && "$value" != "/" ]]; do
        value="${value%/}"
    done
    printf '%s' "$value"
}

same_dir() {
    [[ "$(normalize_dir "$1")" == "$(normalize_dir "$2")" ]]
}

is_inside_dir() {
    local child parent
    child="$(normalize_dir "$1")"
    parent="$(normalize_dir "$2")"
    [[ "$child" == "$parent"/* ]]
}

show_data_plan() {
    local settings="$DATA_DIR/settings.json"
    local models vocals work custom=""
    models="$(json_value "$settings" models)"
    vocals="$(json_value "$settings" vocals)"
    work="$(json_value "$settings" work)"
    [[ -n "$models" ]] || models="$DATA_DIR/models"
    [[ -n "$vocals" ]] || vocals="$DATA_DIR/vocals"
    [[ -n "$work" ]] || work="$DATA_DIR/work"

    echo
    echo "LyricLoom's data:"
    echo "  settings, logs and scan cache: $DATA_DIR"
    echo "  work cache: $work"
    echo "  kept vocals: $vocals"
    echo "  models: $models"
    echo "  AssemblyAI key: $DATA_DIR/assemblyai.key"

    if [[ -n "${LYRICLOOM_DATA_DIR:-}" ]] && ! same_dir "$LYRICLOOM_DATA_DIR" "$DATA_DIR_DEFAULT"; then
        custom+="  data (LYRICLOOM_DATA_DIR): $LYRICLOOM_DATA_DIR"$'\n'
    fi
    if [[ -n "${LYRICLOOM_MODELS:-}" ]] && ! same_dir "$LYRICLOOM_MODELS" "$DATA_DIR/models"; then
        custom+="  models (LYRICLOOM_MODELS): $LYRICLOOM_MODELS"$'\n'
    fi
    if [[ -n "${LYRICLOOM_WORK:-}" ]] && ! same_dir "$LYRICLOOM_WORK" "$DATA_DIR/work"; then
        custom+="  work cache (LYRICLOOM_WORK): $LYRICLOOM_WORK"$'\n'
    fi
    if ! same_dir "$models" "$DATA_DIR/models"; then
        custom+="  models: $models"$'\n'
    fi
    if ! same_dir "$vocals" "$DATA_DIR/vocals"; then
        custom+="  kept vocals: $vocals"$'\n'
    fi
    if ! same_dir "$work" "$DATA_DIR/work"; then
        custom+="  work cache: $work"$'\n'
    fi
    if [[ -n "$custom" ]]; then
        echo
        echo "These custom or environment-provided folders are not LyricLoom default locations:"
        printf '%s' "$custom"
        echo "They are left alone; remove them by hand if you want to."
    fi
    echo
    echo "Your music library and the .lrc files next to your music are never deleted."
}

custom_inside_data() {
    local settings="$DATA_DIR/settings.json" key value default
    for key in models vocals work; do
        value="$(json_value "$settings" "$key")"
        default="$DATA_DIR/$key"
        if [[ -n "$value" ]] && ! same_dir "$value" "$default" && is_inside_dir "$value" "$DATA_DIR"; then
            return 0
        fi
    done
    for value in "${LYRICLOOM_MODELS:-}" "${LYRICLOOM_WORK:-}"; do
        if [[ -n "$value" ]] && is_inside_dir "$value" "$DATA_DIR"; then
            return 0
        fi
    done
    return 1
}

purge_data() {
    if [[ -n "${LYRICLOOM_DATA_DIR:-}" ]]; then
        echo "Left ${LYRICLOOM_DATA_DIR} in place: LYRICLOOM_DATA_DIR is environment-provided."
        return
    fi
    local library
    library="$(json_value "$DATA_DIR/settings.json" library)"
    if [[ -n "$library" ]] && { same_dir "$library" "$DATA_DIR" || is_inside_dir "$library" "$DATA_DIR"; }; then
        echo "Your music library is inside $DATA_DIR ($library)."
        echo "Refusing to delete the data folder, because that would delete your music."
        echo "Remove the LyricLoom data files by hand if you want to."
        return
    fi
    if custom_inside_data; then
        echo "A configured models, vocals or work folder is inside $DATA_DIR but is not a"
        echo "LyricLoom default location. Refusing to delete the data folder; remove it by hand."
        return
    fi
    if [[ -d "$DATA_DIR" ]]; then
        rm -rf -- "$DATA_DIR"
        echo "Removed $DATA_DIR."
    fi
}

validate_app_dir "$APP_DIR"

case "${1:-}" in
    --uninstall|-u)
        rm -rf -- "$APP_DIR"
        rm -f -- "$BIN_DIR/lyricloom"
        rm -f -- "$DESKTOP_DIR/lyricloom.desktop"
        if command -v update-desktop-database >/dev/null 2>&1; then
            update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
        fi
        echo "Removed $APP_NAME from $APP_DIR."
        show_data_plan
        answer=""
        if [[ -t 0 ]]; then
            printf '\nAlso delete LyricLoom data folders? [y/N] '
            read -r answer || answer=""
        else
            echo "LyricLoom data folders were kept. Run $0 --purge to remove them."
            exit 0
        fi
        case "$answer" in
            y|Y|yes|YES)
                purge_data
                ;;
            *)
                echo "LyricLoom data folders were kept."
                ;;
        esac
        exit 0
        ;;
    --purge)
        rm -rf -- "$APP_DIR"
        rm -f -- "$BIN_DIR/lyricloom"
        rm -f -- "$DESKTOP_DIR/lyricloom.desktop"
        if command -v update-desktop-database >/dev/null 2>&1; then
            update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
        fi
        echo "Removed $APP_NAME from $APP_DIR."
        show_data_plan
        purge_data
        exit 0
        ;;
    "")
        ;;
    *)
        echo "usage: $0 [--uninstall|--purge]" >&2
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

# Copy to a temporary directory first, then swap it in. The old installation is
# restored if the new one cannot be moved into place.
STAGE_DIR="${APP_DIR}.new.$$"
OLD_DIR="${APP_DIR}.old.$$"
rm -rf -- "$STAGE_DIR" "$OLD_DIR"
mkdir -p -- "$STAGE_DIR"
cp -a -- "$SRC_DIR/LyricLoom/." "$STAGE_DIR/"
install -m 0755 "$SRC_DIR/install.sh" "$STAGE_DIR/install.sh"
install -m 0644 "$SRC_DIR/LyricLoom.desktop" "$STAGE_DIR/LyricLoom.desktop"
if [[ -d "$APP_DIR" ]]; then
    mv -- "$APP_DIR" "$OLD_DIR"
fi
if ! mv -- "$STAGE_DIR" "$APP_DIR"; then
    rm -rf -- "$STAGE_DIR"
    if [[ -d "$OLD_DIR" ]]; then
        mv -- "$OLD_DIR" "$APP_DIR" || true
    fi
    die "Could not move the new installation into $APP_DIR. The previous installation was restored."
fi
rm -rf -- "$OLD_DIR"

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
