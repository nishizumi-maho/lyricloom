"""Final cleanup: strictly increasing starts, no overlaps, nothing past the end of the track, and
lines that could not be aligned word by word fall back to a line timestamp only."""
from __future__ import annotations

from ..model import Line, Segment

MIN_STEP_MS = 10


def refine(lines: list[Line], total_ms: int) -> list[Line]:
    timed = [s for l in lines for s in l.segments if s.start_ms is not None]
    prev = None
    for s in timed:
        if prev is not None and s.start_ms <= prev.start_ms:
            s.start_ms = prev.start_ms + MIN_STEP_MS
        prev = s
    for s, nxt in zip(timed, timed[1:] + [None]):
        end = s.end_ms if s.end_ms is not None else s.start_ms + MIN_STEP_MS
        if nxt is not None:
            end = min(end, nxt.start_ms)
        s.start_ms = min(s.start_ms, total_ms)
        s.end_ms = max(min(end, total_ms), s.start_ms)

    out: list[Line] = []
    for i, l in enumerate(lines):
        segs = [s for s in l.segments if s.start_ms is not None]
        if segs and len(segs) == len(l.segments):
            out.append(Line(segs[0].start_ms, l.segments, l.conf))
            continue
        # Unaligned (or partly aligned) line: keep the text with a line timestamp only.
        start = l.start_ms
        if start is None:
            before = next((s.end_ms for p in reversed(out) for s in reversed(p.segments) if s.end_ms is not None), None)
            if before is None:
                before = next((p.start_ms for p in reversed(out) if p.start_ms is not None), 0)
            start = before
        out.append(Line(start, [Segment(l.text, None, None)], l.conf))
    return out
