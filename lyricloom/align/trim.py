"""Ends each line's last word where the isolated vocals actually go quiet.

The aligners place word starts well, but the end of a line's last word tends to run on into the
silence that follows: up to the next block of singing, so through a whole instrumental. Players then
keep filling that word until the next line. Here the end is moved back to where the voice stops."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from ..model import Line

FRAME_MS = 20
QUIET_FOR_MS = 300      # this long below the threshold means the word is over
MIN_WORD_MS = 150       # a word never ends sooner than this after it starts
QUIET_DB = -16          # below the line's voiced level (median of its loud frames) by this much


def _envelope(vocals16k: Path) -> np.ndarray:
    """RMS level in dB per FRAME_MS frame."""
    data, sr = sf.read(str(vocals16k), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    n = int(sr * FRAME_MS / 1000)
    frames = len(mono) // n
    if frames == 0:
        return np.zeros(0)
    rms = np.sqrt(np.mean(mono[: frames * n].reshape(frames, n) ** 2, axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-6))


def trim_line_ends(lines: list[Line], vocals16k: Path) -> list[Line]:
    """Lines are left as they are when the vocals cannot be read."""
    try:
        db = _envelope(vocals16k)
    except (sf.LibsndfileError, OSError, RuntimeError):
        return lines
    if len(db) == 0:
        return lines
    quiet_frames = QUIET_FOR_MS // FRAME_MS
    for line in lines:
        timed = [s for s in line.segments if s.start_ms is not None and s.end_ms is not None]
        if not timed:
            continue
        last = timed[-1]
        a, b = timed[0].start_ms // FRAME_MS, min(len(db), last.end_ms // FRAME_MS)
        if b - a < 3:
            continue
        line_db = db[a:b]
        voiced = np.median(np.sort(line_db)[len(line_db) // 2:])   # level of the louder half of the line
        threshold = voiced + QUIET_DB
        start = (last.start_ms + MIN_WORD_MS) // FRAME_MS
        run = 0
        for f in range(start, b):
            run = run + 1 if db[f] < threshold else 0
            if run >= quiet_frames:
                last.end_ms = max(last.start_ms + MIN_WORD_MS, (f - quiet_frames + 1) * FRAME_MS)
                break
    return lines
