from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr

from .. import config
from ..workers import WorkerError, run_worker, windows_path, wsl_path
from .instrumental import find_instrumental, subtract

# FLAC holds integer samples only: 16-bit stems stay 16-bit, anything else is kept as 24-bit.
_INT_DTYPE = {"PCM_16": "int16", "PCM_24": "int32"}


def to_mono16k(src: Path, dst: Path) -> None:
    data, sr = sf.read(str(src), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    sf.write(str(dst), soxr.resample(mono, sr, 16000).astype(np.float32), 16000, subtype="PCM_16")


def kept_vocals_path(audio: Path) -> Path:
    """Where the isolated vocals of `audio` are kept: the library's folder layout under
    config.vocals_root(), as <song>.vocals.flac (outside the library: <artist>/<album>/<song>,
    from the two folders above the song)."""
    try:
        rel = audio.resolve().relative_to(config.library_root().resolve())
    except ValueError:
        rel = Path(audio.parent.parent.name) / audio.parent.name / audio.name
    return config.vocals_root() / rel.with_name(rel.stem + ".vocals.flac")


def _copy_bit_exact(src: Path, dst: Path, fmt: str, **kw) -> None:
    subtype = sf.info(str(src)).subtype
    subtype = subtype if subtype in _INT_DTYPE else "PCM_24"
    data, sr = sf.read(str(src), dtype=_INT_DTYPE[subtype], always_2d=True)
    sf.write(str(dst), data, sr, format=fmt, subtype=subtype, **kw)


def keep_vocals(audio: Path, vocals: Path) -> Path | None:
    """Stores the vocals as FLAC (lossless; compression level 0; the stem's own bit depth) unless
    they are already kept. Returns the kept file, or None when there is nothing to keep."""
    dst = kept_vocals_path(audio)
    if dst.exists():
        return dst
    if not vocals.exists():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    _copy_bit_exact(vocals, tmp, "FLAC", compression_level=0.0)
    tmp.replace(dst)
    return dst


def _run_separator(audio: Path, work: Path) -> tuple[Path, str, str | None]:
    """Runs the separator: in WSL on the GPU when possible, else on Windows. Returns the stem it
    wrote, the device used and, after a failed WSL run, why it failed."""
    payload = {"audio": str(audio), "out_dir": str(work), "model": config.SEPARATOR_MODEL,
               "model_dir": str(config.SEPARATOR_MODEL_DIR), "device": config.SEPARATOR_DEVICE,
               "overlap": config.SEPARATOR_OVERLAP}
    fallback = None
    if config.SEPARATOR_WSL_ENABLED:
        try:
            on_wsl = {**payload, "device": "rocm",
                      **{k: wsl_path(payload[k]) for k in ("audio", "out_dir")}}
            if config.WSL_MODELS_DIR:
                on_wsl["model_dir"] = config.WSL_MODELS_DIR
            else:
                on_wsl["model_dir"] = wsl_path(payload["model_dir"])
            res = run_worker("lyricloom.workers.separate", on_wsl, python=config.SEPARATOR_WSL_PYTHON,
                             wsl=config.SEPARATOR_WSL_DISTRO, wsl_env=config.SEPARATOR_WSL_ENV)
            return windows_path(res["vocals"]), "rocm", None
        except ValueError as e:
            # UNC paths (\\server\share) cannot be bridged to /mnt; use the local CPU path.
            fallback = f"{e}; separating on the CPU instead"
        except (WorkerError, OSError, subprocess.TimeoutExpired) as e:
            fallback = str(e)[-500:]
    res = run_worker("lyricloom.workers.separate", payload, python=config.SEPARATOR_PYTHON)
    return Path(res["vocals"]), res.get("device", config.SEPARATOR_DEVICE), fallback


def separate(audio: Path, work: Path) -> dict:
    """Isolates the vocals of `audio` into work/vocals.wav (and a 16 kHz mono copy), reusing the
    kept vocals when there are some and keeping them otherwise."""
    work.mkdir(parents=True, exist_ok=True)
    vocals = work / "vocals.wav"
    kept = kept_vocals_path(audio)
    out = {"model": config.SEPARATOR_MODEL}
    if kept.exists():
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
        produced, out["device"], fallback = _run_separator(source, work)
        if fallback:
            out["fallback"] = fallback
        produced.replace(vocals)
        keep_vocals(audio, vocals)
    vocals16k = work / "vocals16k.wav"
    to_mono16k(vocals, vocals16k)
    return {**out, "vocals": str(vocals), "vocals16k": str(vocals16k), "kept": str(kept)}
