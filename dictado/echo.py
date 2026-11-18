"""Filtro de eco por texto.

Con altavoces, el micrófono también capta lo que dicen los demás. Como el
audio del sistema se transcribe por separado, una frase del micrófono cuyas
palabras ya aparecen en lo que sonó por los altavoces en ese mismo momento
es eco: se descarta. Con auriculares nunca se activa.
"""

from __future__ import annotations

import re
import unicodedata

WORD = re.compile(r"\w+", re.UNICODE)


def words(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return WORD.findall(text)


def echo_ratio(mic_text: str, system_text: str) -> float:
    """Fracción de palabras del micrófono que también están en el sistema."""
    mic = words(mic_text)
    if not mic:
        return 0.0
    pool: dict[str, int] = {}
    for w in words(system_text):
        pool[w] = pool.get(w, 0) + 1
    hits = 0
    for w in mic:
        if pool.get(w, 0) > 0:
            pool[w] -= 1
            hits += 1
    return hits / len(mic)


def is_echo(mic_text: str, system_texts: list[str], threshold: float = 0.6) -> bool:
    """`system_texts`: frases del sistema que se solapan en el tiempo."""
    if not system_texts:
        return False
    mic = words(mic_text)
    # Con una o dos palabras ("sí", "vale") hace falta coincidencia total.
    needed = 1.0 if len(mic) <= 2 else threshold
    return echo_ratio(mic_text, " ".join(system_texts)) >= needed
