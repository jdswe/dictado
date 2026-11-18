"""Línea de órdenes: `dictado serve | toggle | transcribe ARCHIVO | ...`."""

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
    """Transcribe archivos localmente (sin pasar por el servicio)."""
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
        print(f"\r{src.name}: listo en {time.monotonic() - t0:.1f} s → {out}", file=sys.stderr)
        print(out)
    return 0


def cmd_bench(ns) -> int:
    """Mide la velocidad de cada modelo con un archivo (factor de tiempo real)."""
    from dictado import config
    from dictado.audio import decode_file
    from dictado.engine import Engine

    cfg = config.load()
    audio = decode_file(ns.file)
    seconds = audio.size / 16000
    print(f"Audio: {seconds:.1f} s · hilos: {cfg.threads}")
    for name in ns.models:
        engine = Engine(cfg.languages, cfg.threads, cfg.detect_model)
        t0 = time.monotonic()
        engine.model(name)
        load = time.monotonic() - t0
        for beam in (1, 5):
            t0 = time.monotonic()
            result = engine.transcribe(audio, name, beam_size=beam)
            took = time.monotonic() - t0
            print(f"{name:>16} beam={beam}: {took:6.1f} s ({took / seconds:.2f}× tiempo real, "
                  f"carga {load:.1f} s) [{result.language}] {result.text[:70]}")
    return 0


def cmd_pick(_ns) -> int:
    """Selector de archivos (portal) y transcripción en el servicio."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gio, Gtk

    app = Gtk.Application(application_id="dev.dictado.Pick", flags=Gio.ApplicationFlags.NON_UNIQUE)

    def on_activate(application):
        application.hold()
        media = Gtk.FileFilter(name="Audio y vídeo")
        media.add_mime_type("audio/*")
        media.add_mime_type("video/*")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(media)
        dialog = Gtk.FileDialog(title="Transcribir archivos", filters=filters, default_filter=media)

        def done(dlg, res):
            try:
                files = dlg.open_multiple_finish(res)
            except Exception:  # cancelado
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
    """Descarga (una sola vez) los modelos configurados."""
    from dictado import config
    from dictado.engine import Engine

    cfg = config.load()
    engine = Engine(cfg.languages, cfg.threads, cfg.detect_model)
    names = dict.fromkeys(n for n in (cfg.dictation_model, cfg.transcription_model, cfg.detect_model) if n)
    for name in names:
        print(f"Modelo {name}…", flush=True)
        engine.model(name)
    print("Modelos listos.")
    return 0


def cmd_watch(_ns) -> int:
    """Muestra las señales del servicio (útil para depurar)."""
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
    p = argparse.ArgumentParser(prog="dictado", description="Dictado por voz y transcripción local.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="arranca el servicio D-Bus")
    sub.add_parser("toggle", help="empieza/termina un dictado")
    sub.add_parser("start", help="empieza un dictado")
    sub.add_parser("stop", help="termina el dictado y lo transcribe")
    sub.add_parser("cancel", help="cancela el dictado")
    sub.add_parser("live", help="empieza/termina la transcripción en vivo (Yo + Otros)")
    sub.add_parser("status", help="estado del servicio")
    sub.add_parser("watch", help="muestra las señales D-Bus")
    sub.add_parser("download", help="descarga los modelos configurados")
    sub.add_parser("pick", help="elige archivos y los transcribe en segundo plano")
    sub.add_parser("quit", help="detiene el servicio")
    t = sub.add_parser("transcribe", help="transcribe archivos de audio o vídeo a .txt")
    t.add_argument("files", nargs="+")
    t.add_argument("--model", help="modelo Whisper (por defecto dictation_model)")
    b = sub.add_parser("bench", help="mide la velocidad de los modelos")
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
