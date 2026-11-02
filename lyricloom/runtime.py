"""Downloads of the optional large models and the small NLTK data used by the singing model.

The app never downloads anything silently: the Models dialog (or ``lyricloom models``) lists what is
missing and starts only the downloads the user asks for. Files are written to a ``.part`` file and
moved into place only after their size/checksum is verified.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Callable

import httpx

from . import config
from .workers import run_worker

Progress = Callable[[int, int], None]  # bytes done, bytes total (total may be 0)

WHISPER_REPO = "ggerganov/whisper.cpp"
WHISPER_NAME = "ggml-large-v3.bin"
WHISPER_SHA256 = "64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2"
MTL_URL = "https://github.com/jhuang448/LyricsAlignment-MTL/raw/main/checkpoints/checkpoint_MTL"
MTL_SHA256 = "826559e7e810bf8f90223d8fd5c66525c01ad4dd9cdc19d019f39f784e7ed3c1"
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


def _download(url: str, dest: Path, progress: Progress | None = None, expected: str | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    if expected and sha256(tmp).lower() != expected.lower():
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"checksum mismatch for {dest.name}")
    tmp.replace(dest)
    return dest


def whisper_expected_sha256() -> str:
    """The checksum Hugging Face publishes for the model (large-v3 can be updated rarely)."""
    try:
        tree = httpx.get(f"https://huggingface.co/api/models/{WHISPER_REPO}/tree/main", timeout=30).json()
        return next(f["lfs"]["oid"] for f in tree if f["path"] == WHISPER_NAME)
    except Exception:  # noqa: BLE001 - fall back to the checksum pinned above
        return WHISPER_SHA256


def whisper_status() -> bool:
    return config.WHISPER_MODEL.is_file() and config.WHISPER_MODEL.stat().st_size > 1_000_000_000


def separator_status() -> bool:
    return (config.SEPARATOR_MODEL_DIR / config.SEPARATOR_MODEL).is_file()


def mtl_status() -> bool:
    return config.MTL_CHECKPOINT.is_file() and config.MTL_CHECKPOINT.stat().st_size > MTL_MIN_BYTES


def mms_status() -> bool:
    # torchaudio stores the checkpoint under TORCH_HOME/hub/checkpoints. The exact filename is
    # owned by torchaudio; a directory with any checkpoint is a useful heuristic for the UI.
    root = config.MODELS / "torch" / "hub" / "checkpoints"
    return root.is_dir() and any(p.suffix.lower() in (".pth", ".pt") for p in root.iterdir())


def status() -> dict[str, bool]:
    return {"whisper": whisper_status(), "separator": separator_status(),
            "mtl": mtl_status(), "mms": mms_status()}


def download_whisper(progress: Progress | None = None) -> Path:
    want = whisper_expected_sha256()
    dest = config.WHISPER_MODEL
    if dest.is_file() and sha256(dest) == want:
        if progress:
            progress(1, 1)
        return dest
    return _download(f"https://huggingface.co/{WHISPER_REPO}/resolve/main/{WHISPER_NAME}",
                     dest, progress, want)


def download_mtl(progress: Progress | None = None) -> Path:
    if mtl_status():
        if progress:
            progress(1, 1)
        return config.MTL_CHECKPOINT
    return _download(MTL_URL, config.MTL_CHECKPOINT, progress, MTL_SHA256)


def download_separator() -> None:
    """audio-separator knows the URL and checksum of its own model registry."""
    run_worker("lyricloom.workers.download", {"kind": "separator"}, timeout_s=3600)


def download_mms() -> None:
    run_worker("lyricloom.workers.download", {"kind": "mms"}, timeout_s=3600)


def download_nltk() -> None:
    run_worker("lyricloom.workers.download", {"kind": "nltk"}, timeout_s=600)


def download_all(progress: Progress | None = None) -> None:
    download_whisper(progress)
    download_separator()
    download_mms()
    download_mtl(progress)
    download_nltk()


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
    try:
        import nltk

        def has(path: str) -> bool:
            try:
                nltk.data.find(path)
                return True
            except LookupError:
                return False

        return has("corpora/cmudict") and (
            has("taggers/averaged_perceptron_tagger") or has("taggers/averaged_perceptron_tagger_eng"))
    except Exception:  # noqa: BLE001
        return False
