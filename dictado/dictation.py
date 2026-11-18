"""Dictado: graba solo el micrófono y lo transcribe al soltar/parar."""

from __future__ import annotations

import datetime as dt
import threading
from pathlib import Path
from typing import Callable

import numpy as np

from dictado.audio import Capture, rms


class Recorder:
    def __init__(self, target: str = "", on_level: Callable[[float], None] | None = None):
        self.on_level = on_level
        self._blocks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._capture = Capture("mic", self._feed, target=target, name="Dictado")

    def _feed(self, block: np.ndarray, _t: float) -> None:
        with self._lock:
            self._blocks.append(block)
        if self.on_level:
            # Nivel 0..1 aproximado (escala logarítmica, -60 dB .. 0 dB).
            level = rms(block)
            db = 20 * np.log10(max(level, 1e-6))
            self.on_level(float(np.clip((db + 60) / 60, 0, 1)))

    def start(self) -> None:
        self._capture.start()

    def stop(self) -> np.ndarray:
        self._capture.stop()
        with self._lock:
            audio = np.concatenate(self._blocks) if self._blocks else np.zeros(0, np.float32)
            self._blocks = []
        return audio

    @property
    def alive(self) -> bool:
        return self._capture.alive


def save_dictation(folder: Path, text: str, when: dt.datetime | None = None) -> Path:
    when = when or dt.datetime.now()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{when:%Y-%m-%d}.txt"
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"[{when:%H:%M:%S}] {text}\n")
    return path
