#!/usr/bin/env bash
# Install Dictado for the current user (no sudo).
#   ./install.sh          normal install
#   ./install.sh --dev    editable install (changes in the repo apply at once)
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}"
VENV="$PREFIX/dictado/venv"
BIN="$HOME/.local/bin/dictado"
UUID="dictado@dictado.dev"
EXT_DIR="$PREFIX/gnome-shell/extensions/$UUID"
DEV=0
[[ "${1:-}" == "--dev" ]] && DEV=1

say() { printf '\033[1m→ %s\033[0m\n' "$*"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# 1. System requirements
for cmd in python3 pw-record ffmpeg gnome-extensions glib-compile-schemas; do
    command -v "$cmd" >/dev/null || fail "Missing '$cmd'. See «Requirements» in the README."
done
python3 -c 'import gi' 2>/dev/null || fail "Missing python3-gi (sudo apt install python3-gi)."
PYVER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

# 2. Isolated Python environment (uses the system's python3-gi)
if [[ ! -x "$VENV/bin/python" ]]; then
    say "Creating the environment in $VENV"
    python3 -m venv --system-site-packages "$VENV" \
        || fail "Could not create the environment. Install: sudo apt install python$PYVER-venv"
fi
say "Installing Dictado and faster-whisper"
"$VENV/bin/pip" install -q --upgrade pip
if (( DEV )); then
    "$VENV/bin/pip" install -q -e "$REPO"
else
    "$VENV/bin/pip" install -q --upgrade "$REPO"
fi
mkdir -p "$(dirname "$BIN")"
ln -sf "$VENV/bin/dictado" "$BIN"

# 3. Default settings (an untouched 0.1.0 config is upgraded to English)
"$VENV/bin/python" -c 'from dictado import config; config.write_default()'

# Version 0.1.0 used Spanish folder names: move them if the new ones don't exist
# and the config doesn't point at the old ones.
for pair in "Dictados:Dictations" "Transcripciones:Transcripts"; do
    old="$HOME/Documents/${pair%%:*}"
    new="$HOME/Documents/${pair##*:}"
    if [[ -d "$old" && ! -e "$new" ]] \
        && ! grep -q "Documents/${pair%%:*}" "$HOME/.config/dictado/config.toml" 2>/dev/null; then
        mv "$old" "$new" && echo "  Moved $old → $new"
    fi
done

# 4. Service: D-Bus activation + systemd unit (starts at login)
say "Installing the D-Bus service"
mkdir -p "$PREFIX/dbus-1/services" "$HOME/.config/systemd/user"
sed "s|@BIN@|$VENV/bin/dictado|" "$REPO/data/dev.dictado.Dictado.service.in" \
    > "$PREFIX/dbus-1/services/dev.dictado.Dictado.service"
sed "s|@BIN@|$VENV/bin/dictado|" "$REPO/data/dictado.service.in" \
    > "$HOME/.config/systemd/user/dictado.service"
systemctl --user daemon-reload
systemctl --user enable dictado.service >/dev/null 2>&1 || true
systemctl --user restart dictado.service || true

# 5. GNOME Shell extension
say "Installing the GNOME Shell extension"
rm -rf "$EXT_DIR"
mkdir -p "$EXT_DIR"
cp -r "$REPO/extension/$UUID/." "$EXT_DIR/"
glib-compile-schemas "$EXT_DIR/schemas"
# If GNOME doesn't know the extension yet (on Wayland, until you log in
# again), add it to the enabled list so it loads at the next login.
gnome-extensions enable "$UUID" 2>/dev/null || python3 - "$UUID" <<'PY'
import ast, subprocess, sys
cur = ast.literal_eval(subprocess.check_output(
    ["gsettings", "get", "org.gnome.shell", "enabled-extensions"], text=True).replace("@as ", ""))
if sys.argv[1] not in cur:
    subprocess.check_call(["gsettings", "set", "org.gnome.shell", "enabled-extensions", str(cur + [sys.argv[1]])])
PY

# 6. Warn if the shortcut clashes with a GNOME one (nothing is changed)
if gsettings list-recursively 2>/dev/null | grep -qiF "'<Super>j'"; then
    echo "Note: another GNOME shortcut already uses Super+J. Change it in Dictado's extension settings."
fi

# 7. Models (downloaded once to ~/.cache/huggingface)
say "Downloading the Whisper models (first time only)"
"$VENV/bin/dictado" download

echo
say "Done."
echo "  Log out and back in so GNOME loads the new extension."
echo "  Dictate: Super+J · Live transcript: Super+Shift+J · Files: dictado transcribe FILE"
