"""Worker: CTC forced alignment with torchaudio's MMS_FA (multilingual wav2vec2).

Payload {wav, device, blocks: [{start_ms, end_ms, lines: [[mms_tokens per segment]]}]}.
device "cuda" runs the model on the GPU (inside WSL, where torch finds the ROCm device through
ROCm); "cpu" is the Windows fallback.
Result {blocks: [{lines: [{segments: [{start_ms, end_ms, score} | null]}]}]}, times relative to
the block start. A segment whose tokens are empty (pure punctuation) or a block that cannot be
aligned yields nulls instead of failing the track."""
import os

import soundfile as sf
import torch
import torchaudio

from . import emit, read_payload

SR = 16000
WINDOW_S = 30  # emissions are computed in windows: attention over a whole song would not fit


def _load(path: str, device: str) -> torch.Tensor:
    """Mono 16 kHz float tensor on `device` (the payload is always the 16 kHz mono copy)."""
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    wave = torch.from_numpy(data.mean(axis=1, keepdims=True)).transpose(0, 1)
    if sr != SR:
        wave = torchaudio.functional.resample(wave, sr, SR)
    return wave.to(device)


def _emission(model, wave: torch.Tensor) -> torch.Tensor:
    parts = []
    with torch.inference_mode():
        for start in range(0, wave.size(1), WINDOW_S * SR):
            chunk = wave[:, start:start + WINDOW_S * SR]
            if chunk.size(1) < 400:  # shorter than one wav2vec2 frame
                break
            parts.append(model(chunk)[0])
    return torch.cat(parts, dim=1)


def _align_block(model, tokenizer, aligner, wave, block) -> dict:
    lines = block["lines"]
    words, where = [], []
    for li, segs in enumerate(lines):
        for si, tok in enumerate(segs):
            if tok:
                words.append(tok)
                where.append((li, si))
    result = [{"segments": [None] * len(segs)} for segs in lines]
    if not words:
        return {"lines": result}
    a, b = block["start_ms"] * SR // 1000, block["end_ms"] * SR // 1000
    piece = wave[:, a:b]
    try:
        # The aligner walks probabilities on the CPU; only the model's emissions need the GPU.
        emission = _emission(model, piece).cpu()
        spans = aligner(emission[0], tokenizer(words))
    except Exception:  # noqa: BLE001 - transcript longer than audio, etc.: leave the block unaligned
        return {"lines": result}
    ms_per_frame = piece.size(1) / emission.size(1) / SR * 1000
    for (li, si), word_spans in zip(where, spans):
        result[li]["segments"][si] = {
            "start_ms": int(word_spans[0].start * ms_per_frame),
            "end_ms": int(word_spans[-1].end * ms_per_frame),
            "score": float(sum(s.score * len(s) for s in word_spans) / sum(len(s) for s in word_spans)),
        }
    return {"lines": result}


def main() -> None:
    p = read_payload()
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "6")))
    device = "cuda" if p.get("device") in ("auto", "cuda") and torch.cuda.is_available() else "cpu"
    bundle = torchaudio.pipelines.MMS_FA
    model = bundle.get_model(with_star=False).to(device)
    wave = _load(p["wav"], device)
    tokenizer, aligner = bundle.get_tokenizer(), bundle.get_aligner()
    emit({"blocks": [_align_block(model, tokenizer, aligner, wave, b) for b in p["blocks"]]})


if __name__ == "__main__":
    main()
