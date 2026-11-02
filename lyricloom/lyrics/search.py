"""Queries every lyric source and returns cleaned, scored candidates.

Sites that refuse scripted requests (Uta-Net, Letras.mus.br and Musixmatch, which answers with
decoy lyrics) have no adapter: blocking is respected, never worked around."""
from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import replace

import httpx

from ..model import Candidate, TrackMeta
from ..text import reading
from .clean import clean_lyrics
from .score import score_meta
from .sources import genius, lrclib, netease, qq, utaten, websearch
from .sources.base import UA, SourceBlocked

SOURCES = [lrclib, netease, qq, utaten, genius, websearch]
_BRACKETS = re.compile(r"\s*(\([^)]*\)|\[[^\]]*\]|（[^）]*）)\s*")


def title_variants(meta: TrackMeta) -> list[str]:
    variants = [meta.title, _BRACKETS.sub(" ", meta.title).strip()]
    if meta.lang == "ja":
        variants.append(reading(variants[-1], "ja"))
    return list(dict.fromkeys(v for v in variants if v))


def search_all(meta: TrackMeta, sources=None, log: Callable[[str], None] | None = None) -> list[Candidate]:
    log = log or (lambda m: print(m, file=sys.stderr))
    out: list[Candidate] = []
    seen: set[tuple[str, str]] = set()
    with httpx.Client(headers={"User-Agent": UA}, timeout=15, follow_redirects=True) as client:
        for src in sources or SOURCES:
            for title in title_variants(meta):
                try:
                    results = src.search(replace(meta, title=title), client)
                except SourceBlocked as e:
                    log(f"{src.name}: blocked ({e})")
                    break
                except Exception as e:  # noqa: BLE001 - one broken source must not stop the search
                    log(f"{src.name}: error {type(e).__name__}: {e}")
                    break
                for r in results:
                    text = clean_lyrics(r.text)
                    if not text or (src.name, text) in seen:
                        continue
                    seen.add((src.name, text))
                    c = Candidate(src.name, text, synced=r.synced, url=r.url)
                    c.score = score_meta(c, meta, r.title, r.artist, r.duration_s)
                    out.append(c)
                if results:
                    break
    out.sort(key=lambda c: c.score, reverse=True)
    return out


if __name__ == "__main__":
    from pathlib import Path

    from ..probe import probe

    m = probe(Path(sys.argv[1]))
    print(m)
    for c in search_all(m):
        print(f"{c.score:.2f} {c.source:10} {'word-synced' if c.synced else ''} {c.url}")
        print("   " + c.text.splitlines()[0][:80])
