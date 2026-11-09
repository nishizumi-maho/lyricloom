from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from .. import config, models
from ..model import Segment
from ..workers import WorkerError, run_worker, wsl_path
from .anchors import Block

log = logging.getLogger(__name__)


def _segments(blocks: list[Block], res: dict) -> list[list[Segment | None]]:
    out: list[list[Segment | None]] = []
    for b, rb in zip(blocks, res["blocks"]):
        for line in rb["lines"]:
            out.append([None if s is None else
                        Segment("", b.start_ms + s["start_ms"], b.start_ms + s["end_ms"], s["score"])
                        for s in line["segments"]])
    return out


def align_blocks(vocals16k: Path, blocks: list[Block], seg_tokens: list[list[list[str]]]
                 ) -> list[list[Segment | None]]:
    """seg_tokens[k][l] = MMS token strings of each segment of line l in block k.
    Returns, per lyric line in order, one Segment (absolute ms) or None per segment.
    Runs on the GPU through ROCm in WSL when it is available, else on the CPU."""
    # R3-27: point torch at our own cache unconditionally; a user-set TORCH_HOME must not make the
    # status check and the aligner disagree about where the checkpoint is.
    torch_home = config.MODELS / "torch"
    os.environ["TORCH_HOME"] = str(torch_home)
    spec = config.resolve_model("align", config.active_language())
    model_path = spec.dest(spec.model_file(), config.MODELS)
    payload = {"wav": str(vocals16k), "device": config.ALIGN_DEVICE, "blocks": [
        {"start_ms": b.start_ms, "end_ms": b.end_ms, "lines": lines} for b, lines in zip(blocks, seg_tokens)],
        "model_path": str(model_path), "torch_home": str(torch_home)}
    if config.ALIGN_WSL_ENABLED:
        on_wsl = {**payload, "device": "cuda", "wav": wsl_path(payload["wav"]),
                  "model_path": wsl_path(payload["model_path"]),
                  "torch_home": str(config.ALIGN_WSL_ENV.get("TORCH_HOME", torch_home))}
        try:
            res = run_worker("lyricloom.workers.align_ctc", on_wsl, python=config.ALIGN_WSL_PYTHON,
                             wsl=config.ALIGN_WSL_DISTRO, wsl_env=config.ALIGN_WSL_ENV)
            return _segments(blocks, res)
        except (WorkerError, OSError, subprocess.TimeoutExpired) as e:
            log.warning("alignment in WSL failed, aligning on the CPU instead: %s", str(e)[-300:])
    return _segments(blocks, run_worker("lyricloom.workers.align_ctc", payload))
