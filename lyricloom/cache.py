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


def load(audio: Path, stage: str, version: str, inputs: dict | None = None) -> dict | None:
    """Loads a cached stage.  When ``inputs`` is given, a cache written for a different model or
    parameter set is treated as absent (the caller recomputes that stage and the ones after it)."""
    p = work_dir(audio) / f"{stage}.json"
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.pop("_version", None) != version:
        return None
    stored = data.pop("_inputs", None)
    if inputs is not None and stored != inputs:
        return None
    return data


def save(audio: Path, stage: str, version: str, data: dict, inputs: dict | None = None) -> None:
    p = work_dir(audio) / f"{stage}.json"
    payload = {**data, "_version": version}
    if inputs is not None:
        payload["_inputs"] = inputs
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
