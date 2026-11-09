"""Worker: download model data without starting the GUI or loading a model into memory.

Kept for compatibility with older callers; all files now go through the verified downloader in
:mod:`lyricloom.downloads` (see :mod:`lyricloom.runtime`).
"""
from __future__ import annotations

from .. import runtime
from . import emit, read_payload


def main() -> None:
    p = read_payload()
    kind = p["kind"]
    if kind == "separator":
        runtime.download_separator()
    elif kind == "mms":
        runtime.download_mms()
    elif kind == "nltk":
        runtime.download_nltk()
    else:
        raise SystemExit(f"unknown download kind: {kind}")
    emit({"ok": True, "kind": kind})


if __name__ == "__main__":
    main()
