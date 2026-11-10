"""Picking a model copy from the paths the engine sends in a worker payload.

A WSL setup helper copies the big files into the distro so the worker can load them from its own
filesystem instead of reading them through the slow ``/mnt`` bridge on every song.  The engine
sends the inside-the-distro candidate first and the ``/mnt`` path last; the worker uses the first
candidate that exists with the size the catalog recorded, and falls back to the last path when no
copy can be confirmed.
"""
from __future__ import annotations

from pathlib import Path


def _matches(path: Path, expected: int) -> bool:
    try:
        st = path.stat()
    except OSError:
        return False
    return not expected or st.st_size == expected


def first_file(candidates, expected: int = 0, fallback=None) -> Path:
    """The first candidate file that exists with ``expected`` bytes (0 accepts any size)."""
    paths = [Path(c) for c in (candidates or [])]
    for path in paths:
        if _matches(path, expected):
            return path
    if fallback is not None:
        return Path(fallback)
    return paths[-1] if paths else Path()


def first_checkpoint_dir(candidates, expected: int = 0, fallback=None,
                         filename: str = "checkpoint_MTL") -> Path:
    """The first directory whose ``checkpoints/<filename>`` is present with ``expected`` bytes."""
    dirs = [Path(c) for c in (candidates or [])]
    for directory in dirs:
        if _matches(directory / "checkpoints" / filename, expected):
            return directory
    if fallback is not None:
        return Path(fallback)
    return dirs[-1] if dirs else Path()


def first_model_dir(candidates, required: list[str], sizes: dict | None = None,
                    fallback=None) -> Path:
    """The first directory holding every required file with its expected size."""
    sizes = sizes or {}
    dirs = [Path(c) for c in (candidates or [])]
    for directory in dirs:
        if all(_matches(directory / name, int(sizes.get(name) or 0)) for name in required):
            return directory
    if fallback is not None:
        return Path(fallback)
    return dirs[-1] if dirs else Path()
