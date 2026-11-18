"""Audio capture from PipeWire with pw-record (no extra dependencies).

- Microphone: the default source (or the given node).
- System: the monitor of the default sink (stream.capture.sink=true), that is,
  whatever plays through the speakers or headphones.
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Callable

import numpy as np

RATE = 16000
BLOCK_SECONDS = 0.1
BLOCK_BYTES = int(RATE * BLOCK_SECONDS) * 2  # s16 mono

# callback(float32_block, unix_time_of_block_start)
BlockCallback = Callable[[np.ndarray, float], None]


def pcm16_to_float(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


def decode_file(path: str) -> np.ndarray:
    """Decode any audio or video file to 16 kHz mono with ffmpeg."""
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1",
         "-ar", str(RATE), "-f", "s16le", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="replace").strip() or "ffmpeg failed")
    return pcm16_to_float(proc.stdout)


def rms(block: np.ndarray) -> float:
    if block.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(block * block)))


class Capture:
    """A pw-record process that delivers 100 ms blocks to a callback."""

    def __init__(self, kind: str, callback: BlockCallback, target: str = "", name: str = "Dictado"):
        if kind not in ("mic", "system"):
            raise ValueError(kind)
        self.kind = kind
        self.callback = callback
        self.target = target
        self.name = name
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def command(self) -> list[str]:
        cmd = ["pw-record", "--raw", "--rate", str(RATE), "--channels", "1",
               "--format", "s16", "--latency", "100ms"]
        props = [f'media.name="{self.name} ({"microphone" if self.kind == "mic" else "system audio"})"',
                 'application.name="Dictado"', 'application.icon-name="audio-input-microphone"']
        if self.kind == "system":
            props.append("stream.capture.sink=true")
        cmd += ["-P", "{ " + " ".join(props) + " }"]
        if self.target:
            cmd += ["--target", self.target]
        cmd.append("-")
        return cmd

    def start(self) -> None:
        self._stop.clear()
        self._proc = subprocess.Popen(self.command(), stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, bufsize=0)
        self._thread = threading.Thread(target=self._run, name=f"capture-{self.kind}", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        assert self._proc and self._proc.stdout
        stream = self._proc.stdout
        t0 = None
        samples = 0
        pending = b""
        while not self._stop.is_set():
            chunk = stream.read(BLOCK_BYTES - len(pending))
            if not chunk:
                break
            pending += chunk
            if len(pending) < BLOCK_BYTES:
                continue
            block = pcm16_to_float(pending)
            pending = b""
            if t0 is None:
                # The first block just ended: it started 100 ms ago.
                t0 = time.time() - BLOCK_SECONDS
            self.callback(block, t0 + samples / RATE)
            samples += block.size

    def stop(self) -> None:
        self._stop.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._proc = None
        self._thread = None

    @property
    def alive(self) -> bool:
        return bool(self._proc and self._proc.poll() is None)


class Segmenter:
    """Cut a continuous stream into phrases by energy (a simple VAD).

    Emits (audio, unix_start) after `min_silence` of silence following speech,
    or when a phrase reaches `max_seconds`. The threshold adapts to the
    background noise. Whisper filters again with its own VAD (Silero).
    """

    def __init__(self, emit: Callable[[np.ndarray, float], None], *,
                 min_silence: float = 0.7, max_seconds: float = 20.0,
                 preroll: float = 0.3, min_speech: float = 0.4, abs_threshold: float = 0.004):
        self.emit = emit
        self.min_silence = min_silence
        self.max_seconds = max_seconds
        self.preroll_blocks = max(1, round(preroll / BLOCK_SECONDS))
        self.min_speech = min_speech
        self.abs_threshold = abs_threshold
        self.noise = 0.002
        self._levels: list[float] = []
        self._blocks: list[np.ndarray] = []
        self._start = 0.0
        self._speech = 0.0
        self._silence = 0.0
        self._recent: list[tuple[np.ndarray, float]] = []
        self.position = 0.0  # unix time up to which audio has been processed

    @property
    def open_since(self) -> float | None:
        """Start of the phrase in progress (not emitted yet), if any."""
        return self._start if self._blocks else None

    def threshold(self) -> float:
        return max(self.abs_threshold, self.noise * 2.5)

    def feed(self, block: np.ndarray, t: float) -> None:
        level = rms(block)
        # Background noise = 20th percentile of the last ~10 s: it rises with a
        # fan or a noisy mic and drops when the room goes quiet.
        self._levels.append(level)
        if len(self._levels) > 100:
            self._levels.pop(0)
        if len(self._levels) >= 10:
            self.noise = float(np.percentile(self._levels, 20))
        voiced = level > self.threshold()
        self.position = t + BLOCK_SECONDS

        if not self._blocks:
            self._recent.append((block, t))
            self._recent = self._recent[-(self.preroll_blocks + 1):]
            if voiced:
                self._blocks = [b for b, _ in self._recent]
                self._start = self._recent[0][1]
                self._recent = []
                self._speech = BLOCK_SECONDS
                self._silence = 0.0
            return

        self._blocks.append(block)
        if voiced:
            self._speech += BLOCK_SECONDS
            self._silence = 0.0
        else:
            self._silence += BLOCK_SECONDS
        length = len(self._blocks) * BLOCK_SECONDS
        if self._silence >= self.min_silence or length >= self.max_seconds:
            self.flush()

    def flush(self) -> None:
        if self._blocks and self._speech >= self.min_speech:
            self.emit(np.concatenate(self._blocks), self._start)
        self._blocks = []
        self._speech = 0.0
        self._silence = 0.0
