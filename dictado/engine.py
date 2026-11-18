"""Speech recognition engine: faster-whisper (CTranslate2, int8 on the CPU)."""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

RATE = 16000

# Phrases Whisper invents on silence or music (they come from subtitles).
HALLUCINATIONS = [
    r"subt[ií]tulos (realizados|hechos|creados) por.*",
    r"subt[ií]tulado por.*",
    r".*amara\.org.*",
    r"gracias por ver( el v[ií]deo)?\.?",
    r"suscr[ií]bete.*",
    r"thanks? (you )?for watching.*",
    r"please subscribe.*",
    r"[.…\s]+",
    r"\[(m[uú]sica|music|silencio|silence|aplausos|applause|risas|laughter)\]",
    r"\((m[uú]sica|music|silencio|silence|aplausos|applause|risas|laughter)\)",
]
# Real phrases that are also typical hallucinations: dropped only when Whisper
# also doubts there was any speech.
SUSPICIOUS = [r"(muchas )?gracias\.?", r"thank you\.?", r"¡?m[uú]sica!?", r"adi[oó]s\.?", r"bye\.?"]
_HALLU = re.compile(r"^\s*(" + "|".join(HALLUCINATIONS) + r")\s*$", re.IGNORECASE)
_SUSP = re.compile(r"^\s*(" + "|".join(SUSPICIOUS) + r")\s*$", re.IGNORECASE)


@dataclass
class Segment:
    start: float  # seconds from the start of the audio
    end: float
    text: str
    language: str = ""


@dataclass
class Result:
    segments: list[Segment]
    language: str

    @property
    def text(self) -> str:
        return clean(" ".join(s.text for s in self.segments))


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def is_hallucination(text: str, no_speech_prob: float = 0.0, avg_logprob: float = 0.0) -> bool:
    if not text.strip():
        return True
    if _HALLU.match(text):
        return True
    if _SUSP.match(text) and no_speech_prob > 0.3:
        return True
    return no_speech_prob > 0.8 and avg_logprob < -1.0


def speech_pieces(audio: np.ndarray, min_gap: float = 0.35, min_piece: float = 1.2) -> list[tuple[int, int]]:
    """Split audio into phrases (sample ranges) at pauses, using Silero VAD."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    stamps = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=300, speech_pad_ms=200))
    pieces: list[list[int]] = []
    for s in stamps:
        if pieces and (s["start"] - pieces[-1][1]) < min_gap * RATE:
            pieces[-1][1] = s["end"]
        else:
            pieces.append([s["start"], s["end"]])
    # Very short pieces ("ok", "sí") can't be identified on their own:
    # merge them with the previous phrase.
    merged: list[list[int]] = []
    for p in pieces:
        if merged and (p[1] - p[0]) < min_piece * RATE:
            merged[-1][1] = p[1]
        else:
            merged.append(p)
    if len(merged) > 1 and (merged[0][1] - merged[0][0]) < min_piece * RATE:
        merged[1][0] = merged[0][0]
        merged.pop(0)
    return [(a, b) for a, b in merged]


class Engine:
    """Loads models on demand and keeps them in memory."""

    def __init__(self, languages: list[str] | None = None, threads: int = 4,
                 detect_model: str = "tiny"):
        self.languages = [l for l in (languages or []) if l]
        self.detect_model = detect_model
        self.threads = threads
        self._models: dict[str, object] = {}
        self._lock = threading.Lock()

    def model(self, name: str):
        with self._lock:
            if name not in self._models:
                from faster_whisper import WhisperModel
                log.info("Loading model %s…", name)
                self._models[name] = WhisperModel(name, device="cpu", compute_type="int8",
                                                  cpu_threads=self.threads, num_workers=2)
                log.info("Model %s ready", name)
            return self._models[name]

    def loaded(self, name: str) -> bool:
        return name in self._models

    def detect(self, audio: np.ndarray, fallback_model: str) -> str | None:
        """Language of a phrase, restricted to `languages` (so accented Spanish
        is not taken for Portuguese or Galician).

        Whisper always processes 30 s windows, so detecting with the big model
        costs almost a whole extra transcription; `tiny` costs a fraction and
        is accurate enough to choose between a few languages.
        """
        if len(self.languages) == 1:
            return self.languages[0]
        if not self.languages:
            return None
        model = self.model(self.detect_model or fallback_model)
        try:
            _, _, probs = model.detect_language(audio=audio[: RATE * 30])
        except Exception:  # older faster-whisper
            log.debug("detect_language unavailable", exc_info=True)
            return None
        allowed = [(lang, p) for lang, p in probs if lang in self.languages]
        return max(allowed, key=lambda x: x[1])[0] if allowed else None

    def transcribe(self, audio: np.ndarray, model_name: str, *, beam_size: int = 5,
                   prompt: str | None = None, progress=None) -> Result:
        """Transcribe, detecting the language phrase by phrase.

        A recording that switches between Spanish and English is split at the
        pauses; consecutive phrases in the same language are transcribed
        together, each run with its own language. Forcing a single language
        on mixed audio makes Whisper drop or translate the other one.
        """
        if audio.size < RATE * 0.3:
            return Result([], self.languages[0] if self.languages else "")
        runs: list[tuple[int, int, str | None]] = []
        if len(self.languages) > 1:
            pieces = speech_pieces(audio)
            for start, end in pieces:
                lang = self.detect(audio[start:end], model_name)
                if runs and runs[-1][2] == lang:
                    runs[-1] = (runs[-1][0], end, lang)
                else:
                    runs.append((start, end, lang))
        if len(runs) <= 1:
            lang = runs[0][2] if runs else self.detect(audio, model_name)
            runs = [(0, audio.size, lang)]
        else:
            log.info("Mixed languages: %s", " → ".join(r[2] or "?" for r in runs))
            # Give each run the audio up to the next one, so no word at a
            # boundary is cut off.
            runs = [(0 if i == 0 else s, runs[i + 1][0] if i + 1 < len(runs) else audio.size, l)
                    for i, (s, _e, l) in enumerate(runs)]

        total = audio.size / RATE
        segments: list[Segment] = []
        for start, end, lang in runs:
            offset = start / RATE
            part = self._run(audio[start:end], model_name, lang, beam_size, prompt,
                             (lambda f, o=offset, d=(end - start) / RATE:
                              progress(min(1.0, (o + f * d) / total))) if progress else None)
            segments += [Segment(s.start + offset, s.end + offset, s.text, s.language) for s in part]
        languages = [s.language for s in segments if s.language]
        main = max(set(languages), key=languages.count) if languages else (runs[0][2] or "")
        return Result(segments, main)

    def _run(self, audio, model_name, language, beam_size, prompt, progress) -> list[Segment]:
        model = self.model(model_name)
        segments, info = model.transcribe(
            audio,
            language=language,
            beam_size=beam_size,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,
            initial_prompt=prompt,
        )
        out = []
        for seg in segments:
            if progress and info.duration:
                progress(min(1.0, seg.end / info.duration))
            if is_hallucination(seg.text, seg.no_speech_prob, seg.avg_logprob):
                continue
            out.append(Segment(seg.start, seg.end, clean(seg.text), info.language))
        return out
