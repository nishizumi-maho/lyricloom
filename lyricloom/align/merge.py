"""Uses a source's ready-made word timing (e.g. NetEase yrc) where it agrees with the audio.

The two may segment a line differently, so they are compared by character position: the
presync time at a character offset is interpolated inside the presync segment that holds it.
Our segmentation is kept (finer karaoke steps), with presync times when the line agrees."""
from __future__ import annotations

import re

from ..model import Line, Segment

_NOISE = re.compile(r"[\s\W_]+", re.UNICODE)


def _norm(text: str) -> str:
    return _NOISE.sub("", text).lower()


def _time_at(line: Line, offset: int, at_end: bool = False) -> float | None:
    pos = 0
    for s in line.segments:
        n = len(s.text)
        if s.start_ms is not None and s.end_ms is not None and (pos <= offset < pos + n or (at_end and offset == pos + n)):
            return s.start_ms + (s.end_ms - s.start_ms) * (offset - pos) / max(n, 1)
        pos += n
    return None


def _word_timed(line: Line) -> bool:
    return any(s.start_ms is not None and s.end_ms is not None for s in line.segments)


def merge_presync(ours: list[Line], presync: list[Line], max_mean_diff_ms: int = 150) -> list[Line]:
    out = []
    for line in ours:
        key = _norm(line.text)
        same = [p for p in presync if _norm(p.text) == key and p.start_ms is not None]
        if not key or not same:
            out.append(line)
            continue
        pre = min(same, key=lambda p: abs(p.start_ms - (line.start_ms or 0)))
        if not _word_timed(pre):
            # A plain LRC source has line timing only.  Use it where it agrees with our line
            # start; word starts stay as CTC/MTL heard them (R1-13).
            if line.start_ms is not None and abs(pre.start_ms - line.start_ms) <= max_mean_diff_ms:
                out.append(Line(pre.start_ms, line.segments, max(line.conf, 0.9)))
            else:
                out.append(line)
            continue
        if line.start_ms is None:
            out.append(line)
            continue
        diffs, retimed, pos = [], [], 0
        for s in line.segments:
            a, b = _time_at(pre, pos), _time_at(pre, pos + len(s.text), at_end=True)
            if s.start_ms is not None and a is not None:
                diffs.append(abs(s.start_ms - a))
            retimed.append(Segment(s.text, None if a is None else int(a), None if b is None else int(b), s.conf))
            pos += len(s.text)
        if diffs and sum(diffs) / len(diffs) <= max_mean_diff_ms and all(r.start_ms is not None for r in retimed):
            out.append(Line(retimed[0].start_ms, retimed, max(line.conf, 0.9)))
        else:
            out.append(line)
    return out
