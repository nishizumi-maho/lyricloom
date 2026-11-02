"""Strips credits and site boilerplate from fetched lyrics. Parenthesized backing vocals stay,
because they are sung."""
from __future__ import annotations

import re

_CREDIT = re.compile(
    r"^\s*(作詞|作曲|編曲|歌|词|曲|作词|编曲|制作人|混音|Composed by|Lyrics by|Written by|Arranged by|Letra|Música|Musica)\s*[:：]",
    re.IGNORECASE,
)
_BOILERPLATE = re.compile(r"https?://|www\.|Lyrics provided by|Paroles de la chanson", re.IGNORECASE)


def clean_lyrics(text: str) -> str:
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if _CREDIT.match(line) or _BOILERPLATE.search(line):
            continue
        if not line and (not out or not out[-1]):
            continue
        out.append(line)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)
