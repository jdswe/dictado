"""Text-based echo filter.

With speakers, the microphone also picks up what the others say. Since the
system audio is transcribed separately, a microphone phrase whose words
already appear in what the speakers played at that same moment is echo and is
dropped. With headphones it never triggers.
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
    """Fraction of the microphone's words that are also in the system audio."""
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
    """`system_texts`: system phrases that overlap in time."""
    if not system_texts:
        return False
    mic = words(mic_text)
    # With one or two words ("yes", "ok") it takes a full match.
    needed = 1.0 if len(mic) <= 2 else threshold
    return echo_ratio(mic_text, " ".join(system_texts)) >= needed
