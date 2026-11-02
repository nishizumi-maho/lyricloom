"""What the app shows about each track, and the one edit operation it needs. No Qt here."""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import mutagen

from .. import config
from ..align.refine import refine
from ..brand import is_ours
from ..lrc import parse_lrc
from ..model import Line, LrcDoc, Segment
from ..runner import find_audio
from ..text import split_line


@dataclass
class TrackRow:
    path: Path
    artist: str
    title: str
    status: str            # pending | done | review | other | failed | processing
    source: str = ""
    conf: float = 0.0
    review_lines: list[int] = field(default_factory=list)
    error: str = ""


def _flac_tags(audio: Path) -> tuple[str, str] | None:
    """Reads only the Vorbis comment block of a FLAC file.

    Mutagen loads every metadata block, including embedded cover art. A library with a few very
    large scans then spends minutes in the first scan. The Vorbis comment is a small block near the
    start, so this reads it directly and skips the rest. Returns None when the layout is unusual;
    the caller then falls back to mutagen.
    """
    try:
        with audio.open("rb") as f:
            if f.read(4) != b"fLaC":
                return None
            while True:
                header = f.read(4)
                if len(header) != 4:
                    return None
                last, block_type = header[0] & 0x80, header[0] & 0x7F
                size = int.from_bytes(header[1:4], "big")
                if block_type == 4:  # VORBIS_COMMENT
                    data = f.read(size)
                    vendor_len = struct.unpack_from("<I", data, 0)[0]
                    pos = 4 + vendor_len
                    count = struct.unpack_from("<I", data, pos)[0]
                    pos += 4
                    values = {}
                    for _ in range(count):
                        length = struct.unpack_from("<I", data, pos)[0]
                        pos += 4
                        item = data[pos:pos + length].decode("utf-8", "replace")
                        pos += length
                        key, sep, value = item.partition("=")
                        if sep and key.upper() not in values:
                            values[key.upper()] = value.strip()
                    return values.get("ARTIST", ""), values.get("TITLE", "")
                if last:
                    return None
                f.seek(size, 1)
    except (OSError, struct.error, IndexError):
        return None


def _tags(audio: Path) -> tuple[str, str]:
    """(artist, title) from the file's tags; empty strings when unreadable.

    Very large files are skipped: their embedded art can be bigger than the audio and is not worth
    reading just to fill two columns. The folder and file names are used instead.
    """
    try:
        if audio.stat().st_size > 250_000_000:
            return "", ""
        if audio.suffix.lower() == ".flac":
            fast = _flac_tags(audio)
            if fast is not None:
                return fast
    except OSError:
        return "", ""
    try:
        f = mutagen.File(str(audio), easy=True)
        tags = f.tags if f is not None else None
        get = lambda k: str(tags[k][0]).strip() if tags and k in tags and tags[k] else ""
        return get("artist"), get("title")
    except Exception:  # noqa: BLE001 - a broken file still gets listed
        return "", ""


def read_status(audio: Path) -> TrackRow:
    tag_artist, tag_title = _tags(audio)
    folder = audio.parent.parent.name if audio.parent.parent != audio.parent else ""
    row = TrackRow(audio, tag_artist or folder, tag_title or audio.stem, "pending")
    lrc = audio.with_suffix(".lrc")
    if not lrc.exists():
        return row
    meta = parse_lrc(lrc.read_text(encoding="utf-8", errors="replace")).meta
    if not is_ours(meta.get("re")):
        row.status = "other"
        return row
    source, _, conf = meta.get("#source", "").partition(" conf:")
    row.source = source
    row.conf = float(conf) if conf else 0.0
    row.review_lines = [int(x) for x in meta.get("#review", "").split(",") if x.strip().isdigit()]
    row.status = "review" if row.review_lines or source == "transcription" else "done"
    return row


def scan(root: Path) -> list[TrackRow]:
    return [read_status(p) for p in find_audio(root)]


# ---- scan cache: one JSON per library; a track is re-read only when its audio or .lrc changed ----

