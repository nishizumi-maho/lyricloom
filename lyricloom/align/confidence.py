from __future__ import annotations

from ..model import Line

REVIEW_THRESHOLD = 0.6


def line_conf(ctc_scores: list[float], anchor_score: float | None) -> float:
    if not ctc_scores:
        return 0.0
    mean = sum(ctc_scores) / len(ctc_scores)
    return 0.6 * mean + 0.4 * (anchor_score if anchor_score is not None else mean)


def _duration(line: Line) -> int:
    timed = [s for s in line.segments if s.start_ms is not None and s.end_ms is not None]
    return max(1, timed[-1].end_ms - timed[0].start_ms) if timed else 1


def track_conf(lines: list[Line]) -> float:
    if not lines:
        return 0.0
    total = sum(_duration(l) for l in lines)
    return sum(l.conf * _duration(l) for l in lines) / total
