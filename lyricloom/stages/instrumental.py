"""Vocals by subtracting the song's own instrumental (an "off vocal" / "instrumental" track of the
same release) from the mix. The two copies of the backing track rarely line up exactly: the
instrumental can start a few ms apart and drift by a few samples over the song (one of them was
resampled). So the instrumental is matched to the mix block by block with a short least-squares
filter (delay, gain, slight EQ), and what it cannot explain is the vocals.

Everything is streamed in chunks with float32 samples (R1-27): a one-hour stereo track costs a few
tens of megabytes, not several gigabytes."""
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
CHUNK_S = 60.0               # output chunk; keeps peak memory bounded on long tracks
# The subtraction is used when the instrumental cancels for real: at least MIN_CLEAN_S seconds
# (intro, solos, outro) where what is left is CLEAN_DB below the mix. An unrelated or remastered
# instrumental never gets there; a matching instrumental reaches about -45 dB on a clean studio mix.
CLEAN_DB = -25.0
MIN_CLEAN_S = 3.0
_SILENT_DB = -40.0
_READ_BLOCK = 1 << 18


def _title(stem: str) -> str:
    return _TRACK_NO.sub("", stem).strip().casefold()


def _duration(path: Path) -> float | None:
    """Seconds from libsndfile, or mutagen for a container it cannot read (M4A and others)."""
    try:
        return sf.info(str(path)).duration
    except (RuntimeError, OSError):      # a format libsndfile cannot read
        pass
    try:
        import mutagen

        f = mutagen.File(str(path))
        return float(f.info.length) if f is not None and f.info is not None else None
    except Exception:  # noqa: BLE001 - an unreadable file is simply not an instrumental candidate
        return None


def find_instrumental(audio: Path) -> Path | None:
    """The instrumental of `audio` in the same folder: same title plus an instrumental marker,
    and the same length. None for a song that is itself an instrumental."""
    if _MARK.search(_TRACK_NO.sub("", audio.stem)):
        return None
    title, length = _title(audio.stem), _duration(audio)
    if length is None:
        return None
    try:
        candidates = sorted(audio.parent.iterdir())
    except OSError:
        return None
    for p in candidates:
        if p == audio or p.suffix.lower() not in AUDIO_EXT:
            continue
        try:
            stem = _TRACK_NO.sub("", p.stem)
            m = _MARK.search(stem)
            if m and stem[:m.start()].strip().casefold() == title:
                d = _duration(p)
                if d is not None and abs(d - length) <= MAX_LENGTH_DIFF_S:
                    return p
        except OSError:
            continue
    return None


def _read_mono(path: Path, seconds: float) -> tuple[np.ndarray, int]:
    with sf.SoundFile(str(path)) as f:
        n = min(f.frames, max(1, int(seconds * f.samplerate)))
        data = f.read(n, dtype="float32", always_2d=True)
        return data.mean(axis=1), f.samplerate


def _lag(mix: np.ndarray, inst: np.ndarray, sr: int) -> int:
    """How many samples later the instrumental's content appears in the mix."""
    a, b = mix[:SEARCH_S * sr], inst[:SEARCH_S * sr]
    xc = fftconvolve(a, b[::-1], mode="full")
    return int(np.argmax(xc)) - (len(b) - 1)


def _db(x: np.ndarray) -> float:
    return 10 * np.log10(float((x ** 2).mean()) + 1e-20)


def _channels(block: np.ndarray, channels: int) -> np.ndarray:
    """Makes a read block match the mix channel count without loading the whole file."""
    if block.shape[1] == channels:
        return block
    if block.shape[1] == 1:
        return np.repeat(block, channels, axis=1)
    if channels == 1:
        return block.mean(axis=1, keepdims=True)
    return block[:, :channels]


def _resample_file(src: Path, dst: Path, sr: int) -> None:
    """Resamples a whole file to an on-disk WAV, one block at a time, in float32."""
    with sf.SoundFile(str(src)) as f:
        resampler = soxr.ResampleStream(f.samplerate, sr, f.channels, dtype="float32")
        with sf.SoundFile(str(dst), "w", samplerate=sr, channels=f.channels,
                          subtype="FLOAT", format="WAV") as out:
            for block in f.blocks(blocksize=_READ_BLOCK, dtype="float32", always_2d=True):
                out.write(resampler.resample_chunk(block))
            out.write(resampler.resample_chunk(np.empty((0, f.channels), dtype="float32"), last=True))


