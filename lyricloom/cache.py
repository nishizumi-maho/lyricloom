"""Per-track work directory and per-stage JSON cache."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import config


def work_dir(audio: Path) -> Path:
    st = audio.stat()
    key = f"{audio.resolve()}|{st.st_size}|{st.st_mtime_ns}"
    d = config.WORK_ROOT / hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    d.mkdir(parents=True, exist_ok=True)
    return d


def load(audio: Path, stage: str, version: str) -> dict | None:
    p = work_dir(audio) / f"{stage}.json"
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.pop("_version", None) != version:
        return None
    return data


def save(audio: Path, stage: str, version: str, data: dict) -> None:
    p = work_dir(audio) / f"{stage}.json"
    p.write_text(json.dumps({**data, "_version": version}, ensure_ascii=False, indent=1), encoding="utf-8")
