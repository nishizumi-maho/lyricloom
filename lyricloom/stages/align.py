"""Align stage: official lyrics -> word-timed lines with confidence."""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .. import config, models
from ..align.anchors import Anchor, Block, blocks, find_anchors
from ..align.confidence import REVIEW_THRESHOLD, line_conf, track_conf
from ..align.ctc import align_blocks
from ..align.merge import merge_presync
from ..align.mtl import align_lines_mtl
from ..align.refine import refine
from ..align.trim import trim_line_ends
from ..model import Candidate, Line, Segment, TrackMeta, Transcript
from ..text import reading, split_line
from ..text.mms import to_mms_tokens
from ..text.scripts import unsupported_reason
from ..workers import WorkerError

log = logging.getLogger(__name__)

# Confidence of a line timed by the singing model that Whisper did not hear: below
# REVIEW_THRESHOLD, so it is listed for review.
MTL_UNCONFIRMED = 0.55
MTL_MARGIN_MS = 500

_NOISE = re.compile(r"[\s\W_]+", re.UNICODE)


def _norm(text: str) -> str:
    return _NOISE.sub("", text).lower()


@dataclass
class AlignResult:
    lines: list[Line]
    track_conf: float
    review: bool
    models_used: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def lyric_lang(meta: TrackMeta, transcript: Transcript) -> str:
    # An explicit per-song language (app/CLI/tag) must survive; otherwise Japanese wins, then the
    # languages the text layer understands, and everything else is "other".
    if meta.lang == "ja" or transcript.lang == "ja":
        return "ja"
    if meta.lang not in ("", "other"):
        return meta.lang
    return transcript.lang if transcript.lang in ("pt", "en") else "other"


def _line_timing(texts: list[str], total_ms: int, presync: list[Line] | None) -> list[Line]:
    """Line timestamps for lyrics that cannot be word-aligned at all.

    A source's line-level timing is used when its text matches; the remaining lines are spread
    over the track in proportion to their length, so an LRC player still scrolls sensibly."""
    starts: list[int | None] = [None] * len(texts)
    used: set[int] = set()
    for i, text in enumerate(texts):
        key = _norm(text)
        if not key or not presync:
            continue
        for j, candidate in enumerate(presync):
            if j not in used and candidate.start_ms is not None and _norm(candidate.text) == key:
                starts[i] = candidate.start_ms
                used.add(j)
                break
    weights = [max(1, len(t)) for t in texts]
    total = max(1, sum(weights))
    cursor = 0
    for i, weight in enumerate(weights):
        if starts[i] is None:
            starts[i] = min(total_ms, round(total_ms * cursor / total))
        cursor += weight
    lines = []
    for text, start in zip(texts, starts):
        lines.append(Line(min(total_ms, int(start or 0)), [Segment(text, None, None)], 0.0))
    return lines


def _block_for_line(bs: list[Block], line_idx: int) -> Block | None:
    for b in bs:
        if b.line_start <= line_idx < b.line_end:
            return b
    return bs[-1] if bs else None


def _mtl_problems(seg_texts: list[list[str]], aligned: list[list[Segment | None]],
                  bs: list[Block], anchors: list[Anchor]) -> list[str]:
    """Sanity-checks the singing model's timing before it is trusted (R1-16)."""
    problems: list[str] = []
    if len(aligned) != len(seg_texts):
        return [f"returned {len(aligned)} lines for {len(seg_texts)}"]
    anchor_at = {a.line_idx: a for a in anchors}
    for i, (line, texts) in enumerate(zip(aligned, seg_texts)):
        if len(line) != len(texts):
            problems.append(f"line {i} has {len(line)} words for {len(texts)} segments")
            continue
        block = _block_for_line(bs, i)
        timed = [s for s in line if s is not None and s.start_ms is not None]
        if not timed:
            continue
        prev_start = prev_end = None
        for s in timed:
            if s.end_ms is None or s.start_ms >= s.end_ms:
                problems.append(f"line {i} has a word with no duration")
                continue
            if block is not None and (s.start_ms < block.start_ms - MTL_MARGIN_MS
                                      or s.end_ms > block.end_ms + MTL_MARGIN_MS):
                problems.append(f"line {i} is outside its block")
            if prev_start is not None and s.start_ms <= prev_start:
                problems.append(f"line {i} is not monotonic")
            if prev_end is not None and s.start_ms < prev_end:
                problems.append(f"line {i} has overlapping words")
            prev_start, prev_end = s.start_ms, s.end_ms
        anchor = anchor_at.get(i)
        if anchor is not None and abs(timed[0].start_ms - anchor.start_ms) > MTL_MARGIN_MS:
            problems.append(f"line {i} does not agree with the anchor")
    return problems[:6]


