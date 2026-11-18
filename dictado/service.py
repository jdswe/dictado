"""D-Bus service (session bus) that runs dictation, live transcription and files."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from gi.repository import Gio, GLib

from dictado import BUS_NAME, INTERFACE, OBJECT_PATH
from dictado import config as config_mod
from dictado.dictation import Recorder, save_dictation
from dictado.engine import Engine
from dictado.files import output_path, transcribe_file
from dictado.transcription import LiveTranscription, transcript_path

log = logging.getLogger(__name__)

XML = (Path(__file__).parent / "dev.dictado.Dictado1.xml").read_text(encoding="utf-8")


def notify(summary: str, body: str = "", icon: str = "audio-input-microphone-symbolic",
           urgent: bool = False) -> None:
    """Desktop notification (org.freedesktop.Notifications)."""
    try:
        hints = {"urgency": GLib.Variant("y", 2 if urgent else 1)}
        Gio.bus_get_sync(Gio.BusType.SESSION).call(
            "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications", "Notify",
            GLib.Variant("(susssasa{sv}i)", ("Dictado", 0, icon, summary, body, [], hints, -1)),
            None, Gio.DBusCallFlags.NONE, -1, None, None, None)
    except Exception:  # noqa: BLE001
        log.debug("Could not notify", exc_info=True)


class Service:
    def __init__(self, loop: GLib.MainLoop, cfg: config_mod.Config | None = None):
        self.loop = loop
        self.cfg = cfg or config_mod.load()
        self.engine = Engine(self.cfg.languages, self.cfg.threads, self.cfg.detect_model)
        self.conn: Gio.DBusConnection | None = None
        self.dictation = "idle"
        self.transcription = "idle"
        self.recorder: Recorder | None = None
        self.live: LiveTranscription | None = None
        self.model_ready = False
        self._last_level = 0.0
        self._file_lock = threading.Lock()

    # -- D-Bus plumbing ---------------------------------------------------
    def register(self, conn: Gio.DBusConnection) -> None:
        self.conn = conn
        node = Gio.DBusNodeInfo.new_for_xml(XML)
        conn.register_object(OBJECT_PATH, node.interfaces[0], self._on_call, self._on_get, None)

    def _emit(self, name: str, sig: str, *args) -> None:
        if self.conn:
            self.conn.emit_signal(None, OBJECT_PATH, INTERFACE, name, GLib.Variant(f"({sig})", args))

    def emit(self, name: str, sig: str, *args) -> None:
        """Safe from any thread."""
        GLib.idle_add(lambda: (self._emit(name, sig, *args), False)[1])

    def _props(self) -> dict:
        return {
            "Dictation": GLib.Variant("s", self.dictation),
            "Transcription": GLib.Variant("s", self.transcription),
            "TranscriptPath": GLib.Variant("s", str(self.live.path) if self.live else ""),
            "TranscriptionStarted": GLib.Variant("x", int(self.live.started * 1000) if self.live else 0),
            "ModelReady": GLib.Variant("b", self.model_ready),
        }

    def _on_get(self, _conn, _sender, _path, _iface, prop):
        return self._props().get(prop)

    def _state_changed(self) -> None:
        if not self.conn:
            return
        self._emit("StateChanged", "ss", self.dictation, self.transcription)
        self.conn.emit_signal(None, OBJECT_PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                              GLib.Variant("(sa{sv}as)", (INTERFACE, self._props(), [])))

    def _on_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        try:
            handler = getattr(self, f"dbus_{method}")
            result = handler(*params.unpack())
            invocation.return_value(result)
        except Exception as e:  # noqa: BLE001
            log.exception("Error in %s", method)
            invocation.return_dbus_error(f"{BUS_NAME}.Error", str(e))

    # -- models ---------------------------------------------------------
    def preload(self) -> None:
        def run():
            try:
                self.engine.model(self.cfg.dictation_model)
                if self.cfg.detect_model and len(self.cfg.languages) > 1:
                    self.engine.model(self.cfg.detect_model)
                self.model_ready = True
                GLib.idle_add(lambda: (self._state_changed(), False)[1])
            except Exception as e:  # noqa: BLE001
                log.exception("Could not load the model")
                self.emit("Error", "s", f"Could not load the speech model: {e}")
        threading.Thread(target=run, name="preload", daemon=True).start()

    # -- dictation -------------------------------------------------------
    def dbus_StartDictation(self):
        if self.dictation != "idle":
            return None
        self.recorder = Recorder(self.cfg.mic_source, on_level=self._on_level)
        self.recorder.start()
        self.dictation = "recording"
        self._state_changed()
        return None

    def _on_level(self, level: float) -> None:
        self.emit("Level", "d", level)

    def dbus_StopDictation(self):
        if self.dictation != "recording" or not self.recorder:
            return None
        audio = self.recorder.stop()
        self.recorder = None
        self.dictation = "processing"
        self._state_changed()
        threading.Thread(target=self._finish_dictation, args=(audio,), name="dictation",
                         daemon=True).start()
        return None

    def _finish_dictation(self, audio) -> None:
        text, language = "", ""
        t0 = time.monotonic()
        try:
            result = self.engine.transcribe(audio, self.cfg.dictation_model, beam_size=5)
            text, language = result.text, result.language
            log.info("Dictation (%.1fs of audio in %.1fs, %s): %s", audio.size / 16000,
                     time.monotonic() - t0, language, text)
            if text and self.cfg.save_dictations:
                save_dictation(self.cfg.dictation_path, text)
        except Exception as e:  # noqa: BLE001
            log.exception("Dictation error")
            self.emit("Error", "s", str(e))

        def done():
            if text:
                self._emit("DictationText", "ss", text, language)
            self.dictation = "idle"
            self._state_changed()
            return False
        GLib.idle_add(done)

    def dbus_CancelDictation(self):
        if self.recorder:
            self.recorder.stop()
            self.recorder = None
        if self.dictation == "recording":
            self.dictation = "idle"
            self._state_changed()
        return None

    def dbus_Toggle(self):
        if self.dictation == "recording":
            return self.dbus_StopDictation()
        if self.dictation == "idle":
            return self.dbus_StartDictation()
        return None

    # -- live transcription ----------------------------------------------
    def dbus_StartTranscription(self):
        if self.live:
            return GLib.Variant("(s)", (str(self.live.path),))
        path = transcript_path(self.cfg.transcripts_path)
        self.live = LiveTranscription(
            self.engine, {"mic": self.cfg.dictation_model, "system": self.cfg.transcription_model}, path,
            mic_target=self.cfg.mic_source,
            labels={"mic": self.cfg.mic_label, "system": self.cfg.system_label},
            echo_filter=self.cfg.echo_filter,
            on_line=lambda who, text, t: self.emit("TranscriptLine", "ssx", who, text, int(t * 1000)),
            on_error=lambda msg: self.emit("Error", "s", msg))
        self.live.start()
        self.transcription = "recording"
        self._state_changed()
        notify("Recording and transcribing",
               "Your microphone and the system audio are being recorded. Let everyone know.",
               icon="media-record-symbolic", urgent=True)
        return GLib.Variant("(s)", (str(path),))

    def dbus_StopTranscription(self):
        if not self.live:
            return GLib.Variant("(s)", ("",))
        live, self.live = self.live, None
        path = str(live.path)
        self.transcription = "idle"
        self._state_changed()

        def finish():
            live.stop()
            notify("Transcript saved", path, icon="document-save-symbolic")
        threading.Thread(target=finish, name="stop-live", daemon=True).start()
        return GLib.Variant("(s)", (path,))

    def dbus_ToggleTranscription(self):
        if self.live:
            self.dbus_StopTranscription()
        else:
            self.dbus_StartTranscription()
        return None

    # -- files ------------------------------------------------------------
    def dbus_TranscribeFile(self, path: str):
        src = Path(path).expanduser()
        if not src.is_file():
            raise FileNotFoundError(f"No such file: {src}")
        out = output_path(src)
        # Reserve the name so two requests never write the same .txt
        out.touch()

        def run():
            with self._file_lock:
                last = [0.0]

                def progress(f):
                    if f - last[0] >= 0.02 or f >= 1.0:
                        last[0] = f
                        self.emit("FileProgress", "sd", str(src), f)
                try:
                    transcribe_file(self.engine, self.cfg.dictation_model, src, out, progress)
                    self.emit("FileDone", "ss", str(src), str(out))
                    notify("File transcribed", str(out), icon="document-save-symbolic")
                except Exception as e:  # noqa: BLE001
                    log.exception("Error transcribing %s", src)
                    self.emit("Error", "s", f"{src.name}: {e}")
        threading.Thread(target=run, name="file", daemon=True).start()
        return GLib.Variant("(s)", (str(out),))

    def dbus_GetStatus(self):
        return GLib.Variant("(a{sv})", (self._props(),))

    def dbus_Quit(self):
        GLib.idle_add(self.shutdown)
        return None

    def shutdown(self):
        if self.recorder:
            self.recorder.stop()
        if self.live:
            self.live.stop()
            self.live = None
        self.loop.quit()
        return False


def serve() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config_mod.write_default()
    loop = GLib.MainLoop()
    service = Service(loop)

    def on_bus(conn, _name):
        service.register(conn)

    def on_name(_conn, name):
        log.info("Service %s ready", name)
        service.preload()

    def on_lost(_conn, name):
        log.error("Could not own %s (is another instance running?)", name)
        loop.quit()

    Gio.bus_own_name(Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.NONE,
                     on_bus, on_name, on_lost)
    for sig in (2, 15):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, service.shutdown)
    loop.run()
    return 0
