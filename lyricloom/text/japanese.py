from __future__ import annotations

import re
from functools import lru_cache

import fugashi
import ipadic
import pykakasi

_READING_FIELD = 7  # ipadic feature: reading in katakana


@lru_cache(maxsize=1)
def _tagger() -> fugashi.GenericTagger:
    return fugashi.GenericTagger(ipadic.MECAB_ARGS)


@lru_cache(maxsize=1)
def _kakasi():
    return pykakasi.kakasi()


# Inline furigana as lyric sites write it: 運命(さだめ), 縒（よ）れた. The kana is the sung reading.
_RUBY = re.compile(r"([一-鿿々〆ヶ]+)[(（]([぀-ゟ゠-ヿ]+)[)）]")


def split(line: str) -> list[str]:
    """Segments whose concatenation is exactly `line`: one per MeCab token, except that
    - inline furigana `(かな)` stays inside the segment of the kanji it reads, and
    - punctuation and other soundless tokens join a neighbouring segment (a segment with nothing to
      sing cannot be timed, and used to leave its whole line without word timing)."""
    base, inserts, pos = "", [], 0
    for m in _RUBY.finditer(line):
        base += line[pos:m.end(1)]
        inserts.append((len(base), line[m.end(1):m.end()]))
        pos = m.end()
    base += line[pos:]

    segments = _glue_silent(_split_plain(base))
    out, start = [], 0
    for seg in segments:
        end = start + len(seg)
        for p, ann in reversed([(p, a) for p, a in inserts if start < p <= end]):
            seg = seg[:p - start] + ann + seg[p - start:]
        out.append(seg)
        start = end
    return out


def _sounds(segment: str) -> bool:
    return bool(re.sub(r"[^a-z]", "", reading(segment)))


def _glue_silent(segments: list[str]) -> list[str]:
    out: list[str] = []
    pending = ""   # soundless text before the first sung segment
    for seg in segments:
        if _sounds(seg):
            out.append(pending + seg)
            pending = ""
        elif out:
            out[-1] += seg
        else:
            pending += seg
    if pending:
        if out:
            out[-1] += pending
        else:
            out.append(pending)
    return out


def _split_plain(line: str) -> list[str]:
    """One segment per MeCab token. Whitespace and anything MeCab skipped stays attached to the
    previous segment, so the segments always join back into the original line."""
    out: list[str] = []
    pos = 0
    for word in _tagger()(line):
        idx = line.find(word.surface, pos)
        if idx < 0:
            continue
        gap = line[pos:idx]
        if out:
            out[-1] += gap
        elif gap:
            out.append(gap)
        out.append(word.surface)
        pos = idx + len(word.surface)
    rest = line[pos:]
    if rest:
        if out:
            out[-1] += rest
        else:
            out.append(rest)
    return out


def _to_romaji(kana: str) -> str:
    return "".join(item["hepburn"] for item in _kakasi().convert(kana))


def reading(segment: str) -> str:
    """Romanized pronunciation. Inline furigana replaces its kanji: 運命(さだめ) reads "sadame"."""
    segment = _RUBY.sub(lambda m: m.group(2), segment)
    parts = []
    for word in _tagger()(segment):
        f = word.feature
        kana = f[_READING_FIELD] if len(f) > _READING_FIELD and f[_READING_FIELD] != "*" else word.surface
        parts.append(_to_romaji(kana))
    return "".join(parts).lower()