def _read_inst_range(f: sf.SoundFile, start: int, count: int, channels: int) -> np.ndarray:
    """Reads ``count`` samples starting at ``start`` (negative/overrun regions are zeros)."""
    out = np.zeros((count, channels), dtype="float32")
    if count <= 0:
        return out
    skip = max(0, -start)
    read_start = max(0, start)
    read_count = count - skip
    if read_count <= 0:
        return out
    f.seek(read_start)
    data = f.read(read_count, dtype="float32", always_2d=True)
    data = _channels(data, channels)
    out[skip: skip + len(data)] = data
    return out


def subtract(mix_path: Path, inst_path: Path, out_path: Path) -> dict:
    """Writes mix - instrumental (matched block by block) to `out_path`.

    Streaming, float32 implementation (R1-27).  Returns {ok, lag, clean_s}: whether it cancelled
    well enough to use, the offset in samples, and the seconds of near-perfect cancellation that
    decided it."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mix_head, sr = _read_mono(mix_path, SEARCH_S)
    inst_head, isr = _read_mono(inst_path, SEARCH_S)
    if isr != sr:
        inst_head = soxr.resample(inst_head, isr, sr).astype(np.float32)
    lag = _lag(mix_head, inst_head, sr)

    temp: Path | None = None
    inst_file = inst_path
    if isr != sr:
        temp = out_path.with_name(out_path.stem + ".inst" + out_path.suffix)
        _resample_file(inst_path, temp, sr)
        inst_file = temp
    half = TAPS // 2
    front = lag + half          # shifted index k corresponds to inst index k - front
    block = int(BLOCK_S * sr)
    chunk = max(block, int(CHUNK_S * sr))
    window = np.hanning(block)
    clean = 0
    try:
        with sf.SoundFile(str(mix_path)) as mix, sf.SoundFile(str(inst_file)) as inst, \
                sf.SoundFile(str(out_path), "w", samplerate=sr, channels=mix.channels,
                             subtype="PCM_24") as out:
            for core_start in range(0, mix.frames, chunk):
                core_end = min(mix.frames, core_start + chunk)
                a, b = max(0, core_start - block), min(mix.frames, core_end + block)
                mix.seek(a)
                data = mix.read(b - a, dtype="float32", always_2d=True)
                if len(data) < b - a:
                    data = np.vstack([data, np.zeros((b - a - len(data), mix.channels), dtype="float32")])
                shifted = _read_inst_range(inst, a - front, (b - a) + TAPS - 1, mix.channels)

                est = np.zeros_like(data)
                weight = np.zeros(b - a, dtype="float32")
                for w0 in range(0, b - a, block // 2):
                    wb = min(w0 + block, b - a)
                    w = window[:wb - w0]
                    for c in range(mix.channels):
                        taps = sliding_window_view(shifted[w0:wb + TAPS - 1, c], TAPS)[:, ::-1]
                        h = np.linalg.lstsq(taps[::FIT_STEP], data[w0:wb:FIT_STEP, c], rcond=None)[0]
                        est[w0:wb, c] += w * (taps @ h)
                    weight[w0:wb] += w
                rest = data - est / np.maximum(weight, 1e-9)[:, None]
                s0, s1 = core_start - a, core_end - a
                out.write(rest[s0:s1].astype(np.float32))

                first_second = ((core_start + sr - 1) // sr) * sr
                for i in range(first_second, core_end - sr + 1, sr):
                    k0, k1 = i - a, i - a + sr
                    before, after = _db(data[k0:k1]), _db(rest[k0:k1])
                    if before > _SILENT_DB and after - before <= CLEAN_DB:
                        clean += 1
    finally:
        if temp is not None:
            try:
                temp.unlink()
            except OSError:
                pass
    return {"ok": clean >= MIN_CLEAN_S, "lag": lag, "clean_s": float(clean)}
