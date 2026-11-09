import json
from pathlib import Path

import pytest

from lyricloom.stages.transcribe import parse_whisper_json

FX = Path(__file__).resolve().parent / "fixtures"


def _fixture():
    return json.loads((FX / "whisper_full.json").read_text(encoding="utf-8"))


def test_parse_language_and_first_words():
    t = parse_whisper_json(_fixture())
    assert t.lang == "en"
    assert [w.text for w in t.words[:3]] == ["And", "so,", "my"]
    assert (t.words[0].start_ms, t.words[0].end_ms) == (320, 370)
    assert 0.0 < t.words[0].prob <= 1.0


def test_parse_skips_special_tokens_and_empty_segments():
    t = parse_whisper_json(_fixture())
    assert all(w.text and not w.text.startswith("[_") for w in t.words)
    assert t.text.startswith("And so, my fellow Americans")


def _tr(texts, step=1000):
    from lyricloom.model import Transcript, Word
    return Transcript("ja", [Word(t, i * step, i * step + step, 0.9) for i, t in enumerate(texts)])


def test_credit_hallucination_is_detected():
    from lyricloom.stages.transcribe import looks_hallucinated
    # what Whisper produced on a Japanese test clip: credits repeated every 30 s
    tr = _tr(["作詞・作曲・編曲", "テスト歌手"] * 10, step=11000)
    assert looks_hallucinated(tr, 238.6)


def test_too_few_words_for_the_song_is_detected():
    from lyricloom.stages.transcribe import looks_hallucinated
    assert looks_hallucinated(_tr(["eu", "vou", "agora"]), 238.6)


def test_endless_repetition_is_detected():
    from lyricloom.stages.transcribe import looks_hallucinated
    assert looks_hallucinated(_tr(["obrigado", "por", "assistir"] * 60, step=1000), 200)


def test_real_singing_is_not_flagged():
    from lyricloom.stages.transcribe import looks_hallucinated
    words = ("texto inventado para o teste sem nenhuma canção real e com palavras variadas "
             "para validar o detector de alucinações sem repetir demais").split()
    assert not looks_hallucinated(_tr(words * 9, step=500), 238.6)


def test_missing_whisper_cli_error_names_the_real_setting(tmp_path, monkeypatch):
    from lyricloom import config
    from lyricloom.stages import transcribe

    monkeypatch.setattr(config, "whisper_cli", lambda: tmp_path / "missing-whisper-cli")
    with pytest.raises(RuntimeError, match="whisper_cli"):
        transcribe.transcribe(FX / "jfk.wav", tmp_path, "en")



@pytest.mark.gpu
def test_transcribe_jfk(tmp_path):
    from lyricloom.stages.transcribe import transcribe

    t = transcribe(FX / "jfk.wav", tmp_path, "en")
    assert "fellow Americans" in t.text
