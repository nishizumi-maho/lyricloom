"""Worker (runs in .venv-mtl on Windows, or in the WSL venv with cuda=True):
LyricsAlignment-MTL on the full-rate vocals.
Payload {wav, lines: [already-normalized words joined by spaces], repo, cuda?};
result {words: [[word, start_ms, end_ms]]}."""
import os
import sys
import tempfile

import numpy as np

if not hasattr(np, "Inf"):   # the model's utils.py predates NumPy 2, which dropped the alias
    np.Inf = np.inf

from . import emit, read_payload
from .copies import first_checkpoint_dir

# The model's frames are 3 x 256 samples at 22050 Hz.
FRAME_S = 256 / 22050 * 3


def main() -> None:
    p = read_payload()
    # The corpora are a pinned catalog model downloaded by the app; never fetch them here.
    nltk_dir = p.get("nltk_dir")
    if nltk_dir:
        os.environ["NLTK_DATA"] = str(nltk_dir) + os.pathsep + os.environ.get("NLTK_DATA", "")
    # checkpoints are loaded by relative path; prefer the copy inside the distro over /mnt
    checkpoint_dir = first_checkpoint_dir(p.get("checkpoint_dirs"),
                                          int(p.get("checkpoint_size") or 0),
                                          p["checkpoint_dir"])
    os.chdir(checkpoint_dir)
    # PyInstaller's frozen modules have no source file, and inflect (through g2p_en) decorates
    # functions with typeguard, which calls inspect.getsource() and fails in a frozen build.
    # Timing is unaffected; skip the runtime type-check instrumentation.
    try:
        import typeguard

        def _no_typecheck(func=None, **kwargs):
            return func if func is not None else (lambda f: f)

        typeguard.typechecked = _no_typecheck
    except Exception:  # noqa: BLE001 - typeguard is optional
        pass
    sys.path.insert(0, p["repo"])
    if getattr(sys, "frozen", False):
        # A frozen sys.path does not always pick up external source directories. Load the three
        # files directly, in dependency order, and register them for wrapper's absolute imports.
        import importlib.util
        from pathlib import Path

        repo = Path(p["repo"])
        for name in ("utils", "model", "wrapper"):
            spec = importlib.util.spec_from_file_location(name, repo / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        import wrapper
    else:
        import wrapper

    with tempfile.TemporaryDirectory() as tmp:
        lyrics = os.path.join(tmp, "lyrics.txt")
        with open(lyrics, "w", encoding="utf-8") as f:
            f.write("\n".join(l for l in p["lines"] if l))
        audio, words, lyrics_p, idx_word_p, idx_line_p = wrapper.preprocess_from_file(p["wav"], lyrics)
    word_align, _ = wrapper.align(audio, words, lyrics_p, idx_word_p, idx_line_p, method="MTL",
                                  cuda=bool(p.get("cuda")))
    emit({"words": [[w, int(a[0] * FRAME_S * 1000), int(a[1] * FRAME_S * 1000)] for w, a in zip(words, word_align)]})


if __name__ == "__main__":
    main()
