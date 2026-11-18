"""Command line: `dictado serve | toggle | transcribe FILE | ...`."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from dictado import BUS_NAME, INTERFACE, OBJECT_PATH, __version__


def _call(method: str, args=None, sig: str | None = None, timeout: int = 30000):
    from gi.repository import Gio, GLib

    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    params = GLib.Variant(sig, args) if sig else None
    res = bus.call_sync(BUS_NAME, OBJECT_PATH, INTERFACE, method, params, None,
                        Gio.DBusCallFlags.NONE, timeout, None)
    return res.unpack() if res else ()


def cmd_transcribe(ns) -> int:
    """Transcribe files locally (without going through the service)."""
    from dictado import config
    from dictado.engine import Engine
    from dictado.files import transcribe_file

    cfg = config.load()
    engine = Engine(cfg.languages, cfg.threads, cfg.detect_model)
    model = ns.model or cfg.dictation_model
    for name in ns.files:
        src = Path(name)
        t0 = time.monotonic()

        def progress(f):
            print(f"\r{src.name}: {f * 100:5.1f} %", end="", file=sys.stderr, flush=True)
        out = transcribe_file(engine, model, src, progress=progress)
        print(f"\r{src.name}: done in {time.monotonic() - t0:.1f} s → {out}", file=sys.stderr)
        print(out)
    return 0


def cmd_bench(ns) -> int:
    """Measure each model's speed on a file (real-time factor)."""
    from dictado import config
    from dictado.audio import decode_file
    from dictado.engine import Engine

    cfg = config.load()
    audio = decode_file(ns.file)
    seconds = audio.size / 16000
    print(f"Audio: {seconds:.1f} s · threads: {cfg.threads}")
    for name in ns.models:
        engine = Engine(cfg.languages, cfg.threads, cfg.detect_model)
        t0 = time.monotonic()
        engine.model(name)
        load = time.monotonic() - t0
        for beam in (1, 5):
            t0 = time.monotonic()
            result = engine.transcribe(audio, name, beam_size=beam)
            took = time.monotonic() - t0
            print(f"{name:>16} beam={beam}: {took:6.1f} s ({took / seconds:.2f}× real time, "
                  f"load {load:.1f} s) [{result.language}] {result.text[:70]}")
    return 0


def cmd_pick(_ns) -> int:
    """File chooser (portal); the service transcribes the chosen files."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gio, Gtk

    app = Gtk.Application(application_id="dev.dictado.Pick", flags=Gio.ApplicationFlags.NON_UNIQUE)

    def on_activate(application):
        application.hold()
        media = Gtk.FileFilter(name="Audio and video")
        media.add_mime_type("audio/*")
        media.add_mime_type("video/*")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(media)
        dialog = Gtk.FileDialog(title="Transcribe Files", filters=filters, default_filter=media)

        def done(dlg, res):
            try:
                files = dlg.open_multiple_finish(res)
            except Exception:  # cancelled
                files = []
            for i in range(files.get_n_items() if files else 0):
                path = files.get_item(i).get_path()
                if path:
                    print(_call("TranscribeFile", (path,), "(s)")[0])
            application.release()
        dialog.open_multiple(None, None, done)

    app.connect("activate", on_activate)
    return app.run([])


def cmd_download(_ns) -> int:
    """Download the configured models (only once)."""
    from dictado import config
    from dictado.engine import Engine

    cfg = config.load()
    engine = Engine(cfg.languages, cfg.threads, cfg.detect_model)
    names = dict.fromkeys(n for n in (cfg.dictation_model, cfg.transcription_model, cfg.detect_model) if n)
    for name in names:
        print(f"Model {name}…", flush=True)
        engine.model(name)
    print("Models ready.")
    return 0


def cmd_watch(_ns) -> int:
    """Print the service's signals (useful for debugging)."""
    from gi.repository import Gio, GLib

    bus = Gio.bus_get_sync(Gio.BusType.SESSION)

    def on_signal(_c, _s, _p, _i, name, params):
        print(name, params.unpack(), flush=True)
    bus.signal_subscribe(BUS_NAME, INTERFACE, None, OBJECT_PATH, None,
                         Gio.DBusSignalFlags.NONE, on_signal)
    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        pass
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="dictado", description="Local voice dictation and transcription.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="run the D-Bus service")
    sub.add_parser("toggle", help="start/stop a dictation")
    sub.add_parser("start", help="start a dictation")
    sub.add_parser("stop", help="stop the dictation and transcribe it")
    sub.add_parser("cancel", help="cancel the dictation")
    sub.add_parser("live", help="start/stop live transcription (Me + Others)")
    sub.add_parser("status", help="service status")
    sub.add_parser("watch", help="print D-Bus signals")
    sub.add_parser("download", help="download the configured models")
    sub.add_parser("pick", help="choose files and transcribe them in the background")
    sub.add_parser("quit", help="stop the service")
    t = sub.add_parser("transcribe", help="transcribe audio or video files to .txt")
    t.add_argument("files", nargs="+")
    t.add_argument("--model", help="Whisper model (default: dictation_model)")
    b = sub.add_parser("bench", help="measure model speed")
    b.add_argument("file")
    b.add_argument("models", nargs="*", default=["base", "small"])
    ns = p.parse_args(argv)

    if ns.cmd == "serve":
        from dictado.service import serve
        return serve()
    if ns.cmd == "transcribe":
        return cmd_transcribe(ns)
    if ns.cmd == "bench":
        return cmd_bench(ns)
    if ns.cmd == "watch":
        return cmd_watch(ns)
    if ns.cmd == "download":
        return cmd_download(ns)
    if ns.cmd == "pick":
        return cmd_pick(ns)
    simple = {"toggle": "Toggle", "start": "StartDictation", "stop": "StopDictation",
              "cancel": "CancelDictation", "quit": "Quit"}
    if ns.cmd in simple:
        _call(simple[ns.cmd])
        return 0
    if ns.cmd == "live":
        status = _call("GetStatus")[0]
        if status["Transcription"] == "recording":
            print(_call("StopTranscription")[0])
        else:
            print(_call("StartTranscription")[0])
        return 0
    if ns.cmd == "status":
        for k, v in _call("GetStatus")[0].items():
            print(f"{k}: {v}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
