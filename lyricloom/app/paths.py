"""Validation shared by the command line, the single-instance channel and drag-and-drop.

Only existing files with an audio extension LyricLoom supports are accepted. Folders are expanded
recursively because dropping an album folder is a natural way to queue several songs.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .. import runner
from ..errtext import message_text


def _audio(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in runner.AUDIO_EXT


def validate_audio_file(item: str | Path) -> tuple[Path | None, str | None]:
    """One existing audio file, for options that take exactly one file (``--open``)."""
    try:
        path = Path(item).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        return None, f"{item}: {message_text(exc)}"
    if not path.exists():
        return None, f"{path}: does not exist"
    if not path.is_file():
        return None, f"{path}: not a file"
    if not _audio(path):
        return None, f"{path}: unsupported audio format ({path.suffix or 'no extension'})"
    return path, None


def expand_audio_paths(items: Iterable[str | Path]) -> tuple[list[Path], list[str]]:
    """Returns (accepted files, human-readable rejection reasons), de-duplicated and ordered."""
    accepted: list[Path] = []
    rejected: list[str] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError) as exc:
            rejected.append(f"{path}: {message_text(exc)}")
            return
        if resolved not in seen:
            seen.add(resolved)
            accepted.append(resolved)

    for item in items:
        try:
            path = Path(item).expanduser().resolve()
        except (OSError, RuntimeError) as exc:
            rejected.append(f"{item}: {message_text(exc)}")
            continue
        if path.is_dir():
            found = runner.find_audio(path)
            if not found:
                rejected.append(f"{path}: no supported audio files in this folder")
            for audio in found:
                add(audio)
            continue
        if not path.exists():
            rejected.append(f"{path}: does not exist")
        elif not path.is_file():
            rejected.append(f"{path}: not a file")
        elif not _audio(path):
            rejected.append(f"{path}: unsupported audio format ({path.suffix or 'no extension'})")
        else:
            add(path)
    return accepted, rejected
