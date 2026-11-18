#!/usr/bin/env bash
# Desinstala Dictado. No borra tus dictados, transcripciones ni los modelos
# descargados (~/.cache/huggingface).
set -uo pipefail
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}"
UUID="dictado@dictado.dev"
gnome-extensions disable "$UUID" 2>/dev/null
systemctl --user disable --now dictado.service 2>/dev/null
rm -f "$HOME/.config/systemd/user/dictado.service" "$PREFIX/dbus-1/services/dev.dictado.Dictado.service"
systemctl --user daemon-reload
rm -rf "$PREFIX/gnome-shell/extensions/$UUID" "$PREFIX/dictado"
rm -f "$HOME/.local/bin/dictado"
echo "Dictado desinstalado. La configuración sigue en ~/.config/dictado."
