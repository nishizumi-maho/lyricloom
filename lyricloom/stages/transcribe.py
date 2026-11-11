"""Whisper large-v3 through whisper.cpp (CPU by default; a Vulkan build can use the GPU). Used for
anchors and for checking lyrics, and as the lyrics themselves only when no source has them."""
from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import soundfile as sf

from .. import config, models
from ..model import Transcript, Word
from ..workers import run_process


def parse_whisper_json(data: dict) -> Transcript:
    """Words from whisper.cpp's full JSON. A word starts at its first token's DTW time when the
    run computed one (``t_dtw``, in centiseconds; -1 without DTW) and at the decoder's estimate
    otherwise."""
    words = []
    for seg in data.get("transcription", []):
        text = seg.get("text", "").strip()
        if not text:
            continue
        tokens = [t for t in seg.get("tokens", []) if not t["text"].startswith("[_")]
        probs = [t["p"] for t in tokens]
        start, end = seg["offsets"]["from"], seg["offsets"]["to"]
        first = next((t for t in tokens if t["text"].strip()), None)
        if first is not None and int(first.get("t_dtw", -1)) >= 0:
            start = min(int(first["t_dtw"]) * 10, end)
        words.append(Word(text, start, end, sum(probs) / len(probs) if probs else 0.0))
    return Transcript(data.get("result", {}).get("language", ""), words)


# Decoding for sung vocals, measured 2026-11-11 on five songs (ja/en/pt) against their official
# lyrics and human timing:
# -mc 0 carries no text from one 30 s window into the next. With the text carried, Whisper repeated
#   one window through a whole song (Reweave: no line of 58 heard; 44 without), and the character
#   error against the lyrics fell from 63% to 20% (English), 155% to 26% and 72% to 33% (Japanese);
#   Portuguese stayed at 6-7%.
# -dtw times each token from the attention alignment instead of the decoder's estimate (whisper.cpp
#   needs flash attention off for it, -nfa, which cost no time on the GPU measured). Anchors within
#   0.5 s of a human sync: 53% -> 84% (English), 58% -> 75% and 97% (Japanese). Only for the official
#   models, whose alignment heads whisper.cpp knows by name.
SUNG_DECODING = ("-mc", "0")
DTW_PRESETS = {"ggml-large-v3.bin": "large.v3", "ggml-large-v3-turbo.bin": "large.v3.turbo",
               "ggml-medium.bin": "medium", "ggml-small.bin": "small"}


def dtw_args(spec: models.ModelSpec) -> list[str]:
    """``-dtw <preset> -nfa`` for a model whisper.cpp has alignment heads for, else nothing."""
    preset = DTW_PRESETS.get(Path(spec.model_file().filename).name)
    return ["-dtw", preset, "-nfa"] if preset else []


# Phrases Whisper invents from video captions instead of transcribing (credits, subtitle notices).
_CREDIT_MARKS = ("作詞", "作曲", "編曲", "ご視聴", "字幕", "legenda", "subtitles", "amara.org")
MIN_WORDS_PER_MINUTE = 15     # real singing is several times denser than this
MAX_CREDIT_SHARE = 0.3
REPETITION_MIN_WORDS = 30
REPETITION_MAX_DISTINCT = 5
# Gaps longer than this are instrumental/quiet time, not singing: do not let an intro or a long
# break inflate the denominator (R1-31).
MAX_SUNG_GAP_S = 2.0
# Even a very sparse 5-minute ballad has some sung time; a floor keeps a handful of words in a
# four-minute file suspicious.
MIN_EXPECTED_WINDOW_S = 60.0


def sung_duration_s(words: list[Word]) -> float:
    """Seconds covered by word spans, merging small gaps and ignoring instrumental breaks."""
    spans = sorted((w.start_ms / 1000, w.end_ms / 1000) for w in words if w.end_ms > w.start_ms)
    total, start, end = 0.0, None, None
    for a, b in spans:
        if start is None:
            start, end = a, b
        elif a <= end + MAX_SUNG_GAP_S:
            end = max(end, b)
        else:
            total += end - start
            start, end = a, b
    if start is not None:
        total += end - start
    return total


