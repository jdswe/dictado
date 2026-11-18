"""Fake D-Bus service: checks the connection with the extension."""
import sys
from pathlib import Path

from gi.repository import Gio, GLib

xml = (Path(__file__).resolve().parents[2] / "dictado" / "dev.dictado.Dictado1.xml").read_text()
node = Gio.DBusNodeInfo.new_for_xml(xml)
loop = GLib.MainLoop()
conn = None
calls = []


def emit(name, sig, *args):
    conn.emit_signal(None, "/dev/dictado/Dictado", "dev.dictado.Dictado1", name, GLib.Variant(f"({sig})", args))


def on_call(_c, _s, _p, _i, method, params, inv):
    calls.append(method)
    print("llamada:", method, flush=True)
    inv.return_value(None)


def get_prop(_c, _s, _p, _i, prop):
    return {"Dictation": GLib.Variant("s", "idle"), "Transcription": GLib.Variant("s", "idle"),
            "TranscriptPath": GLib.Variant("s", ""), "TranscriptionStarted": GLib.Variant("x", 0),
            "ModelReady": GLib.Variant("b", True)}.get(prop)


def on_bus(c, _n):
    global conn
    conn = c
    c.register_object("/dev/dictado/Dictado", node.interfaces[0], on_call, get_prop, None)


def script():
    emit("StateChanged", "ss", "recording", "idle")
    for lvl in (0.2, 0.8, 0.5):
        emit("Level", "d", lvl)
    emit("StateChanged", "ss", "processing", "idle")
    emit("DictationText", "ss", "Hola mundo", "es")
    emit("StateChanged", "ss", "idle", "recording")
    GLib.timeout_add(1500, lambda: (emit("StateChanged", "ss", "idle", "idle"), print("signals sent", flush=True), False)[2])
    return False


Gio.bus_own_name(Gio.BusType.SESSION, "dev.dictado.Dictado", Gio.BusNameOwnerFlags.NONE, on_bus,
                 lambda *a: GLib.timeout_add(1000, script), lambda *a: sys.exit("nombre ocupado"))
GLib.timeout_add_seconds(8, loop.quit)
loop.run()
