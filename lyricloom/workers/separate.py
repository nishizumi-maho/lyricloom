"""Worker: isolates the vocal stem. Payload {audio, out_dir, model, model_dir, device}.
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
    sep = Separator(output_dir=str(out_dir), model_file_dir=p["model_dir"], output_format="WAV",
                    output_single_stem="Vocals", use_directml=False,
                    mdxc_params={"segment_size": 256, "override_model_segment_size": False,
                                 "batch_size": 1, "overlap": p["overlap"], "pitch_shift": 0})
    sep.load_model(model_filename=p["model"])
    files = sep.separate(p["audio"], {"Vocals": "vocals_raw"})
    produced = [out_dir / Path(f).name for f in files]
    emit({"vocals": str(produced[0]), "device": device})


if __name__ == "__main__":
    main()
