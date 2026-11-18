#!/usr/bin/env bash
# Instala Dictado para el usuario actual (sin sudo).
#   ./install.sh          instalación normal
#   ./install.sh --dev    instala en modo editable (los cambios del repo se usan al momento)
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

# 1. Requisitos del sistema
for cmd in python3 pw-record ffmpeg gnome-extensions glib-compile-schemas; do
    command -v "$cmd" >/dev/null || fail "Falta '$cmd'. Mira la sección «Requisitos» del README."
done
python3 -c 'import gi' 2>/dev/null || fail "Falta python3-gi (sudo apt install python3-gi)."
PYVER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

# 2. Entorno de Python aislado (usa python3-gi del sistema)
if [[ ! -x "$VENV/bin/python" ]]; then
    say "Creando el entorno en $VENV"
    python3 -m venv --system-site-packages "$VENV" \
        || fail "No se pudo crear el entorno. Instala: sudo apt install python$PYVER-venv"
fi
say "Instalando Dictado y faster-whisper"
"$VENV/bin/pip" install -q --upgrade pip
if (( DEV )); then
    "$VENV/bin/pip" install -q -e "$REPO"
else
    "$VENV/bin/pip" install -q --upgrade "$REPO"
fi
mkdir -p "$(dirname "$BIN")"
ln -sf "$VENV/bin/dictado" "$BIN"

# 3. Configuración por defecto
"$VENV/bin/python" -c 'from dictado import config; config.write_default()'

# 4. Servicio: activación D-Bus + unidad de systemd (arranca al iniciar sesión)
say "Instalando el servicio D-Bus"
mkdir -p "$PREFIX/dbus-1/services" "$HOME/.config/systemd/user"
sed "s|@BIN@|$VENV/bin/dictado|" "$REPO/data/dev.dictado.Dictado.service.in" \
    > "$PREFIX/dbus-1/services/dev.dictado.Dictado.service"
sed "s|@BIN@|$VENV/bin/dictado|" "$REPO/data/dictado.service.in" \
    > "$HOME/.config/systemd/user/dictado.service"
systemctl --user daemon-reload
systemctl --user enable dictado.service >/dev/null 2>&1 || true
systemctl --user restart dictado.service || true

# 5. Extensión de GNOME Shell
say "Instalando la extensión de GNOME Shell"
rm -rf "$EXT_DIR"
mkdir -p "$EXT_DIR"
cp -r "$REPO/extension/$UUID/." "$EXT_DIR/"
glib-compile-schemas "$EXT_DIR/schemas"
gnome-extensions enable "$UUID" 2>/dev/null || true

# 6. Avisar si el atajo choca con otro de GNOME (no se cambia nada)
if gsettings list-recursively 2>/dev/null | grep -qiF "'<Super>j'"; then
    echo "Aviso: Super+J ya lo usa otro atajo de GNOME. Cámbialo en las preferencias de la extensión Dictado."
fi

# 7. Modelos (se descargan una sola vez a ~/.cache/huggingface)
say "Descargando los modelos de Whisper (solo la primera vez)"
"$VENV/bin/dictado" download

echo
say "Listo."
if ! gnome-extensions info "$UUID" 2>/dev/null | grep -qi "ACTIVE\|Activ"; then
    echo "  Cierra sesión y vuelve a entrar para que GNOME cargue la extensión."
    echo "  Después: gnome-extensions enable $UUID"
fi
echo "  Dictar: Super+J · Transcripción en vivo: Super+Shift+J · Archivos: dictado transcribe ARCHIVO"