def looks_hallucinated(tr: Transcript, duration_s: float) -> bool:
    """True when Whisper's output is not a transcription of the singing: far too few words for the
    sung part of the song, mostly caption credits, or one short phrase repeated over and over.

    R1-31: the denominator is the vocal activity measured from the word spans, not the audio file
    length, so a sparse ballad with a long intro/outro is not treated as a hallucination."""
    n = len(tr.words)
    window_s = max(sung_duration_s(tr.words), min(max(duration_s, 0.0), MIN_EXPECTED_WINDOW_S), 1.0)
    if n < MIN_WORDS_PER_MINUTE * window_s / 60:
        return True
    if n == 0:
        return False
    texts = [w.text.lower() for w in tr.words]
    credits = sum(1 for t in texts if any(m in t for m in _CREDIT_MARKS))
    if credits / n >= MAX_CREDIT_SHARE:
        return True
    distinct = {"".join(ch for ch in t if ch.isalnum()) for t in texts}
    return n >= REPETITION_MIN_WORDS and len(distinct) <= REPETITION_MAX_DISTINCT


def _model_path(spec: models.ModelSpec) -> Path:
    return spec.dest(spec.model_file(), config.MODELS)


def _duration_s(path: Path) -> float:
    try:
        return float(sf.info(str(path)).duration)
    except (OSError, RuntimeError):
        return 0.0


def _timeout_s(path: Path) -> int:
    """A generous limit proportional to the audio: 10x its length plus ten minutes (R1-21)."""
    return max(600, int(_duration_s(path) * 10) + 600)


def _cli_error(cli: Path) -> RuntimeError:
    searched = "\n  ".join(str(p) for p in config.whisper_cli_candidates())
    return RuntimeError(
        "whisper-cli was not found. Install whisper.cpp and set the `whisper_cli` setting (or the "
        "LYRICLOOM_WHISPER_CLI environment variable) to its full path, put it in "
        f"{config.APP_DATA / 'bin'}, or add it to PATH.\nChecked:\n  {searched}\n"
        f"Configured path: {cli}")


def transcribe(vocals16k: Path, work: Path, lang: str | None, prompt: str | None = None,
               name: str = "whisper", extra: tuple[str, ...] | list[str] = (),
               model: models.ModelSpec | None = None,
               cancel: threading.Event | None = None) -> Transcript:
    """`prompt` gives Whisper context (artist and title); `name` keeps several passes apart in the
    work dir; `extra` adds decoding options (e.g. a different temperature for a second pass);
    `cancel` stops whisper-cli and its process tree when the queue is stopped."""
    work.mkdir(parents=True, exist_ok=True)
    spec = model or config.resolve_model("transcribe", lang)
    cli = config.whisper_cli()
    if not cli.is_file():
        raise _cli_error(cli)
    model_path = _model_path(spec)
    if not model_path.is_file():
        raise RuntimeError(
            f"the Whisper model {spec.id!r} is missing: {model_path}. "
            f"Run `lyricloom models download {spec.id}` or open Help > Models.")
    out = work / name
    code = lang if lang and lang not in ("", "other") else "auto"
    cmd = [str(cli), "-m", str(model_path), "-f", str(vocals16k),
           "-l", code, "-ojf", "-of", str(out),
           "-ml", "1", "-sow", "--beam-size", "5", "--best-of", "5", "-t", str(config.CPU_THREADS), "-np",
           *SUNG_DECODING, *dtw_args(spec), *extra]
    if prompt:
        cmd += ["--prompt", prompt]
    timeout_s = _timeout_s(vocals16k)
    try:
        proc = run_process(cmd, cancel=cancel, timeout_s=timeout_s)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"transcription timed out after {timeout_s} s; the model or the audio may be corrupt. "
            "Try another Whisper model, or check the file.") from e
    if proc.returncode != 0:
        raise RuntimeError("whisper-cli failed: " + proc.stderr.decode("utf-8", "replace")[-1500:])
    return parse_whisper_json(json.loads(out.with_suffix(".json").read_text(encoding="utf-8")))
