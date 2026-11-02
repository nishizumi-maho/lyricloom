"""Vocals by subtracting the song's own instrumental (an "off vocal" / "instrumental" track of the
same release) from the mix. The two copies of the backing track rarely line up exactly: the
instrumental can start a few ms apart and drift by a few samples over the song (one of them was
resampled). So the instrumental is matched to the mix block by block with a short least-squares
filter (delay, gain, slight EQ), and what it cannot explain is the vocals."""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr
from numpy.lib.stride_tricks import sliding_window_view
from scipy.signal import fftconvolve

AUDIO_EXT = {".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav"}
# "Redo (instrumental)", "Redo (Off Vocal)", "Redo (Instrumental ver.)", "Redo -instrumental-",
# "Redo (inst.)", "Redo (Karaoke)": the title, then the marker in brackets or dashes at the end.
_MARK = re.compile(r"[\s_]*[(\[\-~]\s*(instrumental|off[\s-]?vocal|inst\.?|karaoke)(\s*ver(sion)?\.?)?"
                   r"\s*[)\]\-~]?\s*$", re.IGNORECASE)
_TRACK_NO = re.compile(r"^\d+\s*[-.]\s*")
MAX_LENGTH_DIFF_S = 3.0      # a different edit of the song is not its instrumental
SEARCH_S = 90                # the offset is found in the first 90 s
TAPS = 33                    # filter length: covers +-16 samples of drift inside a block
BLOCK_S = 2.0                # blocks short enough that the drift inside one is a fraction of a sample
FIT_STEP = 4                 # the filter is fitted on every 4th sample: as good, 4x faster
# The subtraction is used when the instrumental cancels for real: at least MIN_CLEAN_S seconds
# (intro, solos, outro) where what is left is CLEAN_DB below the mix. An unrelated or remastered
# instrumental never gets there; the matching one reaches ~-45 dB on Suzuki Konomi's "Redo".
CLEAN_DB = -25.0
MIN_CLEAN_S = 3.0
_SILENT_DB = -40.0


def _title(stem: str) -> str:
    return _TRACK_NO.sub("", stem).strip().casefold()


def _duration(path: Path) -> float | None:
    try:
        return sf.info(str(path)).duration
    except RuntimeError:      # a format libsndfile cannot read
        return None


def find_instrumental(audio: Path) -> Path | None:
    """The instrumental of `audio` in the same folder: same title plus an instrumental marker,
    and the same length. None for a song that is itself an instrumental."""
    if _MARK.search(_TRACK_NO.sub("", audio.stem)):
        return None
    title, length = _title(audio.stem), _duration(audio)
    if length is None:
        return None
    for p in sorted(audio.parent.iterdir()):
        if p == audio or p.suffix.lower() not in AUDIO_EXT:
            continue
        stem = _TRACK_NO.sub("", p.stem)
        m = _MARK.search(stem)
        if m and stem[:m.start()].strip().casefold() == title:
            d = _duration(p)
            if d is not None and abs(d - length) <= MAX_LENGTH_DIFF_S:
                return p
    return None


def _lag(mix: np.ndarray, inst: np.ndarray, sr: int) -> int:
    """How many samples later the instrumental's content appears in the mix."""
    a, b = mix[:SEARCH_S * sr].mean(axis=1), inst[:SEARCH_S * sr].mean(axis=1)
    xc = fftconvolve(a, b[::-1], mode="full")
    return int(np.argmax(xc)) - (len(b) - 1)


def _db(x: np.ndarray) -> float:
    return 10 * np.log10(float((x ** 2).mean()) + 1e-20)


def subtract(mix_path: Path, inst_path: Path, out_path: Path) -> dict:
    """Writes mix - instrumental (matched block by block) to `out_path`.
    Returns {ok, lag, clean_s}: whether it cancelled well enough to use, the offset in samples,
    and the seconds of near-perfect cancellation that decided it."""
    mix, sr = sf.read(str(mix_path), dtype="float64", always_2d=True)
    inst, isr = sf.read(str(inst_path), dtype="float64", always_2d=True)
    if isr != sr:
        inst = soxr.resample(inst, isr, sr)
    if inst.shape[1] != mix.shape[1]:
        inst = np.repeat(inst.mean(axis=1, keepdims=True), mix.shape[1], axis=1)
    lag = _lag(mix, inst, sr)
    half = TAPS // 2
    # Shift so that the centre tap sees the instrumental sample aligned with each mix sample.
    front = lag + half
    shifted = np.vstack([np.zeros((front, inst.shape[1])), inst]) if front >= 0 else inst[-front:]
    n = len(mix)
    block = int(BLOCK_S * sr)
    shifted = np.vstack([shifted, np.zeros((max(0, n + block + TAPS - len(shifted)), inst.shape[1]))])

    est = np.zeros_like(mix)
    weight = np.zeros(n)
    window = np.hanning(block)
    for a in range(0, n, block // 2):
        b = min(a + block, n)
        w = window[:b - a]
        for c in range(mix.shape[1]):
            taps = sliding_window_view(shifted[a:b + TAPS - 1, c], TAPS)[:, ::-1]
            h = np.linalg.lstsq(taps[::FIT_STEP], mix[a:b:FIT_STEP, c], rcond=None)[0]
            est[a:b, c] += w * (taps @ h)
        weight[a:b] += w
    rest = mix - est / np.maximum(weight, 1e-9)[:, None]

    clean = sum(1 for i in range(0, n - sr, sr)
                if _db(mix[i:i + sr]) > _SILENT_DB and _db(rest[i:i + sr]) - _db(mix[i:i + sr]) <= CLEAN_DB)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), rest.astype(np.float32), sr, subtype="PCM_24")
    return {"ok": clean >= MIN_CLEAN_S, "lag": lag, "clean_s": float(clean)}
