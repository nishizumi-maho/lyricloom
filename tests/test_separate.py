import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from lyricloom.workers import WorkerError, run_worker

TESTS = Path(__file__).resolve().parent


def _run(payload):
    # fake_worker lives in tests/, so run it with tests/ on the import path.
    return run_worker("fake_worker", payload, python=sys.executable, cwd=TESTS)


def test_run_worker_roundtrips_unicode_paths():
    p = {"wav": r"F:\X\Library\テスト歌手\01 - Synthetic Song.flac"}
    assert _run(p) == {"echo": p}


def test_run_worker_raises_with_stderr_tail():
    with pytest.raises(WorkerError) as e:
        _run({"fail": True})
    assert "boom from worker" in str(e.value)


@pytest.mark.gpu
def test_separate_synthetic(tmp_path):
    from lyricloom.stages.separate import separate

    sr = 44100
    t = np.arange(sr * 10) / sr
    sig = (0.3 * np.sin(2 * np.pi * 440 * t) + 0.05 * np.random.default_rng(0).standard_normal(t.size))
    audio = tmp_path / "in.wav"
    sf.write(str(audio), np.stack([sig, sig], axis=1).astype("float32"), sr)
    out = separate(audio, tmp_path / "work")
    info = sf.info(out["vocals16k"])
    assert info.samplerate == 16000 and info.channels == 1
    assert abs(info.duration - 10.0) < 0.05
    assert Path(out["vocals"]).exists()


# --- separation on the GPU through WSL, and the kept vocals ---------------------------------

import subprocess

from lyricloom import config
from lyricloom.stages import separate as sep_mod
from lyricloom.workers import RESULT_MARK, windows_path, wsl_path


def _wav(path: Path, subtype: str = "PCM_16", seconds: float = 1.0, sr: int = 44100) -> np.ndarray:
    """Writes a stereo test tone; returns the samples as the integers stored in the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(sr * seconds)) / sr
    sig = 0.3 * np.sin(2 * np.pi * 440 * t) + 0.01 * np.random.default_rng(1).standard_normal(t.size)
    sf.write(str(path), np.stack([sig, -sig], axis=1).astype("float32"), sr, subtype=subtype)
    return sf.read(str(path), dtype="int32")[0]


def test_wsl_path_maps_drive_letters_both_ways():
    win = r"F:\X\Library\テスト歌手\01 - Synthetic Song.flac"
    assert wsl_path(win) == "/mnt/f/X/Library/テスト歌手/01 - Synthetic Song.flac"
    assert windows_path(wsl_path(win)) == Path(win)
    assert windows_path("/tmp/sep/vocals.wav") == Path("/tmp/sep/vocals.wav")


def test_run_worker_in_wsl_builds_the_command(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["input"] = argv, kw["input"]
        return subprocess.CompletedProcess(argv, 0, (RESULT_MARK + '{"ok": 1}\n').encode(), b"")

    monkeypatch.setattr("lyricloom.workers.subprocess.run", fake_run)
    res = run_worker("some.module", {"a": 1}, python="/opt/lyricloom/venv/bin/python", cwd=Path(r"C:\Music\LyricLoom"),
                     wsl="Ubuntu", wsl_env={"HSA_ENABLE_DXG_DETECTION": "1"})
    argv = seen["argv"]
    assert res == {"ok": 1}
    assert argv[:7] == ["wsl.exe", "-d", "Ubuntu", "--cd", "/mnt/c/Music/LyricLoom", "--exec", "env"]
    assert "HSA_ENABLE_DXG_DETECTION=1" in argv and f"OMP_NUM_THREADS={config.CPU_THREADS}" in argv
    assert argv[-3:] == ["/opt/lyricloom/venv/bin/python", "-m", "some.module"]


def _fake_worker(calls: list, fail_wsl: bool = False):
    """Stands in for run_worker: 'separates' by copying the input, like the real worker's output."""
    def run(module, payload, python=None, wsl=None, wsl_env=None, **kw):
        calls.append({"payload": payload, "wsl": wsl, "python": python})
        if wsl and fail_wsl:
            raise WorkerError(module, "HIP error: no device")
        out_dir = windows_path(payload["out_dir"]) if wsl else Path(payload["out_dir"])
        raw = out_dir / "vocals_raw.wav"
        raw.write_bytes((windows_path(payload["audio"]) if wsl else Path(payload["audio"])).read_bytes())
        return {"vocals": wsl_path(raw) if wsl else str(raw)}
    return run


@pytest.fixture
def library(tmp_path, monkeypatch):
    root = tmp_path / "Library"
    monkeypatch.setattr("lyricloom.config.LIBRARY_ROOT", root)
    return root


