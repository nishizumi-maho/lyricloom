import json
from pathlib import Path

import pytest

from lyricloom import config
from lyricloom.align import ctc
from lyricloom.align.anchors import Block
from lyricloom.workers import WorkerError

FX = Path(__file__).resolve().parent / "fixtures"


def test_align_blocks_converts_to_absolute_time(monkeypatch):
    seen = {}

    def fake_worker(module, payload, **kw):
        seen.update(payload)
        return {"blocks": [{"lines": [{"segments": [{"start_ms": 100, "end_ms": 400, "score": 0.9}, None]}]}]}

    monkeypatch.setattr(ctc, "run_worker", fake_worker)
    out = ctc.align_blocks(Path("v.wav"), [Block(0, 1, 5000, 9000)], [[["eu", ""]]])
    assert seen["device"] == "cpu"
    assert seen["blocks"][0]["start_ms"] == 5000
    seg_a, seg_b = out[0]
    assert (seg_a.start_ms, seg_a.end_ms, seg_a.conf) == (5100, 5400, 0.9)
    assert seg_b is None


@pytest.mark.gpu
def test_ctc_matches_synthesizer_ground_truth():
    # Windows SAPI reports when it starts each word: a true reference, unlike Whisper's own
    # word times, which glue each word to the previous one and absorb pauses.
    truth = json.loads((FX / "tts_sample.json").read_text(encoding="utf-8-sig"))
    ref = sorted(w["start_ms"] for w in truth["words"])
    words = truth["text"].split()
    assert len(ref) == len(words)
    out = ctc.align_blocks(FX / "tts_sample.wav", [Block(0, 1, 0, ref[-1] + 2000)], [[words]])
    starts = [s.start_ms for s in out[0]]
    assert starts == sorted(starts)
    errors = sorted(abs(a - b) for a, b in zip(starts, ref))
    assert errors[len(errors) // 2] < 100  # median word-start error (spec target: < ~100 ms)
    assert errors[-1] < 250


def _result() -> dict:
    return {"blocks": [{"lines": [{"segments": [{"start_ms": 100, "end_ms": 400, "score": 0.9}]}]}]}


def test_align_blocks_runs_in_wsl_on_the_gpu(monkeypatch):
    calls = []

    def fake(module, payload, python=None, wsl=None, wsl_env=None, **kw):
        calls.append({"payload": payload, "wsl": wsl, "python": python})
        return _result()

    monkeypatch.setattr(ctc, "run_worker", fake)
    monkeypatch.setattr(config, "ALIGN_WSL_ENABLED", True)
    out = ctc.align_blocks(Path(r"C:\work\vocals16k.wav"), [Block(0, 1, 5000, 9000)], [[["eu"]]])
    assert calls[0]["wsl"] == config.ALIGN_WSL_DISTRO and calls[0]["python"] == config.ALIGN_WSL_PYTHON
    assert calls[0]["payload"]["device"] == "cuda"
    assert calls[0]["payload"]["wav"] == "/mnt/c/work/vocals16k.wav"
    assert out[0][0].start_ms == 5100


def test_align_blocks_falls_back_to_the_cpu_when_wsl_fails(monkeypatch):
    calls = []

    def fake(module, payload, python=None, wsl=None, wsl_env=None, **kw):
        calls.append({"payload": payload, "wsl": wsl})
        if wsl:
            raise WorkerError(module, "HIP error: no device")
        return _result()

    monkeypatch.setattr(ctc, "run_worker", fake)
    monkeypatch.setattr(config, "ALIGN_WSL_ENABLED", True)
    out = ctc.align_blocks(Path("vocals16k.wav"), [Block(0, 1, 0, 5000)], [[["eu"]]])
    assert [c["wsl"] for c in calls] == [config.ALIGN_WSL_DISTRO, None]
    assert calls[1]["payload"]["device"] == "cpu"
    assert out[0][0].start_ms == 100
