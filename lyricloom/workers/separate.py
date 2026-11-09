"""Worker: isolates the vocal stem. Payload {audio, out_dir, model, model_dir, model_files,...}.
device "rocm" runs inside WSL, where audio-separator finds the GPU through torch's CUDA API."""
import os
from pathlib import Path

import torch
from audio_separator.separator import Separator

from . import emit, read_payload


def main() -> None:
    p = read_payload()
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "6")))
    requested = p.get("device", "auto")
    device = "cuda" if requested in ("auto", "cuda", "rocm") and torch.cuda.is_available() else "cpu"
    out_dir = Path(p["out_dir"])
    model_dir = Path(p["model_dir"])
    # Never let audio-separator download on its own: every catalog and custom file must already be
    # in place (the engine's preflight checks it, and `models download` fetched it).
    needed = [model_dir / name for name in (p.get("model_files") or [p["model"]])]
    if not (model_dir / "download_checks.json").is_file():
        needed.append(model_dir / "download_checks.json")
    missing = [str(path) for path in needed if not path.is_file()]
    name = str(p["model"]).lower()
    # Files audio-separator would otherwise fetch on its own when they are absent.
    if name.endswith(".onnx") and not (model_dir / "mdx_model_data.json").is_file():
        missing.append(str(model_dir / "mdx_model_data.json"))
    if name.endswith(".pth") and not (model_dir / "vr_model_data.json").is_file():
        missing.append(str(model_dir / "vr_model_data.json"))
    if name.endswith(".ckpt"):
        stems = [path.with_suffix(s) for path in needed for s in (".yaml", ".yml", ".json")]
        if not any(path.is_file() for path in stems):
            missing.append(str(needed[0].with_suffix(".yaml")))
    if missing:
        raise SystemExit(
            "the separator model is missing: " + ", ".join(missing)
            + ". Run `lyricloom models download <id>` or open Help > Download models.")
    sep = Separator(output_dir=str(out_dir), model_file_dir=str(model_dir), output_format="WAV",
                    output_single_stem="Vocals", use_directml=False,
                    mdxc_params={"segment_size": 256, "override_model_segment_size": False,
                                 "batch_size": 1, "overlap": p["overlap"], "pitch_shift": 0})
    sep.load_model(model_filename=p["model"])
    files = sep.separate(p["audio"], {"Vocals": "vocals_raw"})
    produced = [out_dir / Path(f).name for f in files]
    emit({"vocals": str(produced[0]), "device": device})


if __name__ == "__main__":
    main()