def _cache_file(root: Path) -> Path:
    key = hashlib.sha1(str(Path(root).resolve()).lower().encode("utf-8")).hexdigest()[:12]
    return config.WORK_ROOT.parent / f"scan-{key}.json"


def _stamp(audio: Path) -> list:
    lrc = audio.with_suffix(".lrc")
    return [audio.stat().st_mtime_ns, lrc.stat().st_mtime_ns if lrc.exists() else 0]


def _row_to_json(row: TrackRow, stamp: list) -> dict:
    d = asdict(row)
    d["path"] = str(row.path)
    d["stamp"] = stamp
    return d


def _row_from_json(d: dict) -> TrackRow:
    d = dict(d)
    d.pop("stamp", None)
    d["path"] = Path(d["path"])
    return TrackRow(**d)


def load_cached_rows(root: Path) -> list[TrackRow]:
    """Rows from the last scan of this library, without touching the files (instant on startup)."""
    try:
        data = json.loads(_cache_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [_row_from_json(d) for d in data.values()]


def scan_cached(root: Path) -> list[TrackRow]:
    """Full listing, re-reading only tracks whose audio or .lrc changed since the last scan."""
    try:
        old = json.loads(_cache_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    new, rows = {}, []
    for audio in find_audio(root):
        try:
            stamp = _stamp(audio)
        except OSError:
            continue
        cached = old.get(str(audio))
        row = _row_from_json(cached) if cached and cached.get("stamp") == stamp else read_status(audio)
        new[str(audio)] = _row_to_json(row, stamp)
        rows.append(row)
    path = _cache_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")
    return rows


def delete_line(doc: LrcDoc, index: int) -> LrcDoc:
    """Removes one line; review markers after it move up by one."""
    meta = dict(doc.meta)
    review = [int(x) for x in meta.pop("#review", "").split(",") if x.strip().isdigit()]
    review = [i - 1 if i > index else i for i in review if i != index]
    if review:
        meta["#review"] = ",".join(map(str, review))
    return LrcDoc(meta, [l for i, l in enumerate(doc.lines) if i != index])


_CJK = re.compile(r"[぀-ヿ一-鿿]")

# ---- progress estimate: the engine reports stage changes only, so time drives the bar inside a stage ----
# (stage, share of the bar, expected seconds = a + b * track seconds). Separation dominates: ~3.5x the
# track length on 6 CPU threads. Cached stages finish at once and the bar jumps to the next one.
STAGES = [("lyrics", 0.04, 5, 0.0), ("separate", 0.66, 10, 3.5), ("transcribe", 0.20, 10, 0.6),
          ("align", 0.08, 5, 0.15), ("write", 0.02, 1, 0.0)]
STAGE_LABELS = {"lyrics": "searching lyrics", "separate": "separating vocals", "transcribe": "transcribing",
                "align": "aligning", "write": "writing .lrc"}


def track_progress(stage: str, elapsed_s: float, duration_s: float) -> float:
    """Fraction of one track done (0..1, never reaching 1 before the track ends)."""
    start = 0.0
    for name, share, a, b in STAGES:
        if name == stage:
            expected = a + b * max(duration_s, 1)
            inside = min(0.995, 1 - math.exp(-1.2 * max(elapsed_s, 0) / expected))   # keeps moving, never hits 1
            return start + share * inside
        start += share
    return start


def _review(meta: dict) -> list[int]:
    return [int(x) for x in meta.get("#review", "").split(",") if x.strip().isdigit()]


def _with_review(meta: dict, review: list[int]) -> dict:
    meta = {k: v for k, v in meta.items() if k != "#review"}
    if review:
        meta["#review"] = ",".join(map(str, sorted(review)))
    return meta


def insert_word(doc: LrcDoc, line: int, after: int, text: str, total_ms: int) -> LrcDoc:
    """Adds a word after segment `after` (-1 = at the start of the line). It takes the second half of
    the word before it (the first half of the first word), ready to be adjusted by hand."""
    segs = [replace(s) for s in doc.lines[line].segments]
    cjk = bool(_CJK.search(doc.lines[line].text + text))
    word = Segment(text.strip(), None, None)
    neighbour = segs[after] if after >= 0 else (segs[0] if segs else None)
    if neighbour is not None and neighbour.start_ms is not None and neighbour.end_ms is not None:
        mid = (neighbour.start_ms + neighbour.end_ms) // 2
        if after >= 0:
            word.start_ms, word.end_ms, neighbour.end_ms = mid, neighbour.end_ms, mid
        else:
            word.start_ms, word.end_ms, neighbour.start_ms = neighbour.start_ms, mid, mid
    else:
        start = doc.lines[line].start_ms or 0
        word.start_ms, word.end_ms = start, start + 300
    segs.insert(after + 1, word)
    if not cjk:   # Latin text: every word but the last carries its following space
        for i, s in enumerate(segs):
            s.text = s.text.rstrip() + (" " if i < len(segs) - 1 else "")
    return apply_edits(doc, line, segs, total_ms)


def delete_word(doc: LrcDoc, line: int, index: int) -> LrcDoc:
    """Removes one word; a line left without words is removed too."""
    segs = [replace(s) for i, s in enumerate(doc.lines[line].segments) if i != index]
    if not segs:
        return delete_line(doc, line)
    segs[-1].text = segs[-1].text.rstrip()
    lines = list(doc.lines)
    lines[line] = Line(segs[0].start_ms, segs, doc.lines[line].conf)
    return LrcDoc(dict(doc.meta), lines)


def insert_line(doc: LrcDoc, after: int, text: str, start_ms: int, end_ms: int, total_ms: int) -> LrcDoc:
    """New line after line `after` (-1 = first), its words spread evenly between start and end."""
    parts = split_line(text.strip(), "ja" if _CJK.search(text) else "other")
    step = max(10, (end_ms - start_ms) // max(1, len(parts)))
    segs = [Segment(p, start_ms + i * step, start_ms + (i + 1) * step) for i, p in enumerate(parts)]
    lines = [Line(l.start_ms, [replace(s) for s in l.segments], l.conf) for l in doc.lines]
    lines.insert(after + 1, Line(start_ms, segs, 1.0))
    review = [i + 1 if i > after else i for i in _review(doc.meta)]
    return LrcDoc(_with_review(doc.meta, review), refine(lines, total_ms))


def merge_with_previous(doc: LrcDoc, index: int) -> LrcDoc:
    """Joins line `index` onto the end of the line above, keeping every word's time. Latin text gets
    a space between the two parts; Japanese does not. A merged line is flagged if either part was."""
    if index <= 0 or index >= len(doc.lines):
        return doc
    above, below = doc.lines[index - 1], doc.lines[index]
    head = [replace(s) for s in above.segments]
    tail = [replace(s) for s in below.segments]
    if head and not _CJK.search(above.text + below.text):
        head[-1].text = head[-1].text.rstrip() + " "
    merged = Line(above.start_ms if above.start_ms is not None else below.start_ms, head + tail,
                  min(above.conf, below.conf))
    lines = list(doc.lines[:index - 1]) + [merged] + list(doc.lines[index + 1:])
    review = {i - 1 if i >= index else i for i in _review(doc.meta)}
    return LrcDoc(_with_review(doc.meta, list(review)), lines)


def apply_edits(doc: LrcDoc, line: int, segments: list[Segment], total_ms: int) -> LrcDoc:
    """Replaces one line's segments and re-runs refine, so edited times stay ordered and never
    overlap their neighbours. Other lines keep their times."""
    lines = [Line(l.start_ms, [replace(s) for s in l.segments], l.conf) for l in doc.lines]
    lines[line] = Line(segments[0].start_ms if segments else lines[line].start_ms,
                       [replace(s) for s in segments], lines[line].conf)
    return LrcDoc(dict(doc.meta), refine(lines, total_ms))
