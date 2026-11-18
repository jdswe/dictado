"""Settings in ~/.config/dictado/config.toml (every key is optional)."""

from __future__ import annotations

import hashlib
import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "dictado"
CONFIG_FILE = CONFIG_DIR / "config.toml"

DEFAULT_TOML = """\
# Dictado settings. Delete a line to go back to its default.
# After changing this file: systemctl --user restart dictado

# Whisper models: tiny, base, small, medium, large-v3-turbo...
# They are downloaded once to ~/.cache/huggingface.
# dictation_model is used for dictation, files and your voice in live mode;
# transcription_model for the system audio in live mode.
dictation_model = "small"
transcription_model = "base"

# Small model used only to detect the language (empty = the same model).
detect_model = "tiny"

# Languages to recognize. The language is detected phrase by phrase, so you
# can switch between them in the same recording. With a single language
# nothing is detected and it is a little faster.
languages = ["es", "en"]

# CPU threads for Whisper (0 = automatic).
cpu_threads = 0

# Save every dictation with its time to <dictation_dir>/YYYY-MM-DD.txt
save_dictations = true
dictation_dir = "~/Documents/Dictations"

# Folder for live transcripts.
transcripts_dir = "~/Documents/Transcripts"

# Microphone (PipeWire node name; empty = the default one).
# With speakers you can use "echo-cancel-source" (see the README).
mic_source = ""

# Labels for each source in live transcripts.
mic_label = "Me"
system_label = "Others"

# Drop microphone phrases that repeat what the speakers are playing.
echo_filter = true
"""

# SHA-256 of the config file written by version 0.1.0 (Spanish defaults).
# If it was never edited, it is replaced by the current defaults.
_OLD_DEFAULTS = {"13f326e7dd5de5a20b4016334f9a25e4f27f4e04fcf39accee04c827143208d7"}


@dataclass
class Config:
    dictation_model: str = "small"
    transcription_model: str = "base"
    detect_model: str = "tiny"
    languages: list[str] = field(default_factory=lambda: ["es", "en"])
    cpu_threads: int = 0
    save_dictations: bool = True
    dictation_dir: str = "~/Documents/Dictations"
    transcripts_dir: str = "~/Documents/Transcripts"
    mic_source: str = ""
    mic_label: str = "Me"
    system_label: str = "Others"
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


def is_old_default(text: str) -> bool:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() in _OLD_DEFAULTS


def write_default(path: Path = CONFIG_FILE) -> bool:
    """Write the default settings, or upgrade an untouched 0.1.0 file."""
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if not is_old_default(text):
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_TOML, encoding="utf-8")
    return True
