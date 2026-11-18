#!/bin/bash
# Loads the extension in an isolated, invisible GNOME Shell (without touching
# the real session: its own bus, settings and folders) and checks that it
# enables without errors and talks to a fake service over D-Bus.
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
    echo \"state: \$(gdbus call --session -d org.gnome.Shell -o /org/gnome/Shell -m org.gnome.Shell.Extensions.GetExtensionInfo $uuid | grep -o \"'state': <[0-9.]*>\")\"
    # The fake service emits states, levels and a DictationText: the
    # extension must react (pill, indicator, paste) without JS errors.
    sleep 4
    kill \$fake 2>/dev/null; sleep 1
    kill \$shell 2>/dev/null; wait \$shell 2>/dev/null || true
"
echo '--- fake service'; cat "$work/fake.log"
echo '--- JS errors'
grep -A6 -E "JS ERROR|Dictado|dictado" "$work/shell.log" | grep -v '^--$' | head -40 || true
