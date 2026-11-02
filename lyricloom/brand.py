"""Brand markers written into .lrc files and recognised on later runs.

The project was previously called Lyrics Boca. Files produced by that version must keep working
after the rename, so every "is this ours?" check accepts both markers.
"""
from __future__ import annotations

BRAND = "LyricLoom"
LEGACY = ("LYRICS BOCA", "LyricsBoca")
PREFIXES = (BRAND, *LEGACY)


def is_ours(value: str | None) -> bool:
    return bool(value) and str(value).startswith(PREFIXES)


def tag(version: str) -> str:
    return f"{BRAND} {version}"
