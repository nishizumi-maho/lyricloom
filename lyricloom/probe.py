"""Reads track metadata. The audio file is only ever opened for reading."""
from __future__ import annotations

import re
from pathlib import Path

import mutagen

from .model import TrackMeta

_JA = re.compile(r"[぀-ヿ一-鿿]")


def _first(tags, key: str) -> str:
    if not tags or key not in tags:
        return ""
    v = tags[key]
    return str(v[0] if isinstance(v, list) else v).strip()


def probe(audio: Path) -> TrackMeta:
    f = mutagen.File(str(audio), easy=True)
    if f is None:
        raise ValueError(f"unreadable audio: {audio}")
    artist, title = _first(f.tags, "artist"), _first(f.tags, "title") or audio.stem
    lang = "ja" if _JA.search(artist + title) else "other"
    return TrackMeta(audio, artist, title, _first(f.tags, "album"), float(f.info.length), lang)
