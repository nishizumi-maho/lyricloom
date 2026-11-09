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


def load(audio: Path, stage: str, version: str, inputs: dict | None = None,
         legacy_ok: bool = False) -> dict | None:
    """Loads a cached stage.  When ``inputs`` is given, a cache written for a different model or
    parameter set is treated as absent (the caller recomputes that stage and the ones after it).

    ``legacy_ok`` accepts a cache written before stage fingerprints existed (2.0 wrote no
    ``_inputs`` key) and immediately rewrites it with the current fingerprint, so it is only used
    when the caller has established that the resolved models are the catalog defaults.  A cache
    with a *different* fingerprint is still rejected."""
    p = work_dir(audio) / f"{stage}.json"
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.pop("_version", None) != version:
        return None
    stored = data.pop("_inputs", None)
    if inputs is not None and stored != inputs:
        if not (legacy_ok and stored is None):
            return None
        save(audio, stage, version, data, inputs=inputs)
    return data


def save(audio: Path, stage: str, version: str, data: dict, inputs: dict | None = None) -> None:
    p = work_dir(audio) / f"{stage}.json"
    payload = {**data, "_version": version}
    if inputs is not None:
        payload["_inputs"] = inputs
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
