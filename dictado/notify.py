"""Desktop notifications that preview the text and open the file when clicked.

Uses org.freedesktop.Notifications directly. GNOME shows the actions as
buttons, the "default" action runs when the notification itself is clicked
(in the banner or in the message tray), and the `desktop-entry` hint gives it
Dictado's name and icon.
"""

from __future__ import annotations

import logging
from pathlib import Path

from gi.repository import Gio, GLib

log = logging.getLogger(__name__)

NAME = "org.freedesktop.Notifications"
PATH = "/org/freedesktop/Notifications"
DESKTOP_ID = "dev.dictado.App"


def preview(path: Path, lines: int = 3, limit: int = 220) -> str:
    """The first lines of text of a transcript (headers and timestamps skipped)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and "] " in line:
            line = line.split("] ", 1)[1]
        out.append(line)
        if len(out) == lines:
            break
    snippet = "\n".join(out)
    return snippet if len(snippet) <= limit else snippet[: limit - 1].rstrip() + "…"


def _escape(text: str) -> str:
    # GNOME renders a small subset of markup in the body.
    return GLib.markup_escape_text(text)


class Notifier:
    def __init__(self):
        self._bus: Gio.DBusConnection | None = None
        self._files: dict[int, Path] = {}
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION)
            self._bus.signal_subscribe(NAME, NAME, "ActionInvoked", PATH, None,
                                       Gio.DBusSignalFlags.NONE, self._on_action)
            self._bus.signal_subscribe(NAME, NAME, "NotificationClosed", PATH, None,
                                       Gio.DBusSignalFlags.NONE, self._on_closed)
        except Exception:  # noqa: BLE001
            log.debug("No session bus for notifications", exc_info=True)

    def send(self, summary: str, body: str = "", *, icon: str = "audio-input-microphone-symbolic",
             urgent: bool = False, file: Path | None = None) -> None:
        """Show a notification. With `file`, it previews the file's text and
        clicking it opens the file; a button shows it in its folder."""
        if not self._bus:
            return
        actions: list[str] = []
        if file:
            text = preview(file)
            body = _escape(text) if text else _escape(file.name)
            actions = ["default", "Open", "show-in-folder", "Show in Folder"]
        hints = {
            "urgency": GLib.Variant("y", 2 if urgent else 1),
            "desktop-entry": GLib.Variant("s", DESKTOP_ID),
        }

        def done(bus, res):
            try:
                (nid,) = bus.call_finish(res).unpack()
                if file:
                    self._files[nid] = file
            except Exception:  # noqa: BLE001
                log.debug("Could not notify", exc_info=True)

        self._bus.call(NAME, PATH, NAME, "Notify",
                       GLib.Variant("(susssasa{sv}i)", ("Dictado", 0, icon, summary, body,
                                                        actions, hints, -1)),
                       GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, -1, None, done)

    def _on_action(self, _c, _s, _p, _i, _sig, params):
        nid, action = params.unpack()
        path = self._files.get(nid)
        if not path:
            return
        if action == "show-in-folder":
            show_in_folder(path)
        else:
            open_file(path)

    def _on_closed(self, _c, _s, _p, _i, _sig, params):
        # Keep the mapping: GNOME "closes" a banner when it moves to the
        # message tray, and it can still be clicked there.
        pass


def open_file(path: Path) -> None:
    try:
        Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(str(path)).get_uri(), None)
    except GLib.Error:
        log.exception("Could not open %s", path)


def show_in_folder(path: Path) -> None:
    uri = Gio.File.new_for_path(str(path)).get_uri()
    try:
        Gio.bus_get_sync(Gio.BusType.SESSION).call_sync(
            "org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
            "org.freedesktop.FileManager1", "ShowItems",
            GLib.Variant("(ass)", ([uri], "")), None, Gio.DBusCallFlags.NONE, 5000, None)
    except GLib.Error:
        open_file(path.parent)
