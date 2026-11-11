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


def test_a_sparse_ballad_with_a_long_instrumental_is_not_flagged():
    """R1-31: the denominator is sung time (word spans), not the file length."""
    from lyricloom.model import Transcript, Word
    from lyricloom.stages.transcribe import looks_hallucinated
    words = [Word(f"palavra{i}", 90_000 + i * 3_000, 90_000 + i * 3_000 + 2_000, 0.9) for i in range(40)]
    assert not looks_hallucinated(Transcript("pt", words), 240.0)


def test_too_few_words_in_a_long_file_is_still_flagged_even_with_short_sung_spans():
    from lyricloom.stages.transcribe import looks_hallucinated
    assert looks_hallucinated(_tr(["eu", "vou", "agora"]), 238.6)


def test_whisper_timeout_names_the_reason(monkeypatch, tmp_path):
    import subprocess

    from lyricloom import config
    from lyricloom.stages import transcribe as tr

    def fake_run(cmd, cancel=None, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout_s", 0))

    monkeypatch.setattr(tr, "run_process", fake_run)
    cli = tmp_path / "whisper-cli"
    cli.write_text("", encoding="utf-8")
    model = tmp_path / "ggml.bin"
    model.write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "whisper_cli", lambda: cli)
    monkeypatch.setattr(tr, "_model_path", lambda spec: model)
    with pytest.raises(RuntimeError, match="timed out"):
        tr.transcribe(tmp_path / "missing.wav", tmp_path, "pt")


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


def _capture_cmd(monkeypatch, tmp_path):
    """Runs transcribe() against a fake whisper-cli that records its command line."""
    import types

    from lyricloom import config
    from lyricloom.stages import transcribe as tr
    seen = []

    def fake_run(cmd, cancel=None, **kwargs):
        seen.append(cmd)
        out = Path(cmd[cmd.index("-of") + 1]).with_suffix(".json")
        out.write_text(json.dumps({"result": {"language": "pt"}, "transcription": []}), encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(tr, "run_process", fake_run)
    cli = tmp_path / "whisper-cli"
    cli.write_text("", encoding="utf-8")
    model = tmp_path / "ggml.bin"
    model.write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "whisper_cli", lambda: cli)
    monkeypatch.setattr(tr, "_model_path", lambda spec: model)
    return tr, seen


def test_sung_vocals_are_decoded_without_carried_text_and_with_dtw_times(monkeypatch, tmp_path):
    from lyricloom import models
    tr, seen = _capture_cmd(monkeypatch, tmp_path)
    tr.transcribe(tmp_path / "v.wav", tmp_path, "pt", model=models.get("whisper-large-v3"))
    cmd = seen[0]
    assert cmd[cmd.index("-mc") + 1] == "0"
    assert cmd[cmd.index("-dtw") + 1] == "large.v3" and "-nfa" in cmd
    tr.transcribe(tmp_path / "v.wav", tmp_path, "pt", model=models.get("whisper-large-v3-turbo"))
    assert seen[1][seen[1].index("-dtw") + 1] == "large.v3.turbo"


def test_a_custom_whisper_model_gets_no_dtw_preset(monkeypatch, tmp_path):
    import dataclasses

    from lyricloom import models
    tr, seen = _capture_cmd(monkeypatch, tmp_path)
    base = models.get("whisper-large-v3")
    custom = dataclasses.replace(base, id="custom-whisper", files=(
        dataclasses.replace(base.files[0], filename=str(tmp_path / "my-finetune.bin")),))
    tr.transcribe(tmp_path / "v.wav", tmp_path, "pt", model=custom)
    assert "-dtw" not in seen[0] and "-nfa" not in seen[0]
    assert seen[0][seen[0].index("-mc") + 1] == "0"


def test_word_starts_come_from_dtw_when_the_run_computed_it():
    def token(text, t_dtw, a, b):
        return {"text": text, "t_dtw": t_dtw, "p": 0.9, "offsets": {"from": a, "to": b}}
    data = {"result": {"language": "en"}, "transcription": [
        {"text": " hello", "offsets": {"from": 1000, "to": 1600},
         "tokens": [token("[_BEG_]", -1, 1000, 1000), token(" hello", 112, 1000, 1600)]},
        {"text": " world", "offsets": {"from": 1600, "to": 2200},
         "tokens": [token(" world", -1, 1600, 2200)]},
        {"text": " late", "offsets": {"from": 2200, "to": 2500},
         "tokens": [token(" late", 999, 2200, 2500)]},
    ]}
    words = parse_whisper_json(data).words
    assert [(w.start_ms, w.end_ms) for w in words] == [(1120, 1600), (1600, 2200), (2500, 2500)]
