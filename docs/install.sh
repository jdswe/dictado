#!/usr/bin/env bash
# One-line installer for Dictado:
#   curl -fsSL https://jdswe.github.io/dictado/install.sh | bash
# Downloads the latest GitHub release, checks its SHA-256 fingerprint
# and runs its install.sh (no sudo).
set -euo pipefail

REPO="jdswe/dictado"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/dictado/src"

say() { printf '\033[1m→ %s\033[0m\n' "$*"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

for cmd in curl tar python3 sha256sum; do
    command -v "$cmd" >/dev/null || fail "Missing '$cmd'."
done
python3 -c 'import venv, ensurepip' 2>/dev/null \
    || fail "python3-venv is missing. Install it with: sudo apt install python3-venv ffmpeg"

say "Looking up the latest release"
read -r TAG URL DIGEST < <(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" | python3 -c '
import json, sys
r = json.load(sys.stdin)
a = next(a for a in r["assets"] if a["name"].endswith(".tar.gz"))
print(r["tag_name"], a["browser_download_url"], (a.get("digest") or "").removeprefix("sha256:") or "-")
')

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
say "Downloading Dictado $TAG"
curl -fsSL "$URL" -o "$tmp/dictado.tar.gz"
if [[ "$DIGEST" != "-" ]]; then
    echo "$DIGEST  $tmp/dictado.tar.gz" | sha256sum -c --quiet - || fail "SHA-256 fingerprint does not match."
fi

rm -rf "$DEST"
mkdir -p "$DEST"
tar -xzf "$tmp/dictado.tar.gz" -C "$DEST" --strip-components=1
cd "$DEST"
./install.sh
