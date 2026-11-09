import hashlib
import json
import os
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
    assert str(windows_path(wsl_path(win))).replace("\\", "/") == win.replace("\\", "/")
    assert windows_path("/tmp/sep/vocals.wav") == Path("/tmp/sep/vocals.wav")


def test_run_worker_in_wsl_builds_the_command(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["input"] = argv, kw["input_bytes"]
        return subprocess.CompletedProcess(argv, 0, (RESULT_MARK + '{"ok": 1}\n').encode(), b"")

    monkeypatch.setattr("lyricloom.workers.run_process", fake_run)
    res = run_worker("some.module", {"a": 1}, python="/opt/lyricloom/venv/bin/python", cwd=Path(r"C:\Music\LyricLoom"),
                     wsl="Ubuntu", wsl_env={"HSA_ENABLE_DXG_DETECTION": "1"})
    argv = seen["argv"]
    assert res == {"ok": 1}
    assert argv[:7] == ["wsl.exe", "-d", "Ubuntu", "--cd", "/mnt/c/Music/LyricLoom", "--exec", "env"]
    assert "HSA_ENABLE_DXG_DETECTION=1" in argv and f"OMP_NUM_THREADS={config.CPU_THREADS}" in argv
    assert argv[-3:] == ["/opt/lyricloom/venv/bin/python", "-m", "some.module"]


def test_run_worker_frozen_never_relaunches_the_gui(monkeypatch, tmp_path):
    """A packaged build's sys.executable is the GUI: asking for "this interpreter" must start
    LyricLoomWorker.exe, or the CPU separation and the MTL fallback open a second window."""
    suffix = ".exe" if config.IS_WINDOWS else ""
    gui = tmp_path / f"LyricLoom{suffix}"
    worker = tmp_path / f"LyricLoomWorker{suffix}"
    gui.write_bytes(b"")
    worker.write_bytes(b"")
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, (RESULT_MARK + '{"ok": 1}\n').encode(), b"")

    monkeypatch.setattr(config, "IS_FROZEN", True)
    monkeypatch.setattr(sys, "executable", str(gui))
    monkeypatch.setattr("lyricloom.workers.run_process",
                        lambda argv, **kw: fake_run(argv, **kw))
    for python in (str(gui), None):
        assert run_worker("lyricloom.workers.separate", {}, python=python, cwd=tmp_path) == {"ok": 1}
        assert seen["argv"] == [str(worker), "separate"]
    # another interpreter (a dev venv) is still used as given
    run_worker("lyricloom.workers.separate", {}, python=str(tmp_path / "other-python"), cwd=tmp_path)
    assert seen["argv"] == [str(tmp_path / "other-python"), "-m", "lyricloom.workers.separate"]


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


@pytest.mark.skipif(sys.platform != "win32", reason="the WSL path bridge is Windows-only")
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


@pytest.mark.skipif(sys.platform != "win32", reason="the WSL path bridge is Windows-only")
def test_wsl_separation_prefers_the_model_copy_inside_the_distro(tmp_path, library, monkeypatch):
    calls = []
    monkeypatch.setattr(config, "SEPARATOR_WSL_ENABLED", True)
    monkeypatch.setattr(config, "WSL_MODELS_DIR", "/opt/lyricloom/models/separator")
    monkeypatch.setattr(sep_mod, "run_worker", _fake_worker(calls))
    audio = library / "Test Artist" / "Test Album" / "01 - Synthetic Song.flac"
    _wav(audio)
    sep_mod.separate(audio, tmp_path / "work")
    payload = calls[0]["payload"]
    assert payload["model_dir_candidates"][0] == "/opt/lyricloom/models/separator"
    assert payload["model_dir_candidates"][-1].startswith("/mnt/")
    assert payload["model_dir"] == payload["model_dir_candidates"][-1]
    spec = config.resolve_model("separate")
    assert payload["model_sizes"][spec.filename] == spec.size


@pytest.mark.skipif(sys.platform != "win32", reason="the WSL path bridge is Windows-only")
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
    digest = hashlib.sha1(str(outside.resolve()).encode("utf-8")).hexdigest()[:12]
    assert sep_mod.kept_vocals_path(outside) == \
        config.vocals_root() / "_external" / digest / "01 - Synthetic Song.vocals.flac"


