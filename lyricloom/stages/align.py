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
# A singing-model line agrees with Whisper when it starts within this distance of Whisper's anchor
# and stays inside its block with the same slack; at least this share of lines must agree.  On a
# real song 85% agreed; shifted or drifting alignments agreed on 0-13% (2026-11-10 measurements).
MTL_ANCHOR_TOLERANCE_MS = 2000
MTL_MIN_AGREEMENT = 0.75
# Each CTC window also holds this many neighbouring blocks on each side, and only its central
# block's lines are kept. Aligned alone, a line had to explain the end of the line before it and
# the start of the next one with its own words, so its first word could start on the previous
# line's last note (lit before it is sung). Measured 2026-11-11 against human timing: English
# word starts within 100 ms of NetEase's 71% -> 82% (more than 0.5 s off: 70 -> 37 words);
# Japanese lines within 0.5 s of LRCLIB's 62% -> 71%, 92% -> 95% and 96% -> 96%.
CTC_CONTEXT_BLOCKS = 1
# Languages aligned in one CTC pass over the whole song instead of blocks cut at the anchors.
# Whisper times Japanese in phrase-long pieces on round seconds, and blocks cut there held lines
# out of place: without the cloud, 55% of Redo's lines were within 0.5 s of a human sync, 95% in
# one pass; Reweave, with no usable Whisper anchor at all, 98%. With the cloud's word-level
# anchors one pass did as well as the blocks (95% and 98% against 95% and 96%).
WHOLE_SONG_CTC_LANGS = frozenset({"ja"})

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


def context_windows(bs: list[Block], context: int = CTC_CONTEXT_BLOCKS) -> list[Block]:
    """Each block widened by ``context`` neighbouring blocks on each side (lines and time)."""
    if context <= 0:
        return list(bs)
    out = []
    for j in range(len(bs)):
        lo, hi = max(0, j - context), min(len(bs) - 1, j + context)
        out.append(Block(bs[lo].line_start, bs[hi].line_end, bs[lo].start_ms, bs[hi].end_ms))
    return out


def central_rows(bs: list[Block], windows: list[Block], rows: list) -> list:
    """The aligned rows of each window's own block, in line order (rows are per window line)."""
    out = []
    k = 0
    for b, w in zip(bs, windows):
        for line in range(w.line_start, w.line_end):
            if k >= len(rows):
                return out
            if b.line_start <= line < b.line_end:
                out.append(rows[k])
            k += 1
    return out


def _block_for_line(bs: list[Block], line_idx: int) -> Block | None:
    for b in bs:
        if b.line_start <= line_idx < b.line_end:
            return b
    return bs[-1] if bs else None


def _mtl_problems(seg_texts: list[list[str]], aligned: list[list[Segment | None]],
                  bs: list[Block], anchors: list[Anchor]) -> list[str]:
    """Sanity-checks the singing model's timing before it is trusted (R1-16).

    The structure must be sound (one row per line, one timing per word, words in order and with a
    duration), and most lines must start near where Whisper heard them and stay in their block.
    The anchors and blocks come from Whisper's word timing, which on sung vocals is often several
    hundred ms early (seconds on a held intro note), so one disagreeing line is no evidence against
    the singing model; a broken alignment (lines shifted, a drift) disagrees on most lines."""
    problems: list[str] = []
    if len(aligned) != len(seg_texts):
        return [f"returned {len(aligned)} lines for {len(seg_texts)}"]
    anchor_at = {a.line_idx: a for a in anchors}
    checked = agreeing = 0
    for i, (line, texts) in enumerate(zip(aligned, seg_texts)):
        if len(line) != len(texts):
            problems.append(f"line {i} has {len(line)} words for {len(texts)} segments")
            continue
        timed = [s for s in line if s is not None and s.start_ms is not None]
        if not timed:
            continue
        prev_start = prev_end = None
        for s in timed:
            if s.end_ms is None or s.start_ms >= s.end_ms:
                problems.append(f"line {i} has a word with no duration")
                continue
            if prev_start is not None and s.start_ms <= prev_start:
                problems.append(f"line {i} is not monotonic")
            if prev_end is not None and s.start_ms < prev_end:
                problems.append(f"line {i} has overlapping words")
            prev_start, prev_end = s.start_ms, s.end_ms
        block, anchor = _block_for_line(bs, i), anchor_at.get(i)
        if block is None and anchor is None:
            continue
        start, end = timed[0].start_ms, max(s.end_ms or s.start_ms for s in timed)
        near_anchor = anchor is None or abs(start - anchor.start_ms) <= MTL_ANCHOR_TOLERANCE_MS
        in_block = block is None or (block.start_ms - MTL_ANCHOR_TOLERANCE_MS <= start
                                     and end <= block.end_ms + MTL_ANCHOR_TOLERANCE_MS)
        checked += 1
        agreeing += near_anchor and in_block
    if checked and agreeing < MTL_MIN_AGREEMENT * checked:
        problems.append(f"only {agreeing} of {checked} lines agree with where Whisper heard them")
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
        ctc_blocks = [Block(0, len(texts), 0, total_ms)] if lang in WHOLE_SONG_CTC_LANGS else bs
        windows = context_windows(ctc_blocks)
        seg_tokens = [[[to_mms_tokens(reading(s, lang)) for s in seg_texts[i]] for i in range(w.line_start, w.line_end)]
                      for w in windows]
        # align_blocks resolves the align model for the current choice; make the lyric language
        # visible to it so a per-language align choice is honoured even outside runner.process.
        previous = config.active_language()
        config.set_active_language(lang)
        try:
            aligned = central_rows(ctc_blocks, windows,
                                   align_blocks(vocals16k, windows, seg_tokens, cancel=cancel))
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
