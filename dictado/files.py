"""Transcribe an audio or video file to a .txt next to it."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from dictado.audio import decode_file
from dictado.engine import Engine


def output_path(source: Path) -> Path:
    out = source.with_suffix(".txt")
    n = 2
    while out.exists():
        out = source.with_name(f"{source.stem} ({n}).txt")
        n += 1
    return out


def stamp(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def transcribe_file(engine: Engine, model: str, source: Path, out: Path | None = None,
                    progress: Callable[[float], None] | None = None) -> Path:
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    out = out or output_path(source)
    audio = decode_file(str(source))
    result = engine.transcribe(audio, model, beam_size=5, progress=progress)
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# {source.name} — language: {result.language}\n\n")
        for seg in result.segments:
            f.write(f"[{stamp(seg.start)}] {seg.text}\n")
    if progress:
        progress(1.0)
    return out
