from pathlib import Path

import pytest

from lyricloom.align import mtl
from lyricloom.model import Candidate, Segment, TrackMeta, Transcript, Word
from lyricloom.stages import align as stage
from lyricloom.workers import WorkerError

META = TrackMeta(Path("x.flac"), "Test Artist", "Synthetic Song", "", 20.0, "other")


def test_mtl_words_map_onto_segments_in_order():
    segs = [["Texto, ", "inventado ", "para"], ["- ", "o ", "teste"]]
    words = [["texto", 1000, 1400], ["inventado", 1400, 1600], ["para", 1600, 2000], ["o", 3000, 3200], ["teste", 3200, 3600]]
    out = mtl.map_words(segs, words)
    assert [(s.start_ms, s.end_ms) for s in out[0]] == [(1000, 1400), (1400, 1600), (1600, 2000)]
    assert out[1][0] is None                      # "-" has no letters: no word of its own
    assert (out[1][1].start_ms, out[1][2].start_ms) == (3000, 3200)


def test_mismatched_word_count_is_an_error():
    with pytest.raises(ValueError):
        mtl.map_words([["a ", "b"]], [["a", 0, 100]])


def _fake_ctc(calls):
    def fake(vocals16k, blocks, seg_tokens):
        calls.append("ctc")
        t, out = 1000, []
        for block in seg_tokens:
            for line in block:
                out.append([None if not tok else Segment("", t + 400 * i, t + 400 * i + 300, 0.9) for i, tok in enumerate(line)])
        return out
    return fake


def _fake_mtl(calls, fail=False):
    def fake(vocals, seg_texts):
        calls.append("mtl")
        if fail:
            raise WorkerError("lyricloom.workers.align_mtl", "boom")
        return [[Segment("", 1000 + 400 * i, 1300 + 400 * i, 1.0) for i, _ in enumerate(line)] for line in seg_texts]
    return fake


def _run(monkeypatch, lang, fail=False, enabled=True):
    calls = []
    monkeypatch.setattr(stage, "align_blocks", _fake_ctc(calls))
    monkeypatch.setattr(stage, "align_lines_mtl", _fake_mtl(calls, fail))
    monkeypatch.setattr("lyricloom.config.MTL_ENABLED", enabled)
    monkeypatch.setattr(stage.models, "singing_ready", lambda lang=None: enabled)
    tr = Transcript(lang, [Word("texto", 1000, 1300, 0.9), Word("inventado", 1400, 1700, 0.9), Word("para", 1800, 2100, 0.9)])
    res = stage.align(META, Path("."), Candidate("netease", "texto inventado para"), tr, Path("v16.wav"), Path("v.wav"))
    return calls, res


def test_english_uses_the_singing_model(monkeypatch):
    calls, res = _run(monkeypatch, "en")
    assert calls == ["mtl"]
    assert [s.start_ms for s in res.lines[0].segments] == [1000, 1400, 1800]


def test_other_languages_keep_the_ctc_aligner(monkeypatch):
    calls, _ = _run(monkeypatch, "pt")
    assert calls == ["ctc"]


def test_singing_model_failure_falls_back_to_ctc(monkeypatch):
    calls, res = _run(monkeypatch, "en", fail=True)
    assert calls == ["mtl", "ctc"]
    assert res.lines[0].segments[0].start_ms is not None


def test_singing_model_off_when_not_installed(monkeypatch):
    calls, _ = _run(monkeypatch, "en", enabled=False)
    assert calls == ["ctc"]


def test_english_does_not_start_mtl_when_its_checkpoint_is_missing(monkeypatch):
    """R1-25: the vendored wrapper exists on every install, but without the checkpoint or NLTK
    data English must go straight to CTC instead of starting a worker that cannot load."""
    calls = []
    monkeypatch.setattr(stage, "align_blocks", _fake_ctc(calls))
    monkeypatch.setattr(stage, "align_lines_mtl", _fake_mtl(calls))
    monkeypatch.setattr("lyricloom.config.MTL_ENABLED", True)
    tr = Transcript("en", [Word("texto", 1000, 1300, 0.9)])
    stage.align(META, Path("."), Candidate("netease", "texto"), tr, Path("v16.wav"), Path("v.wav"))
    assert calls == ["ctc"]


def test_english_line_confidence_comes_from_whisper_confirmation(monkeypatch):
    _, res = _run(monkeypatch, "en")
    assert res.lines[0].conf >= 0.6          # the line was heard by Whisper: an anchor


# --- the singing model on the GPU through WSL, and its .venv-mtl fallback ---------------------

from lyricloom import config


def test_singing_model_runs_in_wsl_on_the_gpu(monkeypatch):
    calls = []

    def fake(module, payload, python=None, wsl=None, wsl_env=None, **kw):
        calls.append({"payload": payload, "wsl": wsl, "python": python})
        return {"words": [["texto", 1000, 1400]]}

    monkeypatch.setattr(mtl, "run_worker", fake)
    monkeypatch.setattr(config, "MTL_WSL_ENABLED", True)
    out = mtl.align_lines_mtl(Path(r"C:\work\vocals.wav"), [["Texto, "]])
    assert calls[0]["wsl"] == config.ALIGN_WSL_DISTRO and calls[0]["python"] == config.ALIGN_WSL_PYTHON
    assert calls[0]["payload"]["cuda"] is True
    assert calls[0]["payload"]["wav"] == "/mnt/c/work/vocals.wav"
    assert calls[0]["payload"]["repo"] == config.MTL_WSL_REPO
    assert (out[0][0].start_ms, out[0][0].end_ms) == (1000, 1400)


def test_singing_model_falls_back_to_its_own_venv(monkeypatch):
    calls = []

    def fake(module, payload, python=None, wsl=None, wsl_env=None, **kw):
        calls.append({"payload": payload, "wsl": wsl, "python": python})
        if wsl:
            raise WorkerError(module, "HIP error: no device")
        return {"words": [["texto", 1000, 1400]]}

    monkeypatch.setattr(mtl, "run_worker", fake)
    monkeypatch.setattr(config, "MTL_WSL_ENABLED", True)
    mtl.align_lines_mtl(Path(r"C:\work\vocals.wav"), [["Texto, "]])
    assert [c["wsl"] for c in calls] == [config.ALIGN_WSL_DISTRO, None]
    assert calls[1]["python"] == str(config.MTL_PYTHON)
    assert calls[1]["payload"].get("cuda") is None    # the Windows venv stays on its CPU