def align(meta: TrackMeta, work: Path, chosen: Candidate, transcript: Transcript, vocals16k: Path,
          vocals: Path | None = None, cancel: threading.Event | None = None) -> AlignResult:
    """vocals (full rate) enables the singing model for English songs; without it every song uses CTC."""
    lang = lyric_lang(meta, transcript)
    texts = [l.strip() for l in chosen.text.splitlines() if l.strip()]
    total_ms = int(meta.duration_s * 1000)
    reason = unsupported_reason("\n".join(texts), lang)
    if reason:
        note = (f"{reason} lyrics cannot be word-aligned: the aligner has no reading for that "
                f"script; wrote line-level timing for review")
        log.warning(note)
        lines = _line_timing(texts, total_ms, chosen.synced)
        return AlignResult(lines, 0.0, True, notes=[note])

    anchors = find_anchors(texts, lang, transcript.words)
    anchor_score = {a.line_idx: a.score for a in anchors}
    bs = blocks(anchors, len(texts), total_ms)

    align_spec = config.resolve_model("align", lang)
    seg_texts = [split_line(t, lang) for t in texts]
    aligned, sung, singing_spec = None, False, None
    mtl_note = None
    if lang == "en" and vocals is not None and models.singing_ready(lang):
        try:
            singing_spec = config.resolve_model("singing", lang)
            candidate = align_lines_mtl(vocals, seg_texts, cancel=cancel)
            problems = _mtl_problems(seg_texts, candidate, bs, anchors)
            if problems:
                mtl_note = ("the singing-model alignment failed its sanity check ("
                            + "; ".join(problems) + "); used CTC and marked the track for review")
                log.warning(mtl_note)
            else:
                aligned, sung = candidate, True
        except (WorkerError, ValueError, OSError, TypeError) as e:
            log.warning("singing model failed, using the CTC aligner: %s", str(e)[-300:])
    used: dict[str, str] = {}
    if aligned is None:
        seg_tokens = [[[to_mms_tokens(reading(s, lang)) for s in seg_texts[i]] for i in range(b.line_start, b.line_end)]
                      for b in bs]
        # align_blocks resolves the align model for the current choice; make the lyric language
        # visible to it so a per-language align choice is honoured even outside runner.process.
        previous = config.active_language()
        config.set_active_language(lang)
        try:
            aligned = align_blocks(vocals16k, bs, seg_tokens, cancel=cancel)
        finally:
            config.set_active_language(previous)
        used["align"] = align_spec.id   # only CTC actually ran this model (FR-A-04)

    lines = []
    for i, (segs_text, segs) in enumerate(zip(seg_texts, aligned)):
        segments = [Segment(t, None, None) if s is None else Segment(t, s.start_ms, s.end_ms, s.conf)
                    for t, s in zip(segs_text, segs)]
        scores = [s.conf for s in segs if s is not None]
        first = next((s.start_ms for s in segments if s.start_ms is not None), None)
        if sung:   # the singing model gives no per-word score: Whisper hearing the line is the confirmation
            conf = anchor_score.get(i, MTL_UNCONFIRMED) if scores else 0.0
        else:
            conf = line_conf(scores, anchor_score.get(i))
        lines.append(Line(first, segments, conf))
    if chosen.synced:
        lines = merge_presync(lines, chosen.synced)
    lines = refine(lines, total_ms)
    lines = trim_line_ends(lines, vocals16k)
    conf = track_conf(lines)
    review = any(l.conf < REVIEW_THRESHOLD for l in lines) or bool(mtl_note)
    notes = [mtl_note] if mtl_note else []
    if sung and singing_spec is not None:
        used["singing"] = singing_spec.id
    return AlignResult(lines, conf, review, used, notes)
