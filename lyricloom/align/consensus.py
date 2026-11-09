"""Extra precision for songs with no official lyrics, where Whisper's text becomes the lyrics.

rover(): several Whisper passes are aligned word by word against the first one; at each word the
reading most passes agree on wins, ties going to Whisper's own confidence. The first pass's words
and times are the skeleton: a word is never dropped and no time is invented.

refrain_consensus(): lines that repeat (refrains) are compared, and where at least three
near-identical repetitions disagree on a word, the strict majority wins."""
from __future__ import annotations

import re
from collections import defaultdict

from rapidfuzz import fuzz

from ..model import Transcript, Word
from ..text import reading
from ..text.mms import to_mms_tokens

WORD_MATCH = 0.8          # phonetic similarity for two words to count as the same word
REFRAIN_SIMILARITY = 0.88  # phonetic similarity for two lines to count as the same refrain
REFRAIN_MIN_REPEATS = 3

_PUNCT = re.compile(r"[^\w']+", re.UNICODE)


def _key(text: str) -> str:
    return _PUNCT.sub("", text).lower()


def _phon(text: str, lang: str) -> str:
    return to_mms_tokens(reading(text, lang))


def _similar(a: str, b: str, threshold: float) -> bool:
    """Two empty romanizations are not similar; rapidfuzz scores "" == "" as a perfect match."""
    return bool(a) and bool(b) and fuzz.ratio(a, b) / 100 >= threshold


def _align_words(a: list[Word], b: list[Word], lang: str) -> list[int | None]:
    """For each word of `a`, the index of the aligned word of `b` (None for a gap)."""
    pa, pb = [_phon(w.text, lang) for w in a], [_phon(w.text, lang) for w in b]
    n, m = len(a), len(b)
    H = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        H[i][0] = -i
    for j in range(1, m + 1):
        H[0][j] = -j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            s = 2 if _similar(pa[i - 1], pb[j - 1], WORD_MATCH) else -1
            H[i][j] = max(H[i - 1][j - 1] + s, H[i - 1][j] - 1, H[i][j - 1] - 1)
    out: list[int | None] = [None] * n
    i, j = n, m
    while i > 0 and j > 0:
        s = 2 if _similar(pa[i - 1], pb[j - 1], WORD_MATCH) else -1
        if H[i][j] == H[i - 1][j - 1] + s:
            out[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif H[i][j] == H[i - 1][j] - 1:
            i -= 1
        else:
            j -= 1
    return out


def _vote(options: list[Word]) -> Word:
    groups: dict[str, list[Word]] = defaultdict(list)
    for w in options:
        groups[_key(w.text) or w.text].append(w)
    best = max(groups.values(), key=lambda g: (len(g), max(w.prob for w in g)))
    return max(best, key=lambda w: w.prob)


def rover(transcripts: list[Transcript], lang: str) -> Transcript:
    primary = transcripts[0]
    links = [_align_words(primary.words, t.words, lang) for t in transcripts[1:]]
    words = []
    for i, w in enumerate(primary.words):
        options = [w] + [t.words[l[i]] for t, l in zip(transcripts[1:], links) if l[i] is not None]
        win = _vote(options)
        words.append(Word(win.text, w.start_ms, w.end_ms, max(o.prob for o in options if _key(o.text) == _key(win.text))))
    return Transcript(primary.lang, words)


def refrain_consensus(lines: list[list[Word]], lang: str) -> list[list[Word]]:
    phon = [_phon(" ".join(w.text for w in l), lang) for l in lines]
    groups: list[list[int]] = []
    for i, line in enumerate(lines):
        for g in groups:
            head = g[0]
            if (len(lines[head]) == len(line) and phon[head] and phon[i]
                    and fuzz.ratio(phon[head], phon[i]) / 100 >= REFRAIN_SIMILARITY):
                g.append(i)
                break
        else:
            groups.append([i])
    out = [list(l) for l in lines]
    for g in groups:
        if len(g) < REFRAIN_MIN_REPEATS:
            continue
        for k in range(len(lines[g[0]])):
            counts: dict[str, list[Word]] = defaultdict(list)
            for i in g:
                counts[_key(lines[i][k].text) or lines[i][k].text].append(lines[i][k])
            top = max(counts.values(), key=len)
            if len(top) * 2 <= len(g):
                continue  # no strict majority: leave the repetitions as Whisper heard them
            text = top[0].text
            for i in g:
                w = out[i][k]
                out[i][k] = Word(text, w.start_ms, w.end_ms, w.prob)
    return out
