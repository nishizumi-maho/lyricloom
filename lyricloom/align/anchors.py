"""Anchors: lyric lines that Whisper clearly heard, with their times. They split the song into
short blocks so that a forced-alignment error cannot drift across the whole track."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..model import Word
from ..text import reading
from ..text.mms import to_mms_tokens

MATCH, MISMATCH, GAP = 2, -1, -1
ANCHOR_MIN_MATCHED = 0.70
BLOCK_MARGIN_MS = 500


@dataclass
class Anchor:
    line_idx: int
    start_ms: int
    end_ms: int
    score: float


@dataclass
class Block:
    line_start: int  # first line, inclusive
    line_end: int    # last line, exclusive
    start_ms: int
    end_ms: int


def _chars(texts: list[str], lang: str) -> tuple[np.ndarray, np.ndarray]:
    chars, owner = [], []
    for i, t in enumerate(texts):
        for c in to_mms_tokens(reading(t, lang)):
            chars.append(ord(c))
            owner.append(i)
    return np.array(chars, dtype=np.int32), np.array(owner, dtype=np.int32)


def _needleman_wunsch(a: np.ndarray, b: np.ndarray) -> list[tuple[int, int]]:
    """Global alignment; returns (i, j) pairs of aligned positions (either may be a match or not)."""
    n, m = len(a), len(b)
    H = np.zeros((n + 1, m + 1), dtype=np.int32)
    H[0] = np.arange(m + 1) * GAP
    idx = np.arange(m + 1, dtype=np.int32)
    for i in range(1, n + 1):
        sub = np.where(b == a[i - 1], MATCH, MISMATCH)
        A = np.empty(m + 1, dtype=np.int32)
        A[0] = i * GAP
        A[1:] = np.maximum(H[i - 1, :-1] + sub, H[i - 1, 1:] + GAP)
        # Left moves: H[i,j] = max_k<=j (A[k] + (j-k)*GAP); with GAP = -1 this is a running max.
        H[i] = np.maximum.accumulate(A + idx) - idx
    pairs = []
    i, j = n, m
    while i > 0 and j > 0:
        s = MATCH if a[i - 1] == b[j - 1] else MISMATCH
        if H[i, j] == H[i - 1, j - 1] + s:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif H[i, j] == H[i - 1, j] + GAP:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def find_anchors(lines: list[str], lang: str, words: list[Word]) -> list[Anchor]:
    la, lown = _chars(lines, lang)
    wa, wown = _chars([w.text for w in words], lang)
    if len(la) == 0 or len(wa) == 0:
        return []
    per_line: dict[int, list[int]] = {}
    for i, j in _needleman_wunsch(la, wa):
        if la[i] == wa[j]:
            per_line.setdefault(int(lown[i]), []).append(int(wown[j]))
    totals = np.bincount(lown, minlength=len(lines))
    anchors = []
    for line, matched_words in sorted(per_line.items()):
        frac = len(matched_words) / totals[line]
        if frac >= ANCHOR_MIN_MATCHED:
            anchors.append(Anchor(line, words[matched_words[0]].start_ms, words[matched_words[-1]].end_ms, float(frac)))
    kept: list[Anchor] = []
    for a in anchors:  # global alignment is monotonic already; this guards against equal-time ties
        if not kept or a.start_ms >= kept[-1].start_ms:
            kept.append(a)
    return kept


def blocks(anchors: list[Anchor], n_lines: int, total_ms: int) -> list[Block]:
    """Lines between consecutive anchors form a block; each anchored line starts a new block."""
    if not anchors:
        return [Block(0, n_lines, 0, total_ms)]
    out = []
    if anchors[0].line_idx > 0:
        out.append(Block(0, anchors[0].line_idx, 0, min(total_ms, anchors[0].start_ms + BLOCK_MARGIN_MS)))
    for k, a in enumerate(anchors):
        nxt = anchors[k + 1] if k + 1 < len(anchors) else None
        end_line = nxt.line_idx if nxt else n_lines
        end_ms = min(total_ms, nxt.start_ms + BLOCK_MARGIN_MS) if nxt else total_ms
        out.append(Block(a.line_idx, end_line, max(0, a.start_ms - BLOCK_MARGIN_MS), end_ms))
    return out
