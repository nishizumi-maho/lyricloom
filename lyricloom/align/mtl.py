"""English word alignment with LyricsAlignment-MTL, a model trained on sung vocals (DALI).
It runs on the GPU in the Windows CUDA runtime or through ROCm in WSL (its own copy of the repo),
falling back to the bundled CPU worker when the GPU run fails."""
from __future__ import annotations

import logging
import re
import subprocess
import threading
from pathlib import Path

from .. import config, gpu_runtime
from ..errtext import message_text
from ..model import Segment
from ..workers import WorkerError, run_worker, wsl_path

log = logging.getLogger(__name__)


def word_key(segment: str) -> str | None:
    """The word the model sees for one of our segments (lowercase letters and apostrophes),
    or None when the segment has no letters (punctuation, dashes, digits)."""
    key = re.sub(r"[^a-z']", "", segment.lower()).strip("'")
    return key if re.search(r"[a-z]", key) else None


def map_words(seg_texts: list[list[str]], words: list[list]) -> list[list[Segment | None]]:
    """words = [[word, start_ms, end_ms], ...] in lyric order, one per segment with a word_key."""
    keyed = sum(word_key(s) is not None for line in seg_texts for s in line)
    if keyed != len(words):
        raise ValueError(f"singing model returned {len(words)} words for {keyed}")
    it = iter(words)
    out = []
    for line in seg_texts:
        row = []
        for s in line:
            if word_key(s) is None:
                row.append(None)
            else:
                _, start, end = next(it)
                row.append(Segment("", int(start), int(end), 1.0))
        out.append(row)
    return out


def align_lines_mtl(vocals: Path, seg_texts: list[list[str]],
                    cancel: threading.Event | None = None) -> list[list[Segment | None]]:
    lines = [" ".join(k for k in map(word_key, line) if k) for line in seg_texts]
    spec = config.resolve_model("singing", "en")
    checkpoint = spec.dest(spec.model_file(), config.MODELS)
    payload = {"wav": str(vocals), "lines": lines, "repo": str(config.MTL_REPO),
               "checkpoint_dir": str(checkpoint.parent.parent),
               "checkpoint_size": spec.size,
               "nltk_dir": str(config.MODELS / "nltk")}
    runtime = config.gpu_runtime()
    if runtime is not None and runtime[0] == "cuda":
        try:
            res = run_worker("lyricloom.workers.align_mtl", {**payload, "cuda": True},
                             python=gpu_runtime.worker_python(runtime[1]),
                             extra_env=gpu_runtime.worker_env(), cancel=cancel)
            return map_words(seg_texts, res["words"])
        except (WorkerError, OSError, subprocess.TimeoutExpired) as e:
            log.warning("singing model on the Windows GPU runtime failed, using the CPU: %s",
                        message_text(e)[-300:])
    elif config.MTL_WSL_ENABLED:
        try:
            mnt_checkpoint_dir = wsl_path(payload["checkpoint_dir"])
            candidates = [d for d in (config.MTL_WSL_CHECKPOINT, mnt_checkpoint_dir) if d]
            on_wsl = {**payload, "cuda": True, "wav": wsl_path(payload["wav"]),
                      "repo": config.MTL_WSL_REPO, "checkpoint_dir": mnt_checkpoint_dir,
                      "checkpoint_dirs": candidates,
                      "nltk_dir": wsl_path(payload["nltk_dir"])}
            res = run_worker("lyricloom.workers.align_mtl", on_wsl, python=config.ALIGN_WSL_PYTHON,
                             wsl=config.ALIGN_WSL_DISTRO, wsl_env=config.MTL_WSL_ENV, cancel=cancel)
            return map_words(seg_texts, res["words"])
        except ValueError as e:
            log.warning("UNC path cannot be bridged to WSL (%s); aligning on the CPU instead", e)
        except (WorkerError, OSError, subprocess.TimeoutExpired) as e:
            log.warning("singing model in WSL failed, using .venv-mtl on the CPU: %s", str(e)[-300:])
    res = run_worker("lyricloom.workers.align_mtl", payload, python=str(config.MTL_PYTHON), cancel=cancel)
    return map_words(seg_texts, res["words"])
