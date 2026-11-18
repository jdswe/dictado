#!/bin/bash
# Carga la extensión en un GNOME Shell aislado e invisible (sin tocar la sesión
# real: bus, ajustes y carpetas propios) y comprueba que se activa sin errores
# y que el atajo de dictado habla con un servicio falso por D-Bus.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
uuid=dictado@dictado.dev
ext="$work/data/gnome-shell/extensions/$uuid"
mkdir -p "$ext" "$work/config"
cp -r "$repo/extension/$uuid/." "$ext/"
glib-compile-schemas "$ext/schemas"

env XDG_CONFIG_HOME="$work/config" XDG_DATA_HOME="$work/data" REPO="$repo" \
    dbus-run-session -- bash -c "
    dconf write /org/gnome/shell/enabled-extensions \"['$uuid']\"
    dconf write /org/gnome/shell/disable-user-extensions false
    gnome-shell --headless --virtual-monitor 1280x800 --wayland > '$work/shell.log' 2>&1 &
    shell=\$!
    for i in \$(seq 60); do
        gdbus call --session -d org.gnome.Shell -o /org/gnome/Shell -m org.freedesktop.DBus.Peer.Ping >/dev/null 2>&1 && break
        sleep 0.5
    done
    sleep 3
    python3 '$here/fake_service.py' > '$work/fake.log' 2>&1 &
    fake=\$!
    sleep 1
    echo \"estado: \$(gdbus call --session -d org.gnome.Shell -o /org/gnome/Shell -m org.gnome.Shell.Extensions.GetExtensionInfo $uuid | grep -o \"'state': <[0-9.]*>\")\"
    # El servicio falso emite estados, niveles y un DictationText: la extensión
    # debe reaccionar (píldora, indicador, pegar) sin errores de JS.
    sleep 4
    kill \$fake 2>/dev/null; sleep 1
    kill \$shell 2>/dev/null; wait \$shell 2>/dev/null || true
"
echo '--- servicio falso'; cat "$work/fake.log"
echo '--- errores JS'
grep -A6 -E "JS ERROR|Dictado|dictado" "$work/shell.log" | grep -v '^--$' | head -40 || true
