"""Whisper large-v3 through whisper.cpp (Vulkan). Used for anchors and for checking lyrics,
and as the lyrics themselves only when no source has them."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .. import config
from ..model import Transcript, Word


def parse_whisper_json(data: dict) -> Transcript:
    words = []
    for seg in data.get("transcription", []):
        text = seg.get("text", "").strip()
        if not text:
            continue
        probs = [t["p"] for t in seg.get("tokens", []) if not t["text"].startswith("[_")]
        words.append(Word(text, seg["offsets"]["from"], seg["offsets"]["to"],
                          sum(probs) / len(probs) if probs else 0.0))
    return Transcript(data.get("result", {}).get("language", ""), words)


# Phrases Whisper invents from video captions instead of transcribing (credits, subtitle notices).
_CREDIT_MARKS = ("作詞", "作曲", "編曲", "ご視聴", "字幕", "legenda", "subtitles", "amara.org")
MIN_WORDS_PER_MINUTE = 15     # real singing is several times denser than this
MAX_CREDIT_SHARE = 0.3
REPETITION_MIN_WORDS = 30
REPETITION_MAX_DISTINCT = 5


def looks_hallucinated(tr: Transcript, duration_s: float) -> bool:
    """True when Whisper's output is not a transcription of the singing: far too few words for the
    song's length, mostly caption credits, or one short phrase repeated over and over."""
    n = len(tr.words)
    if n < MIN_WORDS_PER_MINUTE * duration_s / 60:
        return True
    if n == 0:
        return False
    texts = [w.text.lower() for w in tr.words]
    credits = sum(1 for t in texts if any(m in t for m in _CREDIT_MARKS))
    if credits / n >= MAX_CREDIT_SHARE:
        return True
    distinct = {"".join(ch for ch in t if ch.isalnum()) for t in texts}
    return n >= REPETITION_MIN_WORDS and len(distinct) <= REPETITION_MAX_DISTINCT


def transcribe(vocals16k: Path, work: Path, lang: str | None, prompt: str | None = None,
               name: str = "whisper", extra: tuple[str, ...] | list[str] = ()) -> Transcript:
    """`prompt` gives Whisper context (artist and title); `name` keeps several passes apart in the
    work dir; `extra` adds decoding options (e.g. a different temperature for a second pass)."""
    work.mkdir(parents=True, exist_ok=True)
    if not Path(config.WHISPER_CLI).is_file():
        raise RuntimeError(
            "whisper-cli was not found. Open Help > Download models, or install whisper.cpp and "
            "set LYRICLOOM_WHISPER_CLI.")
    if not Path(config.WHISPER_MODEL).is_file():
        raise RuntimeError(
            f"the Whisper model is missing: {config.WHISPER_MODEL}. "
            "Open Help > Download models to fetch it.")
    out = work / name
    cmd = [str(config.WHISPER_CLI), "-m", str(config.WHISPER_MODEL), "-f", str(vocals16k),
           "-l", lang if lang in ("ja", "pt", "en") else "auto", "-ojf", "-of", str(out),
           "-ml", "1", "-sow", "--beam-size", "5", "--best-of", "5", "-t", str(config.CPU_THREADS), "-np", *extra]
    if prompt:
        cmd += ["--prompt", prompt]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if config.IS_WINDOWS else 0
    proc = subprocess.run(cmd, capture_output=True, creationflags=flags)
    if proc.returncode != 0:
        raise RuntimeError("whisper-cli failed: " + proc.stderr.decode("utf-8", "replace")[-1500:])
    return parse_whisper_json(json.loads(out.with_suffix(".json").read_text(encoding="utf-8")))
