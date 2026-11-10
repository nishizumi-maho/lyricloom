"""Downloads of the optional large models and the small NLTK data used by the singing model.

The engine never downloads anything while processing a song: the Models dialog (or ``lyricloom
models download``) lists what is missing and starts only the downloads the user asks for.  Every
file goes through :func:`lyricloom.downloads.download_verified`: HTTPS only, a resumable ``.part``
file, and an exact size + SHA-256 check before the atomic move.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Callable

from . import config, models
from .downloads import DownloadCancelled, DownloadError, ChecksumMismatch

Progress = Callable[[int, int], None]  # bytes done, bytes total (total may be 0)

# Compatibility names for code that imported the old constants from this module.
WHISPER_REPO = "ggerganov/whisper.cpp"
WHISPER_NAME = "ggml-large-v3.bin"
WHISPER_SHA256 = models.get("whisper-large-v3").sha256
MTL_URL = models.get("singing-mtl").url
MTL_SHA256 = models.get("singing-mtl").sha256
MTL_MIN_BYTES = 60_000_000

NLTK_PACKAGES = {"cmudict": "corpora/cmudict",
                 "averaged_perceptron_tagger": "taggers/averaged_perceptron_tagger",
                 "averaged_perceptron_tagger_eng": "taggers/averaged_perceptron_tagger_eng",
                 "punkt": "tokenizers/punkt",
                 "punkt_tab": "tokenizers/punkt_tab"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _status(stage: str) -> str:
    return models.status(config.resolve_model(stage))


def _available(stage: str) -> bool:
    """A model that processing may use: a verified file or one whose pinned size matches and that
    has no sidecar yet (FR-A-07)."""
    return _status(stage) in ("ready", "unverified")


def whisper_status() -> bool:
    return _available("transcribe")


def separator_status() -> bool:
    return _available("separate")


def mtl_status() -> bool:
    return _available("singing")


def mms_status() -> bool:
    return _available("align")


def status() -> dict[str, bool]:
    return {"whisper": whisper_status(), "separator": separator_status(),
            "mtl": mtl_status(), "mms": mms_status()}


def download_spec(spec: models.ModelSpec, progress: Progress | None = None,
                  cancel=None) -> list[Path]:
    return models.download(spec, progress=progress, cancel=cancel)


def repair(spec: models.ModelSpec, progress: Progress | None = None, cancel=None) -> list[Path]:
    return models.repair(spec, progress=progress, cancel=cancel)


def download_model(model_id: str, progress: Progress | None = None, cancel=None) -> list[Path]:
    spec = models.find(model_id)
    if spec is None:
        raise ValueError(f"unknown model {model_id!r}; use `lyricloom models list`")
    return download_spec(spec, progress=progress, cancel=cancel)


def _download_for(stage: str, model_id: str | None) -> models.ModelSpec:
    """The selected model for ``stage``; an unknown explicit id is an error, never a silent
    fallback to the default (FR-A-09)."""
    if not model_id:
        return config.resolve_model(stage)
    spec = models.find(model_id)
    if spec is None:
        raise ValueError(f"unknown model {model_id!r}; use `lyricloom models list`")
    return spec


def download_whisper(progress: Progress | None = None, model_id: str | None = None) -> Path:
    return download_spec(_download_for("transcribe", model_id), progress=progress)[0]


def download_separator(progress: Progress | None = None, model_id: str | None = None) -> Path:
    return download_spec(_download_for("separate", model_id), progress=progress)[0]


def download_mms(progress: Progress | None = None, model_id: str | None = None) -> Path:
    return download_spec(_download_for("align", model_id), progress=progress)[0]


def download_mtl(progress: Progress | None = None, model_id: str | None = None) -> Path:
    return download_spec(_download_for("singing", model_id), progress=progress)[0]


def download_nltk(progress: Progress | None = None) -> list[Path]:
    return download_spec(models.get("singing-nltk-data"), progress=progress)


def download_all(progress: Progress | None = None, cancel=None) -> dict[str, str]:
    """Downloads every default model.  One failure does not stop the remaining downloads (R3-28).

    Returns ``{model_id: "ready" | "error: ..."}`` so the caller can show a per-model summary.
    """
    results: dict[str, str] = {}
    for spec in models.default_models():
        try:
            download_spec(spec, progress=progress, cancel=cancel)
            results[spec.id] = "ready"
        except DownloadCancelled:
            results[spec.id] = "cancelled"
            break
        except (DownloadError, ChecksumMismatch, OSError, RuntimeError) as exc:
            results[spec.id] = f"error: {exc}"
    return results


def model_status(model_id: str, verify: bool = False) -> str:
    spec = models.find(model_id)
    if spec is None:
        raise ValueError(f"unknown model {model_id!r}; use `lyricloom models list`")
    return models.verify(spec) if verify else models.status(spec)


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def check_ffmpeg() -> bool:
    try:
        import imageio_ffmpeg

        return Path(imageio_ffmpeg.get_ffmpeg_exe()).is_file()
    except Exception:  # noqa: BLE001
        return shutil.which("ffmpeg") is not None


def _nltk_ready() -> bool:
    return models.nltk_ready()
