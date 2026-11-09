"""Reads track metadata. The audio file is only ever opened for reading."""
from __future__ import annotations

import re
from pathlib import Path

import mutagen

from .model import TrackMeta

# Japanese needs kana.  Han characters alone are just as much Chinese as Japanese, so a Chinese
# title such as 孤勇者 must not force Japanese transcription and romaji sidecars (R1-03).
_KANA = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")

# Common spellings accepted from a language tag or the app/CLI override.
_LANG_ALIASES = {
    "japanese": "ja", "日本語": "ja",
    "chinese": "zh", "mandarin": "zh", "中文": "zh", "汉语": "zh", "漢語": "zh",
    "korean": "ko", "한국어": "ko",
    "english": "en", "portuguese": "pt", "português": "pt",
    "russian": "ru", "thai": "th", "greek": "el", "arabic": "ar", "hebrew": "he",
    "hindi": "hi", "spanish": "es", "french": "fr", "german": "de", "italian": "it",
}


def normalize_lang(value: str | None) -> str:
    """A lower-case language code; common language names are mapped to their ISO code.

    Anything unknown is passed through lower-case so an explicit override still reaches
    whisper-cli (which knows more languages than this table)."""
    text = (value or "").strip().lower().replace("_", "-")
    if not text:
        return ""
    if text in _LANG_ALIASES:
        return _LANG_ALIASES[text]
    return text.split("-", 1)[0]


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
    explicit = normalize_lang(_first(f.tags, "language") or _first(f.tags, "lang"))
    if explicit:
        lang = explicit
    else:
        lang = "ja" if _KANA.search(artist + title) else "other"
    return TrackMeta(audio, artist, title, _first(f.tags, "album"), float(f.info.length), lang)