def test_kept_vocals_paths_do_not_collide_outside_the_library(tmp_path, library):
    one = tmp_path / "Drive A" / "Artist" / "Album" / "01 - Song.flac"
    two = tmp_path / "Drive B" / "Artist" / "Album" / "01 - Song.flac"
    assert sep_mod.kept_vocals_path(one) != sep_mod.kept_vocals_path(two)


def test_unc_path_falls_back_to_the_local_separator(tmp_path, monkeypatch):
    calls = []

    def fake(module, payload, python=None, wsl=None, wsl_env=None, **kw):
        calls.append({"payload": payload, "wsl": wsl, "python": python})
        return {"vocals": str(tmp_path / "vocals.wav")}

    monkeypatch.setattr(config, "SEPARATOR_WSL_ENABLED", True)
    monkeypatch.setattr(sep_mod, "run_worker", fake)
    produced, device, fallback = sep_mod._run_separator(Path(r"\\server\share\Song.flac"), tmp_path)
    assert [c["wsl"] for c in calls] == [None]
    assert produced == tmp_path / "vocals.wav"
    assert "UNC" in fallback and "CPU" in fallback


def test_frozen_windows_without_worker_reports_a_damaged_install(monkeypatch, tmp_path):
    gui = tmp_path / "LyricLoom.exe"
    gui.write_bytes(b"")
    monkeypatch.setattr(config, "IS_FROZEN", True)
    monkeypatch.setattr(config, "IS_WINDOWS", True)
    monkeypatch.setattr(sys, "executable", str(gui))

    def no_run(*args, **kwargs):
        raise AssertionError("a missing worker must not start any process")

    monkeypatch.setattr("lyricloom.workers.subprocess.run", no_run)
    with pytest.raises(WorkerError) as error:
        run_worker("lyricloom.workers.separate", {}, cwd=tmp_path)
    message = str(error.value)
    assert "LyricLoomWorker.exe" in message and "damaged" in message and "reinstall" in message.lower()


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


def _legacy_kept_stem(tmp_path, library):
    """A stem as 2.0 left it: the FLAC exists, but there is no JSON manifest beside it."""
    audio = library / "A" / "B" / "01 - C.flac"
    _wav(audio)
    stem = tmp_path / "stem.wav"
    samples = _wav(stem, "PCM_24")
    kept = sep_mod.keep_vocals(audio, stem)
    sep_mod._manifest_path(kept).unlink()
    return audio, kept, samples


def test_legacy_kept_stem_is_reused_and_gets_a_manifest(tmp_path, library, monkeypatch):
    audio, kept, samples = _legacy_kept_stem(tmp_path, library)
    later = audio.stat().st_mtime + 5
    os.utime(kept, (later, later))

    def no_worker(*a, **kw):
        raise AssertionError("a current legacy stem must not be separated again")

    monkeypatch.setattr(sep_mod, "run_worker", no_worker)
    out = sep_mod.separate(audio, tmp_path / "work")
    assert out["device"] == "kept"
    assert np.array_equal(sf.read(out["vocals"], dtype="int32")[0], samples)
    manifest = sep_mod._manifest_path(kept)
    assert manifest.is_file()
    assert json.loads(manifest.read_text(encoding="utf-8"))["model"] == "separator-mel-band-roformer"


def test_legacy_kept_stem_older_than_the_audio_is_not_reused(tmp_path, library, monkeypatch):
    audio, kept, _ = _legacy_kept_stem(tmp_path, library)
    earlier = audio.stat().st_mtime - 5
    os.utime(kept, (earlier, earlier))
    calls = []
    monkeypatch.setattr(sep_mod, "run_worker", _fake_worker(calls))
    out = sep_mod.separate(audio, tmp_path / "work")
    assert calls and out["device"] != "kept"


def test_legacy_kept_stem_is_not_reused_for_a_non_default_separator(tmp_path, library, monkeypatch):
    audio, kept, _ = _legacy_kept_stem(tmp_path, library)
    later = audio.stat().st_mtime + 5
    os.utime(kept, (later, later))
    from lyricloom import models

    models.use("separate", "separator-bs-roformer-vocals")
    calls = []
    monkeypatch.setattr(sep_mod, "run_worker", _fake_worker(calls))
    out = sep_mod.separate(audio, tmp_path / "work")
    assert calls and out["device"] != "kept"