def test_separate_runs_in_wsl_with_translated_paths(tmp_path, library, monkeypatch):
    calls = []
    monkeypatch.setattr(config, "SEPARATOR_WSL_ENABLED", True)
    monkeypatch.setattr(sep_mod, "run_worker", _fake_worker(calls))
    audio = library / "Test Artist" / "Test Album" / "01 - Synthetic Song.flac"
    _wav(audio)
    out = sep_mod.separate(audio, tmp_path / "work")
    assert out["device"] == "rocm" and "fallback" not in out
    p = calls[0]["payload"]
    assert calls[0]["wsl"] == config.SEPARATOR_WSL_DISTRO and calls[0]["python"] == config.SEPARATOR_WSL_PYTHON
    assert all(p[k].startswith("/mnt/") for k in ("audio", "out_dir", "model_dir"))
    assert Path(out["vocals"]).exists() and sf.info(out["vocals16k"]).samplerate == 16000


def test_separate_falls_back_to_cpu_when_wsl_fails(tmp_path, library, monkeypatch):
    calls = []
    monkeypatch.setattr(config, "SEPARATOR_WSL_ENABLED", True)
    monkeypatch.setattr(sep_mod, "run_worker", _fake_worker(calls, fail_wsl=True))
    audio = library / "Test Artist" / "Test Album" / "01 - Synthetic Song.flac"
    _wav(audio)
    out = sep_mod.separate(audio, tmp_path / "work")
    assert [c["wsl"] for c in calls] == [config.SEPARATOR_WSL_DISTRO, None]
    assert out["device"] == config.SEPARATOR_DEVICE and "no device" in out["fallback"]
    assert Path(out["kept"]).exists()


def test_kept_vocals_mirror_the_library(tmp_path, library):
    assert sep_mod.kept_vocals_path(library / "Test Artist" / "Test Album" / "01 - Synthetic Song.flac") == \
        config.vocals_root() / "Test Artist" / "Test Album" / "01 - Synthetic Song.vocals.flac"
    outside = tmp_path / "Other" / "テスト歌手" / "2020 - Synthetic Album [Single]" / "01 - Synthetic Song.flac"
    assert sep_mod.kept_vocals_path(outside) == \
        config.vocals_root() / "テスト歌手" / "2020 - Synthetic Album [Single]" / "01 - Synthetic Song.vocals.flac"


def test_vocals_root_is_a_setting(tmp_path):
    config.set_vocals_root(tmp_path / "Elsewhere")
    assert config.vocals_root() == tmp_path / "Elsewhere"


@pytest.mark.parametrize("subtype", ["PCM_16", "PCM_24"])
def test_keep_vocals_is_bit_exact_flac(tmp_path, library, subtype):
    stem = tmp_path / "work" / "vocals.wav"
    samples = _wav(stem, subtype)
    kept = sep_mod.keep_vocals(library / "A" / "B" / "01 - C.flac", stem)
    info = sf.info(str(kept))
    assert info.format == "FLAC" and info.subtype == subtype
    assert np.array_equal(sf.read(str(kept), dtype="int32")[0], samples)


def test_keep_vocals_never_overwrites_and_skips_missing_stems(tmp_path, library):
    audio = library / "A" / "B" / "01 - C.flac"
    assert sep_mod.keep_vocals(audio, tmp_path / "missing.wav") is None
    stem = tmp_path / "vocals.wav"
    _wav(stem)
    kept = sep_mod.keep_vocals(audio, stem)
    before = kept.stat().st_mtime_ns
    _wav(stem, seconds=2.0)
    assert sep_mod.keep_vocals(audio, stem) == kept and kept.stat().st_mtime_ns == before


def test_separate_reuses_kept_vocals_without_separating(tmp_path, library, monkeypatch):
    audio = library / "A" / "B" / "01 - C.flac"
    _wav(audio)
    samples = _wav(tmp_path / "old.wav", "PCM_24")
    sep_mod.keep_vocals(audio, tmp_path / "old.wav")

    def no_worker(*a, **kw):
        raise AssertionError("separator should not run when the vocals are kept")

    monkeypatch.setattr(sep_mod, "run_worker", no_worker)
    out = sep_mod.separate(audio, tmp_path / "work")
    assert out["device"] == "kept"
    assert np.array_equal(sf.read(out["vocals"], dtype="int32")[0], samples)
    assert sf.info(out["vocals"]).subtype == "PCM_24"


@pytest.mark.gpu
def test_separate_in_wsl_on_the_gpu(tmp_path, library, monkeypatch):
    monkeypatch.setattr(config, "SEPARATOR_WSL_ENABLED", True)
    audio = library / "A" / "B" / "01 - tone.wav"
    _wav(audio, seconds=10.0)
    out = sep_mod.separate(audio, tmp_path / "work")
    assert out["device"] == "rocm", out.get("fallback")
    assert abs(sf.info(out["vocals16k"]).duration - 10.0) < 0.05

