"""Scores lyric candidates and picks the official one."""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from ..model import Candidate, TrackMeta
from ..text import reading

SOURCE_WEIGHT = {
    "uta-net": 1.0, "j-lyric": 1.0, "utaten": 1.0, "letras": 1.0,
    "netease": 0.9, "qq": 0.9, "musixmatch": 0.9,
    "lrclib": 0.8, "genius": 0.8,
    "websearch": 0.6,
}
MIN_ACCEPT = 0.55

_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]|（[^）]*）")


def _norm_title(s: str) -> str:
    return _BRACKETS.sub(" ", s).strip().lower()


def duration_score(track_s: float, cand_s: float | None) -> float:
    if cand_s is None:
        return 0.5
    d = abs(track_s - cand_s)
    if d <= 3:
        return 1.0
    if d >= 20:
        return 0.0
    return 1.0 - (d - 3) / 17


def score_meta(c: Candidate, meta: TrackMeta, cand_title: str, cand_artist: str,
               cand_duration_s: float | None) -> float:
    title = fuzz.token_set_ratio(_norm_title(meta.title), _norm_title(cand_title)) / 100
    artist = fuzz.token_set_ratio(meta.artist.lower(), cand_artist.lower()) / 100
    return (0.4 * title + 0.3 * artist + 0.2 * duration_score(meta.duration_s, cand_duration_s)
            + 0.1 * SOURCE_WEIGHT.get(c.source, 0.5))


def _phonetic(text: str, lang: str) -> str:
    return re.sub(r"[^a-z]", "", reading(text, lang))


def score_transcript(c: Candidate, transcript: str, lang: str) -> float:
    return fuzz.ratio(_phonetic(c.text, lang), _phonetic(transcript, lang)) / 100


# Lyrics must resemble what was heard on their own: the right lyrics scored 0.77 against the
# transcript, another song by the same artist 0.43, a different version 0.37. A matching title can
# never make up for lyrics that do not match the singing.
MIN_TRANSCRIPT_MATCH = 0.60
# With no usable transcript (e.g. Whisper hallucinated and no AssemblyAI), only a near-perfect
# title/artist/duration match is trusted.
MIN_META_WITHOUT_TRANSCRIPT = 0.85


def choose(cands: list[Candidate], transcript: str, lang: str) -> Candidate | None:
    has_transcript = bool(re.sub(r"\W", "", transcript or ""))
    best, best_final = None, -1.0
    for c in cands:
        if has_transcript:
            heard = score_transcript(c, transcript, lang)
            if heard < MIN_TRANSCRIPT_MATCH:
                continue
            final = 0.5 * c.score + 0.5 * heard
        else:
            if c.score < MIN_META_WITHOUT_TRANSCRIPT:
                continue
            final = c.score
        if final > best_final:
            best, best_final = c, final
    return best if best is not None and best_final >= MIN_ACCEPT else None
