"""What the app shows about each track, and the one edit operation it needs. No Qt here."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import mutagen

from .. import config
from .. import models as model_catalog
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
    status: str            # pending | done | review | other | failed | processing | cancelled
    source: str = ""
    conf: float = 0.0
    review_lines: list[int] = field(default_factory=list)
    error: str = ""
    device: str = ""       # where the vocals were separated: rocm, cuda, dml, cpu or kept
    fallback: str = ""     # why the WSL/ROCm separation ran on the CPU instead
    log_path: str = ""     # this track's log.txt, kept so Refresh and Details can find it
    models: dict[str, str] = field(default_factory=dict)  # [#models:] tag: stage -> model id
    notes: list[str] = field(default_factory=list)  # warnings written in [#warning:...] (R1-09)


MODEL_STAGE_LABELS = {"transcribe": "Transcription", "separate": "Vocal separation",
                      "align": "Alignment", "singing": "Singing model"}


def parse_models_tag(raw: str) -> dict[str, str]:
    """The ``[#models:stage=id;...]`` tag as a dict, ignoring unknown or malformed pairs."""
    out: dict[str, str] = {}
    for part in str(raw or "").split(";"):
        stage, sep, model_id = part.partition("=")
        stage, model_id = stage.strip(), model_id.strip()
        if sep and stage in model_catalog.STAGES and model_id:
            out[stage] = model_id
    return out


def current_model_ids() -> dict[str, set[str]]:
    """Every model id the current choices can resolve for each stage.

    The default choice plus every language override, because the .lrc tag does not record the
    language: a song made with a language-specific model is not "made with other models".
    """
    choices = config.model_choices()
    ids = {stage: {model_catalog.resolve(stage, choices=choices).id}
           for stage in model_catalog.STAGES}
    languages = choices.get("languages") if isinstance(choices.get("languages"), dict) else {}
    for lang, entry in languages.items():
        if not isinstance(entry, dict):
            continue
        for stage in model_catalog.STAGES:
            if stage in entry:
                try:
                    ids[stage].add(model_catalog.resolve(stage, lang=str(lang), choices=choices).id)
                except LookupError:
                    pass
    return ids


def other_model_stages(row: TrackRow, current: dict[str, set[str]] | None = None) -> list[str]:
    """Stages whose [#models:] id is not among what the current choices would resolve."""
    if not row.models:
        return []
    current = current if current is not None else current_model_ids()
    return [stage for stage in model_catalog.STAGES
            if stage in row.models and row.models[stage] not in current.get(stage, set())]


def other_models_text(row: TrackRow, current: dict[str, set[str]] | None = None) -> str:
    """A tooltip naming the stages a finished song used a different model for."""
    current = current if current is not None else current_model_ids()
    stages = other_model_stages(row, current)
    if not stages:
        return ""
    lines = []
    for stage in stages:
        ids = sorted(current.get(stage, set()))
        labels = []
        for model_id in ids:
            spec = model_catalog.find(model_id)
            labels.append(spec.label if spec is not None else model_id)
        now = ", ".join(labels) or "the catalog default"
        lines.append(f"{MODEL_STAGE_LABELS.get(stage, stage)}: {row.models[stage]} "
                     f"(current: {now})")
    return "Made with other models:\n" + "\n".join(lines)


def _flac_tags(audio: Path) -> tuple[str, str] | None:
    """Reads only the Vorbis comment block of a FLAC file.

    Mutagen loads every metadata block, including embedded cover art. A library with a few very
    large scans then spends minutes in the first scan. The Vorbis comment is a small block near the
    start, so this reads it directly and skips the rest. An unusual or corrupt layout returns empty
    strings instead of falling back to mutagen, so one bad file cannot stall the whole scan.
    """
    try:
        with audio.open("rb") as f:
            if f.read(4) != b"fLaC":
                return "", ""
            while True:
                header = f.read(4)
                if len(header) != 4:
                    return "", ""
                last, block_type = header[0] & 0x80, header[0] & 0x7F
                size = int.from_bytes(header[1:4], "big")
                if size > 64_000_000:
                    return "", ""      # a corrupt or absurd metadata block: do not read it
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
                    return "", ""
                f.seek(size, 1)
    except (OSError, struct.error, IndexError):
        return "", ""


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
    lrc = audio.with_suffix(".lrc")
    # Reading tags opens every audio file; on a large external library that is the slowest part of
    # the first scan. Pending tracks use the Artist/Album/Track folder layout instead; once a track
    # has a .lrc (or is loaded/processed) the real tags are read.
    tag_artist, tag_title = _tags(audio) if lrc.exists() else ("", "")
    folder = audio.parent.parent.name if audio.parent.parent != audio.parent else ""
    row = TrackRow(audio, tag_artist or folder, tag_title or audio.stem, "pending")
    if not lrc.exists():
        return row
    meta = parse_lrc(lrc.read_text(encoding="utf-8", errors="replace")).meta
    if not is_ours(meta.get("re")):
        row.status = "other"
        return row
    source, _, conf = meta.get("#source", "").partition(" conf:")
    row.source = source
    try:
        row.conf = float(conf) if conf else 0.0
    except ValueError:
        row.conf = 0.0
        row.error = f"invalid confidence in {lrc.name}: {conf!r}"
    row.review_lines = [int(x) for x in meta.get("#review", "").split(",") if x.strip().isdigit()]
    row.models = parse_models_tag(meta.get("#models", ""))
    row.notes = [part.strip() for part in meta.get("#warning", "").split(";") if part.strip()]
    # A transcription-only lyric, or one the engine flagged with a warning, is an implicit review
    # until the user accepts it. "Clear review flags" writes an empty [#review:] tag, which records
    # that the whole lyric was accepted; the warnings stay visible as notes.
    accepted = "#review" in meta
    implicit_review = (source == "transcription" or bool(row.notes)) and not accepted
    row.status = "review" if row.review_lines or implicit_review else "done"
    return row


def scan(root: Path) -> list[TrackRow]:
    return [read_status(p) for p in find_audio(root)]


# ---- scan cache: one JSON per library; a track is re-read only when its audio or .lrc changed ----
# The schema version lets an old or hand-edited cache be discarded instead of crashing every scan.

SCAN_SCHEMA = 5


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


def _discard_cache(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _read_cache(root: Path) -> dict[str, dict]:
    """The cached rows, or {} when the file is missing, corrupt or from an older schema."""
    path = _cache_file(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        _discard_cache(path)   # a corrupt cache must not be read again
        return {}
    if not isinstance(data, dict) or data.get("schema") != SCAN_SCHEMA:
        _discard_cache(path)
        return {}
    rows = data.get("rows")
    return rows if isinstance(rows, dict) else {}


def _row_from_json(d: dict) -> TrackRow:
    """Validates one cached row. Raises ValueError/TypeError so the caller can re-read the file."""
    if not isinstance(d, dict):
        raise ValueError("cached row is not an object")
    d = dict(d)
    d.pop("stamp", None)
    path = d.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("cached row has no path")
    d["path"] = Path(path)
    for key in ("artist", "title", "status"):
        if not isinstance(d.get(key), str):
            raise ValueError(f"cached row has no {key}")
    d["source"] = d.get("source") if isinstance(d.get("source"), str) else ""
    try:
        d["conf"] = float(d.get("conf", 0.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("cached row has an invalid confidence") from exc
    review = d.get("review_lines", [])
    if not isinstance(review, list) or not all(isinstance(i, int) for i in review):
        raise ValueError("cached row has invalid review lines")
    d["review_lines"] = review
    d["error"] = d.get("error") if isinstance(d.get("error"), str) else ""
    d["device"] = d.get("device") if isinstance(d.get("device"), str) else ""
    d["fallback"] = d.get("fallback") if isinstance(d.get("fallback"), str) else ""
    d["log_path"] = d.get("log_path") if isinstance(d.get("log_path"), str) else ""
    used = d.get("models", {})
    if not isinstance(used, dict):
        used = {}
    d["models"] = {str(k): str(v) for k, v in used.items()
                   if isinstance(k, str) and isinstance(v, str)}
    notes = d.get("notes", [])
    if not isinstance(notes, list) or not all(isinstance(n, str) for n in notes):
        notes = []
    return TrackRow(path=d["path"], artist=d["artist"], title=d["title"], status=d["status"],
                    source=d["source"], conf=d["conf"], review_lines=d["review_lines"], error=d["error"],
                    device=d["device"], fallback=d["fallback"], log_path=d["log_path"],
                    models=d["models"], notes=notes)


def _unreadable_row(audio: Path, exc: Exception) -> TrackRow:
    folder = audio.parent.parent.name if audio.parent.parent != audio.parent else ""
    return TrackRow(audio, folder, audio.stem, "other", error=f"could not read this file: {type(exc).__name__}: {exc}")


def load_cached_rows(root: Path) -> list[TrackRow]:
    """Rows from the last scan of this library, without touching the files (instant on startup).
    A corrupt cache or one bad row is ignored; the next scan rebuilds the cache."""
    rows = []
    for data in _read_cache(root).values():
        try:
            rows.append(_row_from_json(data))
        except (TypeError, ValueError, KeyError):
            continue
    return rows


def scan_cached(root: Path, stats: dict | None = None) -> list[TrackRow]:
    """Full listing, re-reading only tracks whose audio or .lrc changed since the last scan.

    One unreadable file (a hand-edited .lrc, a file deleted mid-scan) must not kill Refresh, so
    each file is handled on its own; `stats["unreadable"]` counts the failures for the UI."""
    stats = stats if stats is not None else {}
    stats["unreadable"] = 0
    old = _read_cache(root)
    new, rows = {}, []
    for audio in find_audio(root):
        try:
            stamp = _stamp(audio)
        except OSError as exc:
            stats["unreadable"] += 1
            rows.append(_unreadable_row(audio, exc))
            continue
        cached = old.get(str(audio))
        row = None
        if isinstance(cached, dict) and cached.get("stamp") == stamp:
            try:
                row = _row_from_json(cached)
            except (TypeError, ValueError, KeyError):
                row = None
        if row is None:
            try:
                row = read_status(audio)
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the scan
                stats["unreadable"] += 1
                row = _unreadable_row(audio, exc)
        new[str(audio)] = _row_to_json(row, stamp)
        rows.append(row)
    path = _cache_file(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema": SCAN_SCHEMA, "rows": new}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass   # the next scan rebuilds it; the listing itself is still valid
    return rows


def store_result(root: Path, row: TrackRow) -> None:
    """Records a finished queue result in this library's scan cache.

    Refresh re-reads a cached row only while its audio and .lrc stamps are unchanged, so the last
    error, device and fallback reason survive a Refresh instead of turning a failed row into
    "pending" again. A track outside the library is stored too; the next scan drops it.
    """
    path = _cache_file(root)
    rows = _read_cache(root)
    try:
        rows[str(row.path)] = _row_to_json(row, _stamp(row.path))
    except OSError:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"schema": SCAN_SCHEMA, "rows": rows}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass   # a cache write failure must never break the queue


def delete_line(doc: LrcDoc, index: int) -> LrcDoc:
    """Removes one line; review markers after it move up by one. An explicitly empty
    `[#review:]` (the user accepted the whole lyric) is kept."""
    meta = dict(doc.meta)
    accepted = meta.get("#review") == ""
    review = [int(x) for x in meta.pop("#review", "").split(",") if x.strip().isdigit()]
    review = [i - 1 if i > index else i for i in review if i != index]
    if review:
        meta["#review"] = ",".join(map(str, review))
    elif accepted:
        meta["#review"] = ""
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


def review_lines(doc: LrcDoc | None) -> list[int]:
    """The zero-based line indices still flagged for review."""
    return _review(doc.meta) if doc is not None else []


def _with_review(meta: dict, review: list[int]) -> dict:
    accepted = meta.get("#review") == ""   # an explicitly empty tag means "reviewed, no flags"
    meta = {k: v for k, v in meta.items() if k != "#review"}
    if review:
        meta["#review"] = ",".join(map(str, sorted(review)))
    elif accepted:
        meta["#review"] = ""
    return meta


def mark_line_reviewed(doc: LrcDoc, index: int) -> LrcDoc:
    """Clears one line's review flag. Accepting the last flagged line records an empty tag, so
    the track can leave the Review filter without losing the fact that a human accepted it."""
    review = _review(doc.meta)
    if index not in review:
        return doc
    review.remove(index)
    meta = _with_review(doc.meta, review)
    if not review:
        meta["#review"] = ""
    return LrcDoc(meta, list(doc.lines))


def clear_review_flags(doc: LrcDoc) -> LrcDoc:
    """Accepts every line: removes the flags and records the decision with an empty tag. The empty
    tag is what lets a transcription-only lyric leave the Review filter."""
    if doc.meta.get("#review") == "":
        return doc
    source = doc.meta.get("#source", "")
    if "#review" not in doc.meta and not source.startswith("transcription"):
        return doc   # already accepted/done; do not add a pointless tag
    return LrcDoc(_with_review({**doc.meta, "#review": ""}, []), list(doc.lines))


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
