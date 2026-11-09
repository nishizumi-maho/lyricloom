"""Detects scripts that the MMS forced aligner cannot consume.

Latin script is reduced to a-z by ``text.mms`` and Japanese has a real reading (MeCab).  Every
other script produced empty tokens, so the aligner silently returned no words for every line.
This module names the reason instead of pretending the text was aligned (R1-11)."""
from __future__ import annotations

import re

# Ordered most-specific first: Han appears in Japanese text too, but callers pass lang="ja" and
# never ask this module about Japanese.
_SCRIPTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Hangul", re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")),
    ("Han", re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")),
    ("Cyrillic", re.compile(r"[\u0400-\u052f]")),
    ("Greek", re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")),
    ("Thai", re.compile(r"[\u0e00-\u0e7f]")),
    ("Arabic", re.compile(r"[\u0600-\u06ff\u0750-\u077f]")),
    ("Hebrew", re.compile(r"[\u0590-\u05ff]")),
    ("Devanagari", re.compile(r"[\u0900-\u097f]")),
    ("Bengali", re.compile(r"[\u0980-\u09ff]")),
    ("Tamil", re.compile(r"[\u0b80-\u0bff]")),
    ("Telugu", re.compile(r"[\u0c00-\u0c7f]")),
    ("Kannada", re.compile(r"[\u0c80-\u0cff]")),
    ("Malayalam", re.compile(r"[\u0d00-\u0d7f]")),
    ("Sinhala", re.compile(r"[\u0d80-\u0dff]")),
    ("Myanmar", re.compile(r"[\u1000-\u109f]")),
    ("Georgian", re.compile(r"[\u10a0-\u10ff]")),
    ("Armenian", re.compile(r"[\u0530-\u058f]")),
)

_LANG_NAMES = {
    "zh": "Chinese", "ko": "Korean", "ru": "Russian", "th": "Thai", "el": "Greek",
    "ar": "Arabic", "he": "Hebrew", "hi": "Hindi", "ja": "Japanese", "en": "English",
    "pt": "Portuguese",
}


def detect(text: str) -> str | None:
    """The first unsupported script name in ``text``, or None for Latin/Japanese-compatible text."""
    for name, pattern in _SCRIPTS:
        if pattern.search(text):
            return name
    return None


def unsupported_reason(text: str, lang: str | None = None) -> str | None:
    """A human-readable reason why ``text`` cannot be word-aligned, or None when it can."""
    if lang == "ja":
        return None
    script = detect(text)
    if script is None:
        return None
    language = _LANG_NAMES.get(lang or "")
    return f"{language} ({script})" if language else script
