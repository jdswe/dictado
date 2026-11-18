"""Motor de reconocimiento: faster-whisper (CTranslate2, int8 en CPU)."""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

# Frases que Whisper "inventa" con silencio o música (vienen de subtítulos).
HALLUCINATIONS = [
    r"subt[ií]tulos (realizados|hechos|creados) por.*",
    r"subt[ií]tulado por.*",
    r".*amara\.org.*",
    r"gracias por ver( el v[ií]deo)?\.?",
    r"suscr[ií]bete.*",
    r"thanks? (you )?for watching.*",
    r"please subscribe.*",
    r"[.…\s]+",
    r"\[(m[uú]sica|music|silencio|aplausos|applause|risas|laughter)\]",
    r"\((m[uú]sica|music|silencio|aplausos|applause|risas|laughter)\)",
]
# Frases reales pero típicas de alucinación: solo se descartan si Whisper
# además duda de que haya voz.
SUSPICIOUS = [r"(muchas )?gracias\.?", r"thank you\.?", r"¡?m[uú]sica!?", r"adi[oó]s\.?", r"bye\.?"]
_HALLU = re.compile(r"^\s*(" + "|".join(HALLUCINATIONS) + r")\s*$", re.IGNORECASE)
_SUSP = re.compile(r"^\s*(" + "|".join(SUSPICIOUS) + r")\s*$", re.IGNORECASE)


@dataclass
class Segment:
    start: float  # segundos desde el inicio del audio
    end: float
    text: str


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


class Engine:
    """Carga modelos bajo demanda y los mantiene en memoria."""

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
                log.info("Cargando modelo %s…", name)
                self._models[name] = WhisperModel(name, device="cpu", compute_type="int8",
                                                  cpu_threads=self.threads, num_workers=2)
                log.info("Modelo %s listo", name)
            return self._models[name]

    def loaded(self, name: str) -> bool:
        return name in self._models

    def pick_language(self, model, audio: np.ndarray) -> str | None:
        """Detecta el idioma restringido a `languages` (evita que el español
        con acento se detecte como portugués o gallego).

        Whisper siempre procesa ventanas de 30 s, así que detectar con el
        mismo modelo cuesta casi otra transcripción entera; con `tiny` la
        detección cuesta una fracción y para elegir entre pocos idiomas basta.
        """
        if len(self.languages) == 1:
            return self.languages[0]
        if not self.languages:
            return None
        if self.detect_model:
            model = self.model(self.detect_model)
        try:
            _, _, probs = model.detect_language(audio=audio[: 16000 * 30])
        except Exception:  # versiones antiguas de faster-whisper
            log.debug("detect_language no disponible", exc_info=True)
            return None
        allowed = [(lang, p) for lang, p in probs if lang in self.languages]
        return max(allowed, key=lambda x: x[1])[0] if allowed else None

    def transcribe(self, audio: np.ndarray, model_name: str, *, beam_size: int = 5,
                   prompt: str | None = None, progress=None) -> Result:
        model = self.model(model_name)
        if audio.size < 16000 * 0.3:
            return Result([], self.languages[0] if self.languages else "")
        language = self.pick_language(model, audio)
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
            out.append(Segment(seg.start, seg.end, clean(seg.text)))
        return Result(out, info.language)
