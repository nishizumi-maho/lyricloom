from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr

from .. import config, models
from ..workers import WorkerError, run_worker, windows_path, wsl_path
from .instrumental import find_instrumental, subtract

# FLAC holds integer samples only: 16-bit stems stay 16-bit, anything else is kept as 24-bit.
_INT_DTYPE = {"PCM_16": "int16", "PCM_24": "int32"}
# Bumped when the kept-stem manifest changes meaning; stale stems are separated again.
KEPT_MANIFEST_VERSION = 1


def to_mono16k(src: Path, dst: Path) -> None:
    data, sr = sf.read(str(src), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    sf.write(str(dst), soxr.resample(mono, sr, 16000).astype(np.float32), 16000, subtype="PCM_16")


def kept_vocals_path(audio: Path) -> Path:
    """Where the isolated vocals of `audio` are kept: the library's folder layout under
    config.vocals_root(), as <song>.vocals.flac.  Songs outside the library live under
    ``_external/<hash of the resolved path>`` so two files with the same two parent folders and
    filename on different drives can never share a stem (R1-12)."""
    try:
        rel = audio.resolve().relative_to(config.library_root().resolve())
    except ValueError:
        import hashlib

        digest = hashlib.sha1(str(audio.resolve()).encode("utf-8")).hexdigest()[:12]
        rel = Path("_external") / digest / audio.name
    return config.vocals_root() / rel.with_name(rel.stem + ".vocals.flac")


def _manifest_path(kept: Path) -> Path:
    return kept.with_name(kept.stem + ".json")


def _audio_stamp(audio: Path) -> tuple[int, int]:
    try:
        st = audio.stat()
        return st.st_size, st.st_mtime_ns
    except OSError:
        return 0, 0


def _expected_manifest(audio: Path, spec: models.ModelSpec, overlap: int) -> dict:
    size, mtime = _audio_stamp(audio)
    return {"version": KEPT_MANIFEST_VERSION, "audio_size": size, "audio_mtime_ns": mtime,
            "model": spec.id, "model_fingerprint": models.fingerprint(spec), "overlap": overlap}


def _read_manifest(kept: Path) -> dict | None:
    try:
        data = json.loads(_manifest_path(kept).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _kept_is_current(audio: Path, kept: Path, spec: models.ModelSpec, overlap: int) -> bool:
    """A kept stem is only reusable when the source audio and the separator model still match."""
    return kept.is_file() and _read_manifest(kept) == _expected_manifest(audio, spec, overlap)


def _write_manifest(audio: Path, kept: Path, spec: models.ModelSpec, overlap: int) -> None:
    manifest = _manifest_path(kept)
    tmp = manifest.with_name(manifest.name + ".tmp")
    tmp.write_text(json.dumps(_expected_manifest(audio, spec, overlap), indent=1),
                   encoding="utf-8")
    os.replace(tmp, manifest)


def _legacy_kept_ok(audio: Path, kept: Path, spec: models.ModelSpec) -> bool:
    """A stem kept by 2.0 has no manifest.  Reuse it only while the file was not created before
    the source audio (so an edited/replaced song is separated again) and the separator is still
    the catalog default; the caller then writes the manifest for next time."""
    if not kept.is_file() or _manifest_path(kept).exists():
        return False
    if not (spec.default and not spec.custom):
        return False
    try:
        return kept.stat().st_mtime >= audio.stat().st_mtime
    except OSError:
        return False


def _reuse_kept(audio: Path, kept: Path, spec: models.ModelSpec, overlap: int) -> bool:
    """True when the kept stem may be used; writes a manifest for a legacy stem on first reuse."""
    if _kept_is_current(audio, kept, spec, overlap):
        return True
    if _legacy_kept_ok(audio, kept, spec):
        _write_manifest(audio, kept, spec, overlap)
        return True
    return False


def _archive_stale(path: Path) -> Path | None:
    if not path.exists():
        return None
    target = path.with_name(path.name + ".stale")
    n = 1
    while target.exists():
        target = path.with_name(f"{path.name}.stale{n}")
        n += 1
    try:
        path.replace(target)
        return target
    except OSError:
        return None


def _copy_bit_exact(src: Path, dst: Path, fmt: str, **kw) -> None:
    subtype = sf.info(str(src)).subtype
    subtype = subtype if subtype in _INT_DTYPE else "PCM_24"
    data, sr = sf.read(str(src), dtype=_INT_DTYPE[subtype], always_2d=True)
    sf.write(str(dst), data, sr, format=fmt, subtype=subtype, **kw)


def keep_vocals(audio: Path, vocals: Path, model: models.ModelSpec | None = None,
                overlap: int | None = None) -> Path | None:
    """Stores the vocals as FLAC (lossless; compression level 0; the stem's own bit depth) and
    writes a small manifest beside it.  A stem is reused only while the source audio's size/mtime
    and the separator model id/hash still match; a stale stem is moved aside (``.stale``), never
    silently used.  Returns the kept file, or None when there is nothing to keep."""
    spec = model or config.resolve_model("separate")
    overlap = config.SEPARATOR_OVERLAP if overlap is None else overlap
    dst = kept_vocals_path(audio)
    if dst.exists():
        if _reuse_kept(audio, dst, spec, overlap):
            return dst
        _archive_stale(dst)
        _archive_stale(_manifest_path(dst))
    if not vocals.exists():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    _copy_bit_exact(vocals, tmp, "FLAC", compression_level=0.0)
    tmp.replace(dst)
    _write_manifest(audio, dst, spec, overlap)
    return dst


def _run_separator(audio: Path, work: Path, spec: models.ModelSpec | None = None,
                   cancel: threading.Event | None = None) -> tuple[Path, str, str | None]:
    """Runs the separator: in WSL on the GPU when possible, else on Windows. Returns the stem it
    wrote, the device used and, after a failed WSL run, why it failed."""
    spec = spec or config.resolve_model("separate")
    model_path = spec.dest(spec.model_file(), config.MODELS)
    payload = {"audio": str(audio), "out_dir": str(work), "model": model_path.name,
               "model_dir": str(model_path.parent), "model_files": [f.filename for f in spec.files],
               "model_sizes": {f.filename: f.size for f in spec.files},
               "device": config.SEPARATOR_DEVICE, "overlap": config.SEPARATOR_OVERLAP}
    fallback = None
    if config.SEPARATOR_WSL_ENABLED:
        try:
            mnt_model_dir = wsl_path(payload["model_dir"])
            candidates = [d for d in (config.WSL_MODELS_DIR, mnt_model_dir) if d]
            on_wsl = {**payload, "device": "rocm",
                      **{k: wsl_path(payload[k]) for k in ("audio", "out_dir")},
                      "model_dir": mnt_model_dir, "model_dir_candidates": candidates}
            res = run_worker("lyricloom.workers.separate", on_wsl, python=config.SEPARATOR_WSL_PYTHON,
                             wsl=config.SEPARATOR_WSL_DISTRO, wsl_env=config.SEPARATOR_WSL_ENV,
                             cancel=cancel)
            return windows_path(res["vocals"]), "rocm", None
        except ValueError as e:
            # UNC paths (\\server\share) cannot be bridged to /mnt; use the local CPU path.
            fallback = f"{e}; separating on the CPU instead"
        except (WorkerError, OSError, subprocess.TimeoutExpired) as e:
            fallback = str(e)[-500:]
    res = run_worker("lyricloom.workers.separate", payload, python=config.SEPARATOR_PYTHON, cancel=cancel)
    return Path(res["vocals"]), res.get("device", config.SEPARATOR_DEVICE), fallback


def separate(audio: Path, work: Path, model: models.ModelSpec | None = None,
             cancel: threading.Event | None = None) -> dict:
    """Isolates the vocals of `audio` into work/vocals.wav (and a 16 kHz mono copy), reusing the
    kept vocals only when their manifest matches the audio and the resolved separator model."""
    work.mkdir(parents=True, exist_ok=True)
    spec = model or config.resolve_model("separate")
    vocals = work / "vocals.wav"
    kept = kept_vocals_path(audio)
    out = {"model": spec.id, "model_id": spec.id,
           "model_fingerprint": models.fingerprint(spec)}
    if _reuse_kept(audio, kept, spec, config.SEPARATOR_OVERLAP):
        _copy_bit_exact(kept, vocals, "WAV")
        out["device"] = "kept"
    else:
        # With the song's instrumental at hand, the separator gets mix - instrumental: it then only
        # has to clean what the subtraction left, and keeps more of the backing vocals and reverb.
        source = audio
        inst = find_instrumental(audio)
        if inst is not None:
            minus = work / "minus_instrumental.wav"
            stats = subtract(audio, inst, minus)
            out["instrumental"] = {"path": str(inst), "used": stats["ok"], "lag": stats["lag"],
                                   "clean_s": stats["clean_s"]}
            if stats["ok"]:
                source = minus
        produced, out["device"], fallback = _run_separator(source, work, spec, cancel)
        if fallback:
            out["fallback"] = fallback
        produced.replace(vocals)
        keep_vocals(audio, vocals, model=spec)
    vocals16k = work / "vocals16k.wav"
    to_mono16k(vocals, vocals16k)
    return {**out, "vocals": str(vocals), "vocals16k": str(vocals16k), "kept": str(kept)}
