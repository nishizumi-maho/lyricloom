"""Entry point for the frozen worker executable (and for ``python -m lyricloom.workers``).

The GUI never imports torch, torchaudio or audio-separator directly; each heavy stage runs in its
own process so VRAM is released when the stage ends. In a PyInstaller build the worker is a
separate console executable; in a source checkout it is ``python -m lyricloom.workers.<name>``.
"""
from __future__ import annotations

import importlib
import sys

WORKERS = ("separate", "align_ctc", "align_mtl", "download")


def run(name: str) -> None:
    if name not in WORKERS:
        raise SystemExit(f"unknown worker: {name}")
    module = importlib.import_module(f"lyricloom.workers.{name}")
    module.main()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: LyricLoomWorker <separate|align_ctc|align_mtl>")
    run(sys.argv[1])


if __name__ == "__main__":
    main()
