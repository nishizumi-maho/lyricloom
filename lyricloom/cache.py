"""Per-track work directory, per-stage JSON cache, the per-track lock and cache cleanup."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

from . import config

LOCK_NAME = "lock"


def work_dir(audio: Path) -> Path:
    st = audio.stat()
    key = f"{audio.resolve()}|{st.st_size}|{st.st_mtime_ns}"
    d = config.WORK_ROOT / hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.utime(d, None)   # most recently used, for cache.prune's oldest-first order
    except OSError:
        pass
    return d


# --------------------------------------------------------------------------- stage JSON


def _discard_corrupt(path: Path) -> None:
    """Moves a corrupt cache aside so it is never read again.  The caller recomputes the stage."""
    target = path.with_name(path.name + ".corrupt")
    n = 1
    while target.exists():
        target = path.with_name(f"{path.name}.corrupt{n}")
        n += 1
    try:
        os.replace(path, target)
    except OSError:
        pass


def load(audio: Path, stage: str, version: str, inputs: dict | None = None,
         legacy_ok: bool = False) -> dict | None:
    """Loads a cached stage.  When ``inputs`` is given, a cache written for a different model or
    parameter set is treated as absent (the caller recomputes that stage and the ones after it).

    A truncated, corrupt or non-object JSON file is discarded (renamed ``*.corrupt``) and treated
    as absent, so ``force`` and a normal run both recover it (R1-14).

    ``legacy_ok`` accepts a cache written before stage fingerprints existed (2.0 wrote no
    ``_inputs`` key) and immediately rewrites it with the current fingerprint, so it is only used
    when the caller has established that the resolved models are the catalog defaults.  A cache
    with a *different* fingerprint is still rejected."""
    p = work_dir(audio) / f"{stage}.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        _discard_corrupt(p)
        return None
    if not isinstance(data, dict):
        _discard_corrupt(p)
        return None
    if data.pop("_version", None) != version:
        return None
    stored = data.pop("_inputs", None)
    if inputs is not None and stored != inputs:
        if not (legacy_ok and stored is None):
            return None
        save(audio, stage, version, data, inputs=inputs)
    return data


def save(audio: Path, stage: str, version: str, data: dict, inputs: dict | None = None) -> None:
    """Writes the cache atomically: a crash leaves the previous file, never a truncated one."""
    p = work_dir(audio) / f"{stage}.json"
    payload = {**data, "_version": version}
    if inputs is not None:
        payload["_inputs"] = inputs
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def clear(audio: Path, stage: str | None = None) -> int:
    """Deletes one stage cache (or every stage cache) for a track.  Returns the number removed."""
    d = work_dir(audio)
    removed = 0
    paths = [d / f"{stage}.json"] if stage else list(d.glob("*.json"))
    for p in paths:
        try:
            p.unlink()
            removed += 1
        except FileNotFoundError:
            pass
    return removed


# --------------------------------------------------------------------------- per-track lock


class TrackLock:
    """An exclusive lock file in a track's work directory, released by the process that owns it."""

    def __init__(self, path: Path):
        self.path = path

    def release(self) -> None:
        data = _read_lock(self.path)
        if data is None or data.get("pid") == os.getpid():
            try:
                self.path.unlink()
            except OSError:
                pass

    def __enter__(self) -> "TrackLock":
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def _read_lock(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, int(pid))
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259   # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_is_stale(path: Path) -> bool:
    """A lock without a live owner process is stale.  Missing/unreadable locks count as stale."""
    data = _read_lock(path)
    if data is None:
        return True
    pid = data.get("pid")
    if not isinstance(pid, int):
        return True
    if pid == os.getpid():
        return False
    return not _pid_alive(pid)


def acquire(audio: Path) -> TrackLock | None:
    """Takes the track lock, or returns None when another live run holds it.

    The lock file stores the process id and start time.  A lock left behind by a dead process is
    removed and retried, so a crash never blocks a track forever (R1-15)."""
    d = work_dir(audio)
    path = d / LOCK_NAME
    for _ in range(3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if not lock_is_stale(path):
                return None
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                return None
            continue
        except OSError:
            return None
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps({"pid": os.getpid(), "started": time.time()}))
        return TrackLock(path)
    return None


# --------------------------------------------------------------------------- size and cleanup


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def size_report(root: Path | None = None) -> dict:
    """Bytes and track folders in the work cache (the GUI/CLI can show it before cleaning)."""
    root = Path(root or config.WORK_ROOT)
    dirs = [p for p in root.iterdir() if p.is_dir()] if root.is_dir() else []
    sizes = [(p, _dir_size(p)) for p in dirs]
    return {"root": str(root), "files": len(dirs), "bytes": sum(n for _, n in sizes)}


def _active(directory: Path) -> bool:
    lock = directory / LOCK_NAME
    return lock.exists() and not lock_is_stale(lock)


def prune(max_bytes: int, keep: Path | None = None, root: Path | None = None) -> dict:
    """Deletes the oldest track work folders until the cache is at most ``max_bytes``.

    ``keep`` is the running track's folder and is never removed.  Folders whose lock belongs to a
    live process are also left alone.  A negative or zero limit removes every eligible folder."""
    root = Path(root or config.WORK_ROOT)
    keep = keep.resolve() if keep is not None else None
    dirs = [p for p in root.iterdir() if p.is_dir()] if root.is_dir() else []
    total = sum(_dir_size(p) for p in dirs)
    freed = 0
    removed = 0
    for directory in sorted(dirs, key=lambda p: _mtime(p)):
        if total - freed <= max(0, max_bytes):
            break
        if keep is not None and directory.resolve() == keep:
            continue
        if _active(directory):
            continue
        size = _dir_size(directory)
        try:
            shutil.rmtree(directory)
        except OSError:
            continue
        freed += size
        removed += 1
    return {"removed": removed, "freed": freed, "remaining": max(0, total - freed)}


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
