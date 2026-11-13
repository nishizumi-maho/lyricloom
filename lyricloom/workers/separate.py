"""Worker: isolates the vocal stem. Payload {audio, out_dir, model, model_dir, model_files,...}.
device "rocm" runs inside WSL, where audio-separator finds the GPU through torch's CUDA API;
"directml" runs in the Windows DirectML runtime.  The result names the device the model really
used ("cuda", "dml" or "cpu"), which is not always the one that was asked for."""
import os
from pathlib import Path

import torch
from audio_separator.separator import Separator

from . import emit, read_payload
from .copies import first_model_dir


def _required_files(p: dict) -> list[str]:
    """Every file audio-separator needs locally, so it never fetches one on its own."""
    name = str(p["model"]).lower()
    files = list(dict.fromkeys(p.get("model_files") or [p["model"]]))
    if "download_checks.json" not in files:
        files.append("download_checks.json")
    if name.endswith(".onnx") and "mdx_model_data.json" not in files:
        files.append("mdx_model_data.json")
    if name.endswith(".pth") and "vr_model_data.json" not in files:
        files.append("vr_model_data.json")
    return files


def _missing_files(model_dir: Path, p: dict) -> list[str]:
    needed = [model_dir / name for name in (p.get("model_files") or [p["model"]])]
    if not (model_dir / "download_checks.json").is_file():
        needed.append(model_dir / "download_checks.json")
    name = str(p["model"]).lower()
    if name.endswith(".onnx") and not (model_dir / "mdx_model_data.json").is_file():
        needed.append(model_dir / "mdx_model_data.json")
    if name.endswith(".pth") and not (model_dir / "vr_model_data.json").is_file():
        needed.append(model_dir / "vr_model_data.json")
    if name.endswith(".ckpt"):
        stems = [path.with_suffix(s) for path in needed for s in (".yaml", ".yml", ".json")]
        if not any(path.is_file() for path in stems):
            needed.append(needed[0].with_suffix(".yaml"))
    return [str(path) for path in needed if not path.is_file()]


def actual_device(separator) -> str:
    """Where the loaded model runs: "cuda", "dml" or "cpu".

    audio-separator keeps RoFormer models on the CPU under DirectML (torch-directml cannot hold
    their memory), so asking for DirectML does not mean getting it."""
    instance = getattr(separator, "model_instance", None)
    device = getattr(instance, "torch_device", None)
    if device is None:
        device = getattr(separator, "torch_device", None)
    kind = str(getattr(device, "type", device) or "cpu")
    return {"cuda": "cuda", "privateuseone": "dml"}.get(kind, "cpu")


def main() -> None:
    p = read_payload()
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "6")))
    requested = p.get("device", "auto")
    directml = requested == "directml"
    if directml and p.get("directml_roformer"):
        # audio-separator's own switch: run MDXC/RoFormer on DirectML instead of moving it to the
        # CPU.  It needs most of a 16 GB card; when it does not fit the worker fails and the stage
        # separates on the CPU.
        os.environ["AUDIO_SEPARATOR_FORCE_DML_MDXC"] = "1"
    device = "cuda" if requested in ("auto", "cuda", "rocm") and torch.cuda.is_available() else "cpu"
    out_dir = Path(p["out_dir"])
    # Prefer the copy inside the distro when the setup helper made one; /mnt is the fallback.
    model_dir = first_model_dir(p.get("model_dir_candidates"), _required_files(p),
                                p.get("model_sizes"), p["model_dir"])
    # Never let audio-separator download on its own: every catalog and custom file must already be
    # in place (the engine's preflight checks it, and `models download` fetched it).
    missing = _missing_files(model_dir, p)
    if missing:
        raise SystemExit(
            "the separator model is missing: " + ", ".join(missing)
            + ". Run `lyricloom models download <id>` or open Help > Models.")
    sep = Separator(output_dir=str(out_dir), model_file_dir=str(model_dir), output_format="WAV",
                    output_single_stem="Vocals", use_directml=directml,
                    mdxc_params={"segment_size": 256, "override_model_segment_size": False,
                                 "batch_size": 1, "overlap": p["overlap"], "pitch_shift": 0})
    sep.load_model(model_filename=p["model"])
    if directml:
        device = actual_device(sep)
    files = sep.separate(p["audio"], {"Vocals": "vocals_raw"})
    produced = [out_dir / Path(f).name for f in files]
    emit({"vocals": str(produced[0]), "device": device})


if __name__ == "__main__":
    main()
