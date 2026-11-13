"""Separation and alignment on the Windows GPU runtime, and their way back to the CPU."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from lyricloom import config, gpu_runtime
from lyricloom.align import ctc, mtl
from lyricloom.align.anchors import Block
from lyricloom.stages import separate as sep_mod
from lyricloom.workers import WorkerError


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """Selects a runtime whose interpreter exists; returns a function that sets the backend."""
    python = tmp_path / "runtimes" / "env" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")

    def select(backend: str) -> str:
        monkeypatch.setattr(config, "gpu_runtime", lambda: (backend, str(python)))
        return str(python)

    return select


def _separator(calls, device=None, fail=None):
    def run(module, payload, python=None, wsl=None, extra_env=None, **kw):
        calls.append({"module": module, "payload": payload, "python": python, "wsl": wsl,
                      "extra_env": extra_env})
        if fail is not None and python == fail:
            raise WorkerError(module, "CUDA out of memory")
        result = {"vocals": str(Path(payload["out_dir"]) / "vocals_raw.wav")}
        if device:
            result["device"] = device
        return result
    return run


# --------------------------------------------------------------------------- separation


def test_separation_runs_on_the_cuda_runtime(tmp_path, runtime, monkeypatch):
    python, calls = runtime("cuda"), []
    monkeypatch.setattr(sep_mod, "run_worker", _separator(calls, device="cuda"))
    produced, device, fallback = sep_mod._run_separator(tmp_path / "song.flac", tmp_path)
    assert (device, fallback) == ("cuda", None)
    assert produced == tmp_path / "vocals_raw.wav"
    assert len(calls) == 1
    assert calls[0]["python"] == python and calls[0]["wsl"] is None
    assert calls[0]["payload"]["device"] == "cuda"
    # The runtime imports the app's own copy of the workers.
    assert calls[0]["extra_env"]["PYTHONPATH"] == str(gpu_runtime.package_source())


def test_separation_falls_back_to_the_bundled_cpu_worker_when_the_runtime_fails(
        tmp_path, runtime, monkeypatch):
    python, calls = runtime("cuda"), []
    monkeypatch.setattr(sep_mod, "run_worker", _separator(calls, fail=python))
    _, device, fallback = sep_mod._run_separator(tmp_path / "song.flac", tmp_path)
    assert [call["python"] for call in calls] == [python, config.SEPARATOR_PYTHON]
    assert device == config.SEPARATOR_DEVICE
    assert fallback.startswith("the Windows GPU runtime (cuda) failed, so separation ran on the CPU")
    assert "CUDA out of memory" in fallback


def test_a_broken_runtime_falls_back_and_says_how_to_repair_it(tmp_path, runtime, monkeypatch):
    """What a power loss right after the setup left behind on a real machine."""
    python = runtime("directml")

    def run(module, payload, python=None, **kw):
        if python == runtime_python:
            raise WorkerError(module, "error: uv trampoline failed to spawn Python child process"
                                      "\n  Caused by: entity not found (os error 2)")
        return {"vocals": str(Path(payload["out_dir"]) / "vocals_raw.wav")}

    runtime_python = python
    monkeypatch.setattr(sep_mod, "run_worker", run)
    _, device, fallback = sep_mod._run_separator(tmp_path / "song.flac", tmp_path)
    assert device == config.SEPARATOR_DEVICE
    assert "uv trampoline failed" in fallback
    assert 'run "Set up and use" again' in fallback


def test_a_deleted_runtime_is_named_in_the_fallback_instead_of_crashing(tmp_path, monkeypatch):
    calls = []
    missing = str(tmp_path / "gone" / "python.exe")
    monkeypatch.setattr(config, "gpu_runtime", lambda: ("cuda", missing))
    monkeypatch.setattr(sep_mod, "run_worker", _separator(calls))
    _, _, fallback = sep_mod._run_separator(tmp_path / "song.flac", tmp_path)
    assert len(calls) == 1 and calls[0]["python"] == config.SEPARATOR_PYTHON
    assert "the Windows GPU runtime is missing" in fallback and "Setup assistant" in fallback
    assert 'run "Set up and use" again' in fallback


def test_directml_with_a_roformer_model_is_reported_as_cpu_with_the_reason(
        tmp_path, runtime, monkeypatch):
    runtime("directml")
    calls = []
    monkeypatch.setattr(sep_mod, "run_worker", _separator(calls, device="cpu"))
    _, device, fallback = sep_mod._run_separator(tmp_path / "song.flac", tmp_path)
    assert device == "cpu" and len(calls) == 1
    assert calls[0]["payload"]["device"] == "directml"
    assert fallback.startswith("DirectML keeps Mel-Band RoFormer")
    assert "MDX-Net" in fallback and "16 GB" in fallback
    assert "directml_roformer" not in calls[0]["payload"]      # off unless the user asked


def test_roformer_on_directml_is_requested_only_when_the_option_is_on(tmp_path, runtime,
                                                                      monkeypatch):
    runtime("directml")
    gpu_runtime.set_directml_roformer(True)
    calls = []
    monkeypatch.setattr(sep_mod, "run_worker", _separator(calls, device="dml"))
    _, device, fallback = sep_mod._run_separator(tmp_path / "song.flac", tmp_path)
    assert calls[0]["payload"]["directml_roformer"] is True
    assert (device, fallback) == ("dml", None)


def test_the_option_is_never_sent_to_a_cuda_runtime(tmp_path, runtime, monkeypatch):
    runtime("cuda")
    gpu_runtime.set_directml_roformer(True)
    calls = []
    monkeypatch.setattr(sep_mod, "run_worker", _separator(calls, device="cuda"))
    sep_mod._run_separator(tmp_path / "song.flac", tmp_path)
    assert "directml_roformer" not in calls[0]["payload"]


def test_running_out_of_video_memory_falls_back_with_a_hint(tmp_path, runtime, monkeypatch):
    python = runtime("directml")
    gpu_runtime.set_directml_roformer(True)
    calls = []

    def run(module, payload, python=None, **kw):
        calls.append(python)
        if python == runtime_python:
            raise WorkerError(module, "RuntimeError: Could not allocate tensor with 405868544 "
                                      "bytes. There is not enough GPU video memory available!")
        return {"vocals": str(Path(payload["out_dir"]) / "vocals_raw.wav")}

    runtime_python = python
    monkeypatch.setattr(sep_mod, "run_worker", run)
    _, device, fallback = sep_mod._run_separator(tmp_path / "song.flac", tmp_path)
    assert calls == [python, config.SEPARATOR_PYTHON]
    assert "not enough GPU video memory" in fallback
    assert fallback.endswith("choose a smaller separator model.)")


def test_directml_with_a_supported_model_is_reported_as_dml(tmp_path, runtime, monkeypatch):
    runtime("directml")
    monkeypatch.setattr(sep_mod, "run_worker", _separator([], device="dml"))
    _, device, fallback = sep_mod._run_separator(tmp_path / "song.flac", tmp_path)
    assert (device, fallback) == ("dml", None)


def test_the_runtime_wins_over_a_wsl_setting_left_from_before(tmp_path, runtime, monkeypatch):
    python, calls = runtime("cuda"), []
    monkeypatch.setattr(config, "SEPARATOR_WSL_ENABLED", True)
    monkeypatch.setattr(sep_mod, "run_worker", _separator(calls, device="cuda"))
    sep_mod._run_separator(tmp_path / "song.flac", tmp_path)
    assert [(call["python"], call["wsl"]) for call in calls] == [(python, None)]


def test_forcing_the_cpu_skips_the_runtime(tmp_path, runtime, monkeypatch):
    runtime("cuda")
    calls = []
    monkeypatch.setattr(config, "SEPARATOR_DEVICE", "cpu")
    monkeypatch.setattr(sep_mod, "run_worker", _separator(calls))
    _, device, fallback = sep_mod._run_separator(tmp_path / "song.flac", tmp_path)
    assert [call["python"] for call in calls] == [config.SEPARATOR_PYTHON]
    assert (device, fallback) == ("cpu", None)


def test_the_worker_reports_the_device_the_model_really_uses():
    pytest.importorskip("audio_separator")
    from lyricloom.workers.separate import actual_device

    def separator(kind, own=None):
        instance = SimpleNamespace(torch_device=SimpleNamespace(type=kind))
        return SimpleNamespace(model_instance=instance,
                               torch_device=SimpleNamespace(type=own or kind))

    assert actual_device(separator("cuda")) == "cuda"
    assert actual_device(separator("privateuseone")) == "dml"
    # audio-separator moved a RoFormer model to the CPU although DirectML was configured.
    assert actual_device(separator("cpu", own="privateuseone")) == "cpu"
    assert actual_device(SimpleNamespace()) == "cpu"


# --------------------------------------------------------------------------- alignment


def _ctc_result() -> dict:
    return {"blocks": [{"lines": [{"segments": [{"start_ms": 100, "end_ms": 400, "score": 0.9}]}]}]}


def _align(calls, result, fail=None):
    def run(module, payload, python=None, wsl=None, extra_env=None, **kw):
        calls.append({"payload": payload, "python": python, "wsl": wsl, "extra_env": extra_env})
        if fail is not None and python == fail:
            raise WorkerError(module, "CUDA error: device-side assert")
        return result
    return run


def test_ctc_alignment_runs_on_the_cuda_runtime(runtime, monkeypatch):
    python, calls = runtime("cuda"), []
    monkeypatch.setattr(ctc, "run_worker", _align(calls, _ctc_result()))
    out = ctc.align_blocks(Path(r"C:\work\vocals16k.wav"), [Block(0, 1, 5000, 9000)], [[["eu"]]])
    assert len(calls) == 1 and calls[0]["python"] == python
    assert calls[0]["payload"]["device"] == "cuda"
    assert calls[0]["payload"]["wav"] == r"C:\work\vocals16k.wav"     # Windows paths, no /mnt
    assert "PYTHONPATH" in calls[0]["extra_env"]
    assert out[0][0].start_ms == 5100


def test_ctc_alignment_falls_back_to_the_cpu_when_the_runtime_fails(runtime, monkeypatch):
    python, calls = runtime("cuda"), []
    monkeypatch.setattr(ctc, "run_worker", _align(calls, _ctc_result(), fail=python))
    out = ctc.align_blocks(Path("v.wav"), [Block(0, 1, 5000, 9000)], [[["eu"]]])
    assert [call["python"] for call in calls] == [python, None]
    assert calls[1]["payload"]["device"] == config.ALIGN_DEVICE
    assert out[0][0].start_ms == 5100


def test_alignment_stays_on_the_cpu_with_directml(runtime, monkeypatch):
    runtime("directml")
    calls = []
    monkeypatch.setattr(ctc, "run_worker", _align(calls, _ctc_result()))
    monkeypatch.setattr(mtl, "run_worker", _align(calls, {"words": [["texto", 1000, 1400]]}))
    ctc.align_blocks(Path("v.wav"), [Block(0, 1, 5000, 9000)], [[["eu"]]])
    mtl.align_lines_mtl(Path("v.wav"), [["Texto, "]])
    assert [call["python"] for call in calls] == [None, str(config.MTL_PYTHON)]
    assert all(call["payload"].get("cuda") is None for call in calls)


def test_the_singing_model_runs_on_the_cuda_runtime(runtime, monkeypatch):
    python, calls = runtime("cuda"), []
    monkeypatch.setattr(mtl, "run_worker", _align(calls, {"words": [["texto", 1000, 1400]]}))
    out = mtl.align_lines_mtl(Path(r"C:\work\vocals.wav"), [["Texto, "]])
    assert len(calls) == 1 and calls[0]["python"] == python
    assert calls[0]["payload"]["cuda"] is True
    assert calls[0]["payload"]["repo"] == str(config.MTL_REPO)      # the app's own model code
    assert (out[0][0].start_ms, out[0][0].end_ms) == (1000, 1400)


def test_the_singing_model_falls_back_to_the_cpu_when_the_runtime_fails(runtime, monkeypatch):
    python, calls = runtime("cuda"), []
    monkeypatch.setattr(mtl, "run_worker",
                        _align(calls, {"words": [["texto", 1000, 1400]]}, fail=python))
    mtl.align_lines_mtl(Path("v.wav"), [["Texto, "]])
    assert [call["python"] for call in calls] == [python, str(config.MTL_PYTHON)]
    assert calls[1]["payload"].get("cuda") is None
