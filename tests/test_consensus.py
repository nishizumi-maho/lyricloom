from lyricloom.align.consensus import refrain_consensus, rover
from lyricloom.model import Transcript, Word


def _tr(text, probs=None, t0=0):
    ws = text.split()
    probs = probs or [0.9] * len(ws)
    return Transcript("pt", [Word(w, t0 + i * 400, t0 + i * 400 + 300, p) for i, (w, p) in enumerate(zip(ws, probs))])


def test_rover_majority_wins():
    out = rover([_tr("palavra teste e exemplo"), _tr("palavra testes e exemplo"),
                 _tr("palavra testes e exemplo")], "pt")
    assert [w.text for w in out.words] == ["palavra", "testes", "e", "exemplo"]


def test_rover_keeps_primary_timing():
    out = rover([_tr("a b c", t0=1000), _tr("a x c", t0=0), _tr("a x c", t0=0)], "pt")
    assert [w.start_ms for w in out.words] == [1000, 1400, 1800]
    assert out.words[1].text == "x"


def test_rover_tie_uses_highest_probability():
    out = rover([_tr("teste e prova", [0.4, 0.9, 0.5]), _tr("testes e prova", [0.8, 0.9, 0.7])], "pt")
    assert [w.text for w in out.words] == ["testes", "e", "prova"]


def test_rover_never_drops_primary_words():
    out = rover([_tr("eu vou agora"), _tr("eu agora"), _tr("eu agora")], "pt")
    assert [w.text for w in out.words] == ["eu", "vou", "agora"]


def _lines(*texts):
    return [_tr(t).words for t in texts]


def test_refrain_consensus_fixes_minority_repetition():
    lines = _lines("linha de teste e exemplo vão", "outra linha qualquer aqui",
                   "linha de testes e exemplo vão", "linha de testes e exemplo vão")
    out = [" ".join(w.text for w in l) for l in refrain_consensus(lines, "pt")]
    assert out[0] == "linha de testes e exemplo vão"
    assert out[1] == "outra linha qualquer aqui"


def test_refrain_consensus_leaves_different_verses_alone():
    lines = _lines("essas linhas são de teste", "essas trilhas são de teste")
    out = [" ".join(w.text for w in l) for l in refrain_consensus(lines, "pt")]
    assert out == ["essas linhas são de teste", "essas trilhas são de teste"]
