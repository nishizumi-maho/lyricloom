"""Enhanced LRC: `[mm:ss.xx]` per line, `<mm:ss.xx>` before each segment, and a final
`<mm:ss.xx>` with no text marking where the last segment ends. Text between marks is kept
verbatim (no separators are inserted), so Japanese stays unspaced and Latin text carries its
own spaces."""
from __future__ import annotations

import re

from .model import Line, LrcDoc, Segment

_LINE_TS = re.compile(r"^\[(\d+):(\d{2})(?:[.:](\d{1,3}))?\]")
_META = re.compile(r"^\[(#?[A-Za-z]+):(.*)\]$")
_WORD = re.compile(r"<(\d+):(\d{2})(?:[.:](\d{1,3}))?>")


def _to_ms(mins: str, secs: str, frac: str | None) -> int:
    ms = int(mins) * 60000 + int(secs) * 1000
    if frac:
        ms += int(frac.ljust(3, "0")[:3])
    return ms


def format_ts(ms: int) -> str:
    cs = int(round(ms / 10))
    return f"{cs // 6000:02d}:{(cs // 100) % 60:02d}.{cs % 100:02d}"


def _parse_segments(body: str) -> list[Segment] | None:
    marks = list(_WORD.finditer(body))
    if not marks:
        return None
    segments: list[Segment] = []
    for i, m in enumerate(marks):
        text = body[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(body)]
        start = _to_ms(m.group(1), m.group(2), m.group(3))
        if segments:
            segments[-1].end_ms = start
        if text:
            segments.append(Segment(text, start, None))
    return segments


def parse_lrc(text: str) -> LrcDoc:
    doc = LrcDoc()
    for raw in text.lstrip("﻿").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        ts = _LINE_TS.match(raw)
        if ts:
            body = raw[ts.end():]
            start = _to_ms(ts.group(1), ts.group(2), ts.group(3))
            segments = _parse_segments(body)
            if segments is None:
                segments = [Segment(body, None, None)]
            doc.lines.append(Line(start, segments))
            continue
        meta = _META.match(raw)
        if meta:
            doc.meta[meta.group(1)] = meta.group(2)
    return doc


def _format_line(line: Line) -> str:
    head = f"[{format_ts(line.start_ms or 0)}]"
    timed = [s for s in line.segments if s.start_ms is not None]
    if not timed:
        return head + line.text
    out = [head]
    for s in line.segments:
        if s.start_ms is not None:
            out.append(f"<{format_ts(s.start_ms)}>")
        out.append(s.text)
    last_end = timed[-1].end_ms
    if last_end is not None:
        out.append(f"<{format_ts(last_end)}>")
    return "".join(out)


def format_lrc(doc: LrcDoc) -> str:
    rows = [f"[{k}:{v}]" for k, v in doc.meta.items()]
    rows += [_format_line(l) for l in doc.lines]
    return "".join(r + "\n" for r in rows)