def test_stale_kept_stem_is_not_reused(tmp_path, library, monkeypatch):
    audio = library / "A" / "B" / "01 - C.flac"
    _wav(audio)
    stem = tmp_path / "stem.wav"
    _wav(stem)
    kept = sep_mod.keep_vocals(audio, stem)
    assert kept is not None and kept.exists()
    _wav(audio, seconds=2.0)                    # the user replaced the audio
    calls = []
    monkeypatch.setattr(sep_mod, "run_worker", _fake_worker(calls))
    out = sep_mod.separate(audio, tmp_path / "work")
    assert calls and out["device"] != "kept"
    assert any(p.name.endswith(".stale") for p in kept.parent.iterdir())


@pytest.mark.gpu
def test_separate_in_wsl_on_the_gpu(tmp_path, library, monkeypatch):
    monkeypatch.setattr(config, "SEPARATOR_WSL_ENABLED", True)
    audio = library / "A" / "B" / "01 - tone.wav"
    _wav(audio, seconds=10.0)
    out = sep_mod.separate(audio, tmp_path / "work")
    assert out["device"] == "rocm", out.get("fallback")
    assert abs(sf.info(out["vocals16k"]).duration - 10.0) < 0.05


def test_wsl_cpu_separation_is_reported_as_cpu_with_a_reason(tmp_path, monkeypatch):
    """R1-26: the worker's device must reach the result, not a hard-coded "rocm"."""
    monkeypatch.setattr(config, "SEPARATOR_WSL_ENABLED", True)

    def fake(module, payload, python=None, wsl=None, wsl_env=None, **kw):
        return {"vocals": str(tmp_path / "vocals.wav"), "device": "cpu"}

    monkeypatch.setattr(sep_mod, "run_worker", fake)
    _, device, fallback = sep_mod._run_separator(tmp_path / "song.flac", tmp_path)
    assert device == "cpu"
    assert fallback and "GPU" in fallback


def test_to_mono16k_decodes_m4a_through_ffmpeg(tmp_path):
    """R1-23: libsndfile cannot read M4A; ffmpeg is already a dependency."""
    import imageio_ffmpeg

    source = tmp_path / "source.wav"
    _wav(source)
    m4a = tmp_path / "source.m4a"
    proc = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-i", str(source),
                           "-c:a", "aac", "-b:a", "128k", str(m4a)], capture_output=True)
    if proc.returncode != 0:
        pytest.skip("this ffmpeg build cannot encode AAC")
    out = tmp_path / "out16k.wav"
    sep_mod.to_mono16k(m4a, out)
    info = sf.info(str(out))
    assert info.samplerate == 16000 and info.channels == 1


def test_to_mono16k_streams_instead_of_reading_the_whole_file(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    _wav(source)

    def no_full_read(*args, **kwargs):
        raise AssertionError("to_mono16k must stream, not sf.read the whole file")

    monkeypatch.setattr(sep_mod.sf, "read", no_full_read)
    out = tmp_path / "out16k.wav"
    sep_mod.to_mono16k(source, out)
    assert sf.info(str(out)).samplerate == 16000


def test_a_failed_instrumental_subtraction_does_not_fail_the_track(tmp_path, library, monkeypatch):
    """R1-24: optional work must never abort the track."""
    song = library / "A" / "Synthetic Song" / "01 - Synthetic Song.flac"
    _wav(song)
    inst = library / "A" / "Synthetic Song" / "04 - Synthetic Song (instrumental).flac"
    _wav(inst)

    def boom(*args, **kwargs):
        raise RuntimeError("subtraction is optional")

    calls = []
    monkeypatch.setattr(sep_mod, "find_instrumental", lambda audio: inst)
    monkeypatch.setattr(sep_mod, "subtract", boom)
    monkeypatch.setattr(sep_mod, "run_worker", _fake_worker(calls))
    out = sep_mod.separate(song, tmp_path / "work")
    assert out["instrumental"]["used"] is False
    assert "subtraction is optional" in out["instrumental"]["error"]
    assert Path(out["vocals"]).exists()


def test_a_failed_keep_vocals_does_not_fail_the_track(tmp_path, library, monkeypatch):
    song = library / "A" / "B" / "01 - C.flac"
    _wav(song)
    calls = []
    monkeypatch.setattr(sep_mod, "run_worker", _fake_worker(calls))

    def boom(*args, **kwargs):
        raise OSError("the vocals cache is read-only")

    monkeypatch.setattr(sep_mod, "keep_vocals", boom)
    out = sep_mod.separate(song, tmp_path / "work")
    assert Path(out["vocals"]).exists()
    assert "read-only" in out["kept_error"]

