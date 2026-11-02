"""Align stage: official lyrics -> word-timed lines with confidence."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..align.anchors import blocks, find_anchors
from ..align.confidence import REVIEW_THRESHOLD, line_conf, track_conf
from ..align.ctc import align_blocks
from ..align.merge import merge_presync
from ..align.mtl import align_lines_mtl
from ..align.refine import refine
from ..align.trim import trim_line_ends
from ..model import Candidate, Line, Segment, TrackMeta, Transcript
from ..text import reading, split_line
from ..text.mms import to_mms_tokens
from ..workers import WorkerError

log = logging.getLogger(__name__)

# Confidence of a line timed by the singing model that Whisper did not hear: below
# REVIEW_THRESHOLD, so it is listed for review.
MTL_UNCONFIRMED = 0.55


@dataclass
class AlignResult:
    lines: list[Line]
    track_conf: float
    review: bool


def lyric_lang(meta: TrackMeta, transcript: Transcript) -> str:
    if meta.lang == "ja" or transcript.lang == "ja":
        return "ja"
    return transcript.lang if transcript.lang in ("pt", "en") else "other"


def align(meta: TrackMeta, work: Path, chosen: Candidate, transcript: Transcript, vocals16k: Path,
          vocals: Path | None = None) -> AlignResult:
    """vocals (full rate) enables the singing model for English songs; without it every song uses CTC."""
    lang = lyric_lang(meta, transcript)
    texts = [l.strip() for l in chosen.text.splitlines() if l.strip()]
    total_ms = int(meta.duration_s * 1000)
    anchors = find_anchors(texts, lang, transcript.words)
    anchor_score = {a.line_idx: a.score for a in anchors}
    bs = blocks(anchors, len(texts), total_ms)

    seg_texts = [split_line(t, lang) for t in texts]
    aligned, sung = None, False
    if lang == "en" and vocals is not None and config.MTL_ENABLED:
        try:
            aligned, sung = align_lines_mtl(vocals, seg_texts), True
        except (WorkerError, ValueError, OSError) as e:
            log.warning("singing model failed, using the CTC aligner: %s", str(e)[-300:])
    if aligned is None:
        seg_tokens = [[[to_mms_tokens(reading(s, lang)) for s in seg_texts[i]] for i in range(b.line_start, b.line_end)]
                      for b in bs]
        aligned = align_blocks(vocals16k, bs, seg_tokens)

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
    return AlignResult(lines, conf, any(l.conf < REVIEW_THRESHOLD for l in lines))
