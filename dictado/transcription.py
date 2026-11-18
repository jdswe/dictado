"""Live transcription: microphone ("Me") + system audio ("Others").

Each source is captured and cut into phrases separately. Phrases are
transcribed on a worker thread and written to the file in time order as soon
as neither source can still produce anything earlier (a watermark). Every
line is written and flushed to disk immediately, so nothing already written
is lost if the process stops.
"""

from __future__ import annotations

import datetime as dt
import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from dictado.audio import Capture, Segmenter
from dictado.echo import is_echo
from dictado.engine import Engine

log = logging.getLogger(__name__)

ECHO_WINDOW = 2.5  # seconds of slack when looking for echo in the other channel


@dataclass
class Line:
    source: str  # "mic" | "system"
    start: float  # unix time
    end: float
    text: str


def transcript_path(folder: Path, when: dt.datetime | None = None) -> Path:
    when = when or dt.datetime.now()
    base = folder / when.strftime("%Y-%m-%d %H-%M")
    path = base.with_suffix(".txt")
    n = 2
    while path.exists():
        path = Path(f"{base} ({n}).txt")
        n += 1
    return path


class Merger:
    """Orders both sources' lines by time and drops the echo."""

    def __init__(self, write: Callable[[Line], None], echo_filter: bool = True):
        self.write = write
        self.echo_filter = echo_filter
        self.pending: list[Line] = []
        self.recent_system: list[Line] = []

    def add(self, line: Line) -> None:
        self.pending.append(line)

    def flush(self, watermark: float) -> None:
        """Write the lines that can no longer end up out of order."""
        margin = ECHO_WINDOW if self.echo_filter else 0.0
        self.pending.sort(key=lambda l: l.start)
        ready = [l for l in self.pending if l.end + margin <= watermark]
        # Only a contiguous prefix is written, to keep the order.
        count = 0
        for line in self.pending:
            if line in ready:
                count += 1
            else:
                break
        out, self.pending = self.pending[:count], self.pending[count:]
        for line in out:
            if line.source == "system":
                self.recent_system.append(line)
        for line in out:
            if line.source == "mic" and self.echo_filter and self._is_echo(line):
                log.info("Eco descartado: %s", line.text)
                continue
            self.write(line)
        if out:
            # What is still pending starts after what was written: remembering
            # the system lines of the last echo window is enough.
            cutoff = out[-1].start - 4 * ECHO_WINDOW
            self.recent_system = [l for l in self.recent_system if l.end >= cutoff]

    def _is_echo(self, line: Line) -> bool:
        around = [l.text for l in self.recent_system + self.pending
                  if l.source == "system" and l.start <= line.end + ECHO_WINDOW
                  and l.end >= line.start - ECHO_WINDOW]
        return is_echo(line.text, around)

    def flush_all(self) -> None:
        self.flush(float("inf"))


class LiveTranscription:
    def __init__(self, engine: Engine, models: dict[str, str], path: Path, *, mic_target: str = "",
                 labels: dict[str, str] | None = None, echo_filter: bool = True,
                 on_line: Callable[[str, str, float], None] | None = None,
                 on_error: Callable[[str], None] | None = None):
        self.engine = engine
        # Your own voice ("mic") can use a more accurate model than the
        # system audio, which runs continuously.
        self.models = models
        self.path = path
        self.labels = labels or {"mic": "Me", "system": "Others"}
        self.on_line = on_line
        self.on_error = on_error
        self.started = time.time()
        self._jobs: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._inflight: dict[str, list[float]] = {"mic": [], "system": []}
        self._merger = Merger(self._write, echo_filter)
        self._file = None
        self._segmenters = {
            src: Segmenter(lambda audio, t, s=src: self._enqueue(s, audio, t))
            for src in ("mic", "system")
        }
        self._captures = [
            Capture("mic", lambda b, t: self._feed("mic", b, t), target=mic_target),
            Capture("system", lambda b, t: self._feed("system", b, t)),
        ]
        self._worker = threading.Thread(target=self._work, name="live-transcription", daemon=True)
        self._ticker: threading.Thread | None = None
        self._running = False

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path, "a", encoding="utf-8", buffering=1)
        now = dt.datetime.now()
        self._file.write(
            f"# Transcript {now:%Y-%m-%d %H:%M}\n"
            f"# {self.labels['mic']} = microphone · {self.labels['system']} = system audio\n\n")
        self._sync()
        self._running = True
        self._worker.start()
        for cap in self._captures:
            cap.start()
        self._ticker = threading.Thread(target=self._tick, name="live-flush", daemon=True)
        self._ticker.start()

    def stop(self) -> Path:
        self._running = False
        for cap in self._captures:
            cap.stop()
        with self._lock:
            for seg in self._segmenters.values():
                seg.flush()
        self._jobs.put(None)
        self._worker.join()
        with self._lock:
            self._merger.flush_all()
        if self._file:
            self._file.write(f"\n# End {dt.datetime.now():%H:%M:%S}\n")
            self._sync()
            self._file.close()
            self._file = None
        return self.path

    @property
    def elapsed(self) -> float:
        return time.time() - self.started

    # -- capture -> phrases -> jobs ----------------------------------------
    def _feed(self, source: str, block: np.ndarray, t: float) -> None:
        with self._lock:
            self._segmenters[source].feed(block, t)

    def _enqueue(self, source: str, audio: np.ndarray, start: float) -> None:
        # Called with self._lock held.
        self._inflight[source].append(start)
        self._jobs.put((start, source, audio))

    def _work(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            start, source, audio = job
            try:
                result = self.engine.transcribe(audio, self.models[source], beam_size=1)
            except Exception as e:  # noqa: BLE001
                log.exception("Transcription error")
                if self.on_error:
                    self.on_error(str(e))
                result = None
            with self._lock:
                self._inflight[source].remove(start)
                if result:
                    for seg in result.segments:
                        self._merger.add(Line(source, start + seg.start, start + seg.end, seg.text))
                self._merger.flush(self._watermark())

    def _tick(self) -> None:
        while self._running:
            time.sleep(1.0)
            with self._lock:
                self._merger.flush(self._watermark())

    def _watermark(self) -> float:
        """Time before which no new phrase can arrive any more."""
        marks = []
        for src, seg in self._segmenters.items():
            candidates = [seg.position]
            if seg.open_since is not None:
                candidates.append(seg.open_since)
            candidates += self._inflight[src]
            marks.append(min(candidates))
        return min(marks)

    # -- output -----------------------------------------------------------
    def _write(self, line: Line) -> None:
        stamp = dt.datetime.fromtimestamp(line.start).strftime("%H:%M:%S")
        label = self.labels[line.source]
        if self._file:
            self._file.write(f"[{stamp}] {label}: {line.text}\n")
            self._sync()
        if self.on_line:
            self.on_line(label, line.text, line.start)

    def _sync(self) -> None:
        self._file.flush()
        try:
            import os
            os.fsync(self._file.fileno())
        except OSError:
            pass
