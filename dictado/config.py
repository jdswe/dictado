"""Configuración en ~/.config/dictado/config.toml (todas las claves son opcionales)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "dictado"
CONFIG_FILE = CONFIG_DIR / "config.toml"

DEFAULT_TOML = """\
# Configuración de Dictado. Borra una línea para volver al valor por defecto.

# Modelos Whisper: tiny, base, small, medium, large-v3-turbo...
# Se descargan una sola vez a ~/.cache/huggingface.
dictation_model = "small"
transcription_model = "base"

# Modelo pequeño que solo detecta el idioma (vacío = el mismo modelo).
detect_model = "tiny"

# Idiomas permitidos para la detección automática ("es", "en"...).
# Con un solo idioma no se detecta nada y es algo más rápido.
languages = ["es", "en"]

# Hilos de CPU para Whisper (0 = automático).
cpu_threads = 0

# Guardar cada dictado con hora en <dictation_dir>/AAAA-MM-DD.txt
save_dictations = true
dictation_dir = "~/Documents/Dictados"

# Carpeta de las transcripciones en vivo.
transcripts_dir = "~/Documents/Transcripciones"

# Micrófono (nombre de nodo de PipeWire; vacío = el predeterminado).
# Con altavoces puedes usar "echo-cancel-source" (ver README).
mic_source = ""

# Etiquetas de cada fuente.
mic_label = "Yo"
system_label = "Otros"

# Descartar frases del micrófono que repiten lo que suena por los altavoces.
echo_filter = true
"""


@dataclass
class Config:
    dictation_model: str = "small"
    transcription_model: str = "base"
    detect_model: str = "tiny"
    languages: list[str] = field(default_factory=lambda: ["es", "en"])
    cpu_threads: int = 0
    save_dictations: bool = True
    dictation_dir: str = "~/Documents/Dictados"
    transcripts_dir: str = "~/Documents/Transcripciones"
    mic_source: str = ""
    mic_label: str = "Yo"
    system_label: str = "Otros"
    echo_filter: bool = True

    @property
    def dictation_path(self) -> Path:
        return Path(self.dictation_dir).expanduser()

    @property
    def transcripts_path(self) -> Path:
        return Path(self.transcripts_dir).expanduser()

    @property
    def threads(self) -> int:
        if self.cpu_threads > 0:
            return self.cpu_threads
        return max(1, min(8, (os.cpu_count() or 4) // 2))


def load(path: Path = CONFIG_FILE) -> Config:
    cfg = Config()
    if not path.exists():
        return cfg
    with open(path, "rb") as f:
        data = tomllib.load(f)
    known = {f.name for f in fields(Config)}
    for key, value in data.items():
        if key in known:
            setattr(cfg, key, value)
    return cfg


def write_default(path: Path = CONFIG_FILE) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_TOML, encoding="utf-8")
    return True
