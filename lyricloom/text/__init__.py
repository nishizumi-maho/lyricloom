"""Splits lyric lines into timed segments and gives each one a romanized reading."""
from __future__ import annotations

from . import japanese, latin


def split_line(line: str, lang: str) -> list[str]:
    """Segments whose concatenation is exactly `line`."""
    return japanese.split(line) if lang == "ja" else latin.split(line)


def reading(segment: str, lang: str) -> str:
    """Lowercase romanized pronunciation, used for acoustic alignment and matching."""
    return japanese.reading(segment) if lang == "ja" else latin.reading(segment)
