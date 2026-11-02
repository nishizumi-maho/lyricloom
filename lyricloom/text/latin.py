from __future__ import annotations

import re
import unicodedata

_WORD_WITH_SPACE = re.compile(r"\S+\s*|\s+")


def split(line: str) -> list[str]:
    """Each word keeps the whitespace that follows it."""
    return _WORD_WITH_SPACE.findall(line)


def reading(segment: str) -> str:
    decomposed = unicodedata.normalize("NFKD", segment)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
