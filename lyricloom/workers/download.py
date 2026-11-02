"""Worker: download model data without starting the GUI or loading a model into memory."""
from __future__ import annotations

import os

from .. import config
from . import emit, read_payload


def main() -> None:
    p = read_payload()
    kind = p["kind"]
    if kind == "separator":
        from audio_separator.separator import Separator

        config.SEPARATOR_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        sep = Separator(model_file_dir=str(config.SEPARATOR_MODEL_DIR))
        sep.download_model_and_data(config.SEPARATOR_MODEL)
    elif kind == "mms":
        os.environ.setdefault("TORCH_HOME", str(config.MODELS / "torch"))
        import torchaudio

        torchaudio.pipelines.MMS_FA.get_model(with_star=False)
    elif kind == "nltk":
        import nltk

        for package in ("cmudict", "averaged_perceptron_tagger", "averaged_perceptron_tagger_eng",
                        "punkt", "punkt_tab"):
            try:
                nltk.download(package, quiet=True)
            except Exception:  # noqa: BLE001 - older NLTK versions do not have every package
                pass
    else:
        raise SystemExit(f"unknown download kind: {kind}")
    emit({"ok": True, "kind": kind})


if __name__ == "__main__":
    main()
