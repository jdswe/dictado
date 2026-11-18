import numpy as np

from dictado.audio import BLOCK_SECONDS, RATE, Segmenter
from dictado.echo import echo_ratio, is_echo
from dictado.engine import is_hallucination
from dictado.transcription import Line, Merger


def test_echo_detects_repeated_speech():
    system = "y entonces la función devuelve una promesa que se resuelve después"
    assert is_echo("entonces la función devuelve una promesa", [system])
    assert not is_echo("vale, yo creo que hay que cambiar el test", [system])
    assert not is_echo("sí", ["no lo sé"])
    assert is_echo("Sí.", ["sí"])
    assert echo_ratio("Canción", "cancion") == 1.0  # sin tildes ni mayúsculas


def test_merger_orders_and_drops_echo():
    out = []
    m = Merger(out.append, echo_filter=True)
    m.add(Line("mic", 10.0, 12.0, "hola qué tal"))
    m.add(Line("system", 5.0, 9.0, "bienvenidos a la clase de hoy"))
    m.add(Line("mic", 6.0, 8.5, "bienvenidos a la clase"))  # eco
    m.flush(11.0)  # nada está a salvo todavía con el margen de eco
    assert [l.text for l in out] == []
    m.flush(100.0)
    assert [(l.source, l.text) for l in out] == [
        ("system", "bienvenidos a la clase de hoy"),
        ("mic", "hola qué tal"),
    ]


def test_merger_without_echo_filter_keeps_everything():
    out = []
    m = Merger(out.append, echo_filter=False)
    m.add(Line("mic", 1.0, 2.0, "uno"))
    m.add(Line("system", 0.5, 1.5, "uno"))
    m.flush_all()
    assert [l.source for l in out] == ["system", "mic"]


def test_segmenter_cuts_on_silence():
    chunks = []
    seg = Segmenter(lambda audio, t: chunks.append((audio.size / RATE, t)))
    n = int(RATE * BLOCK_SECONDS)
    t = 1000.0
    rng = np.random.default_rng(0)
    pattern = [0.0] * 10 + [0.2] * 15 + [0.0] * 12 + [0.2] * 5 + [0.0] * 10
    for amp in pattern:
        block = (rng.standard_normal(n) * amp).astype(np.float32) if amp else np.zeros(n, np.float32)
        seg.feed(block, t)
        t += BLOCK_SECONDS
    assert len(chunks) == 2
    first_len, first_start = chunks[0]
    assert abs(first_start - (1000.0 + 0.7)) < 0.01  # 0.3 s de margen antes de la voz
    assert 2.0 < first_len < 2.6


def test_hallucination_filter():
    assert is_hallucination("Subtítulos realizados por la comunidad de Amara.org")
    assert is_hallucination("...")
    assert not is_hallucination("Gracias.", no_speech_prob=0.05)
    assert is_hallucination("Gracias.", no_speech_prob=0.6)
    assert not is_hallucination("Hola, ¿cómo estás?")
