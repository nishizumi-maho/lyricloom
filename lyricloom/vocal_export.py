"""Copies of the isolated vocals for the user: ``<song>_vocal.flac``.

LyricLoom keeps every isolated vocal in its own cache (``<song>.vocals.flac`` under the vocals
folder), which is an internal file laid out for the app.  This module writes a second, plain copy
where the user wants it: next to each song, or in a folder of their choice that mirrors the
library's folder layout.  It is off unless the ``vocal_export`` setting says otherwise.

A copy is lossless FLAC in the stem's own bit depth and carries a ``LYRICLOOM`` tag.  That tag is
how an existing file is recognised as ours before it is replaced: a ``<song>_vocal.flac`` the user
made themselves is never overwritten.  No Qt here.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

SUFFIX = "_vocal"
EXTENSION = ".flac"
TAG = "lyricloom"
TAG_VALUE = "isolated vocals"


class ExportRefused(OSError):
    """The destination exists and was not written by LyricLoom, so it was left untouched."""


def export_name(audio: Path) -> str:
    return audio.stem + SUFFIX + EXTENSION


def is_export_name(name: str, sibling_names: Iterable[str], audio_extensions: Iterable[str]) -> bool:
    """True for ``<song>_vocal.flac`` lying next to ``<song>.<audio extension>``.

    The library scanner uses this so an exported vocal is never listed (or processed) as a song.
    A file that merely ends in ``_vocal`` with no song of that name beside it is a normal song.
    ``sibling_names`` are the lower-cased file names of the same folder."""
    lowered = name.lower()
    if not lowered.endswith(SUFFIX + EXTENSION):
        return False
    base = lowered[: -len(SUFFIX + EXTENSION)]
    if not base:
        return False
    siblings = sibling_names if isinstance(sibling_names, (set, frozenset)) else set(sibling_names)
    return any(base + extension in siblings for extension in audio_extensions)


def target(audio: Path, mode: str | None = None, folder: Path | None = None) -> Path | None:
    """Where the copy of ``audio``'s vocals goes under the current (or given) setting; None when
    the export is off or the folder mode has no folder."""
    mode = config.vocal_export_mode() if mode is None else mode
    if mode == "beside":
        return audio.with_name(export_name(audio))
    if mode != "folder":
        return None
    folder = config.vocal_export_folder() if folder is None else folder
    if folder is None:
        return None
    try:
        relative = audio.resolve().relative_to(config.library_root().resolve()).parent
    except (OSError, ValueError):
        relative = Path()        # a song outside the library goes to the top of the folder
    return Path(folder) / relative / export_name(audio)


def is_ours(path: Path) -> bool:
    """Whether ``path`` is a FLAC that LyricLoom exported (it carries the tag)."""
    try:
        from mutagen.flac import FLAC

        return bool(FLAC(str(path)).get(TAG))
    except Exception:  # noqa: BLE001 - unreadable, not FLAC or untagged: not ours
        return False


def _tag(path: Path, audio: Path) -> None:
    """Marks the copy as ours and names it after the song, so a player shows something useful."""
    import mutagen
    from mutagen.flac import FLAC

    flac = FLAC(str(path))
    flac[TAG] = TAG_VALUE
    try:
        source = mutagen.File(str(audio), easy=True)
        tags = source.tags if source is not None and source.tags else {}
    except Exception:  # noqa: BLE001 - the source tags are a nicety
        tags = {}

    def first(key: str) -> str:
        value = tags.get(key) if hasattr(tags, "get") else None
        return str(value[0] if isinstance(value, list) and value else value or "").strip()

    flac["title"] = f"{first('title') or audio.stem} (vocals)"
    for key in ("artist", "album"):
        if first(key):
            flac[key] = first(key)
    flac.save()


def export(audio: Path, vocals: Path, *, destination: Path | None = None,
           fresh: bool = True) -> Path | None:
    """Writes the copy of ``vocals`` for ``audio`` and returns its path.

    Returns None when the export is off (and no ``destination`` was given).  With ``fresh=False``
    an existing copy that is not older than the song is kept as it is.  Raises
    :class:`ExportRefused` rather than replace a file LyricLoom did not write."""
    from .stages.separate import _copy_bit_exact

    dst = destination if destination is not None else target(audio)
    if dst is None:
        return None
    dst = Path(dst)
    if dst.exists():
        if not is_ours(dst):
            raise ExportRefused(
                f"{dst.name} already exists and was not written by LyricLoom, so it was left "
                f"untouched: {dst}")
        try:
            current = dst.stat().st_mtime >= audio.stat().st_mtime
        except OSError:
            current = False
        if not fresh and current:
            return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + ".part")
    try:
        _copy_bit_exact(Path(vocals), part, "FLAC")
        _tag(part, audio)
        os.replace(part, dst)
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    return dst
