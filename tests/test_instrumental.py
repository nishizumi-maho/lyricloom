from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import soxr

from lyricloom import config
from lyricloom.stages import instrumental
from lyricloom.stages import separate as sep_mod
from lyricloom.workers import windows_path, wsl_path

SR = 44100


def _write(path: Path, data: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), data.astype("float32"), SR, subtype="PCM_24")
    return path


def _music(seconds: float, seed: int = 0) -> np.ndarray:
    """Band-limited stereo noise with a beat: enough structure for the alignment to lock on."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    x = np.convolve(rng.standard_normal(n + 64), np.hanning(64) / 32, mode="valid")[:n]
    env = 0.5 + 0.5 * (np.sin(2 * np.pi * 2 * np.arange(n) / SR) > 0)
    return np.stack([x * env, 0.8 * x * env], axis=1) * 0.2


def _delay(x: np.ndarray, samples: float) -> np.ndarray:
    """Fractional delay through the FFT (circular; the test signals start and end quiet enough)."""
    n = len(x)
    f = np.fft.rfftfreq(n)
    return np.fft.irfft(np.fft.rfft(x, axis=0) * np.exp(-2j * np.pi * f * samples)[:, None], n, axis=0)


def _vocals(seconds: float) -> np.ndarray:
    n = int(SR * seconds)
    t = np.arange(n) / SR
    v = 0.15 * np.sin(2 * np.pi * 330 * t) * np.sin(2 * np.pi * 0.5 * t) ** 2
    v[: int(SR * 6)] = 0      # instrumental-only intro, as in most songs
    return np.stack([v, v], axis=1)


@pytest.mark.parametrize("name", ["04 - Synthetic Song (instrumental).flac", "05 - Synthetic Song (Off Vocal).flac",
                                  "06 - Synthetic Song (Instrumental ver.).flac", "07 - Synthetic Song -instrumental-.flac",
                                  "08 - Synthetic Song (inst.).flac", "09 - Synthetic Song (Karaoke).flac"])
def test_find_instrumental_by_name(tmp_path, name):
    song = _write(tmp_path / "01 - Synthetic Song.flac", np.zeros((SR, 2)))
    _write(tmp_path / "02 - Another Test Song.flac", np.zeros((SR, 2)))
    inst = _write(tmp_path / name, np.zeros((SR, 2)))
    assert instrumental.find_instrumental(song) == inst
    assert instrumental.find_instrumental(inst) is None          # an instrumental has no pair


def test_find_instrumental_needs_a_matching_length(tmp_path):
    song = _write(tmp_path / "01 - Synthetic Song.flac", np.zeros((SR * 10, 2)))
    _write(tmp_path / "04 - Synthetic Song (instrumental).flac", np.zeros((SR * 30, 2)))
    assert instrumental.find_instrumental(song) is None


def test_subtract_recovers_vocals_despite_offset_gain_and_drift(tmp_path):
    secs = 20
    inst = _music(secs)
    inst[-SR // 10:] = 0                  # quiet end: the FFT delay wraps it to the start
    vocals = _vocals(secs)
    # The mix's copy of the instrumental sits 1234.4 samples later, 0.9x as loud, and drifts by
    # about a sample over the song (as when one of the two went through a resampler).
    drifted = soxr.resample(inst, SR, SR * (1 + 1e-6))
    drifted = np.vstack([drifted, np.zeros((len(inst), 2))])[:len(inst)]
    shifted = _delay(drifted, 1234.4)
    mix = _write(tmp_path / "mix.wav", 0.9 * shifted + vocals)
    ins = _write(tmp_path / "inst.wav", inst)
    stats = instrumental.subtract(mix, ins, tmp_path / "out.wav")
    out = sf.read(str(tmp_path / "out.wav"), dtype="float64", always_2d=True)[0]
    core = slice(SR, len(vocals) - SR)     # block edges of the synthetic delay aside
    sdr = 10 * np.log10((vocals[core] ** 2).sum() / ((out[core] - vocals[core]) ** 2).sum())
    assert stats["ok"] and abs(stats["lag"] - 1234) <= 2
    assert sdr > 20, sdr


def test_subtract_rejects_an_unrelated_instrumental(tmp_path):
    mix = _write(tmp_path / "mix.wav", _music(20, seed=1) + _vocals(20))
    ins = _write(tmp_path / "inst.wav", _music(20, seed=2))
    assert not instrumental.subtract(mix, ins, tmp_path / "out.wav")["ok"]


def test_separate_feeds_the_subtraction_to_the_separator(tmp_path, monkeypatch):
    library = tmp_path / "Library"
    monkeypatch.setattr(config, "LIBRARY_ROOT", library)
    monkeypatch.setattr(config, "SEPARATOR_WSL_ENABLED", True)
    song = _write(library / "A" / "Synthetic Song" / "01 - Synthetic Song.flac", np.zeros((SR, 2)))
    _write(library / "A" / "Synthetic Song" / "04 - Synthetic Song (instrumental).flac", np.zeros((SR, 2)))
    monkeypatch.setattr(sep_mod, "subtract", lambda mix, inst, out: (
        _write(out, np.full((SR, 2), 0.1)), {"ok": True, "lag": 7, "clean_s": 4.0})[1])
    calls = []

    def fake_worker(module, payload, wsl=None, **kw):
        calls.append(payload)
        raw = windows_path(payload["out_dir"]) / "vocals_raw.wav"
        raw.write_bytes(windows_path(payload["audio"]).read_bytes())
        return {"vocals": wsl_path(raw)}

    monkeypatch.setattr(sep_mod, "run_worker", fake_worker)
    out = sep_mod.separate(song, tmp_path / "work")
    assert calls[0]["audio"].endswith("/minus_instrumental.wav")
    assert out["instrumental"]["path"].endswith("04 - Synthetic Song (instrumental).flac")
    assert out["instrumental"]["used"] is True


def test_separate_ignores_a_subtraction_that_did_not_cancel(tmp_path, monkeypatch):
    library = tmp_path / "Library"
    monkeypatch.setattr(config, "LIBRARY_ROOT", library)
    song = _write(library / "A" / "Synthetic Song" / "01 - Synthetic Song.flac", np.zeros((SR, 2)))
    _write(library / "A" / "Synthetic Song" / "04 - Synthetic Song (instrumental).flac", np.zeros((SR, 2)))
    monkeypatch.setattr(sep_mod, "subtract", lambda mix, inst, out: {"ok": False, "lag": 0, "clean_s": 0.0})
    calls = []

    def fake_worker(module, payload, **kw):
        calls.append(payload)
        raw = Path(payload["out_dir"]) / "vocals_raw.wav"
        raw.write_bytes(Path(payload["audio"]).read_bytes())
        return {"vocals": str(raw)}

    monkeypatch.setattr(sep_mod, "run_worker", fake_worker)
    out = sep_mod.separate(song, tmp_path / "work")
    assert calls[0]["audio"] == str(song) and out["instrumental"]["used"] is False
