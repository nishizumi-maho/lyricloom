"""Optional transcription through AssemblyAI (cloud). The audio is uploaded to their servers.

Portuguese/English use Universal-3.5 Pro (their most capable model, which also takes a context
prompt); Japanese is not supported by it, so Japanese uses Universal-2. Word times come back in ms.
The API key is read from ``assemblyai.key`` in LyricLoom's data directory (encrypted with Windows
DPAPI, mode 0600 elsewhere) or from the ASSEMBLYAI_API_KEY environment variable. Cloud
transcription also needs the separate ``assemblyai_enabled`` setting and a per-run allowance."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

import httpx

from .. import config
from ..model import Transcript, Word

log = logging.getLogger(__name__)

API = "https://api.assemblyai.com/v2"
PRO_LANGS = {"pt", "en", "es", "fr", "de", "it"}
POLL_S = 3
TIMEOUT_S = 15 * 60


def api_key() -> str:
    key = config.read_assemblyai_key()
    if not key:
        raise RuntimeError("no AssemblyAI key: add one in the app or set ASSEMBLYAI_API_KEY")
    return key


def build_request(audio_url: str, lang: str, context: str | None) -> dict:
    req: dict = {"audio_url": audio_url, "language_code": lang, "punctuate": True, "format_text": True}
    if lang in PRO_LANGS:
        req["speech_models"] = ["universal-3-5-pro"]
        if context:
            req["prompt"] = f"Song lyrics, sung (not spoken). Track: {context}. Transcribe the sung words exactly."
    else:
        req["speech_models"] = ["universal-2"]
    return req


# Prompted with "song lyrics", the Pro model wraps sections in tags like <LYRICS>...</LYRICS>.
_MARKUP = re.compile(r"</?[A-Za-z_]+>")


def parse_transcript(data: dict) -> Transcript:
    words = []
    for w in data.get("words") or []:
        text = _MARKUP.sub("", w["text"]).strip()
        if text:
            words.append(Word(text, int(w["start"]), int(w["end"]), float(w.get("confidence", 0.0))))
    return Transcript(data.get("language_code") or "", words)


def _discard_saved(path: Path) -> None:
    """Moves a corrupt cache aside so a later run can upload again instead of failing forever."""
    target = path.with_name(path.name + ".corrupt")
    n = 1
    while target.exists():
        target = path.with_name(f"{path.name}.corrupt{n}")
        n += 1
    try:
        os.replace(path, target)
    except OSError:
        pass


def _reuse_saved(path: Path) -> Transcript | None:
    """The cached transcript, or None after setting a corrupt one aside (FR-A-08)."""
    try:
        return parse_transcript(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        log.warning("discarding the corrupt AssemblyAI cache %s (%s); a later run can upload "
                    "again", path, type(exc).__name__)
        _discard_saved(path)
        return None


def transcribe_assemblyai(wav: Path, work: Path, lang: str, context: str | None = None,
                          name: str = "assemblyai", reuse: bool = True) -> Transcript:
    saved = work / f"{name}.json"
    if reuse and saved.exists():   # already transcribed: no new upload, no new charge
        cached = _reuse_saved(saved)
        if cached is not None:
            return cached
    headers = {"authorization": api_key()}
    with httpx.Client(timeout=120) as c:
        with wav.open("rb") as f:
            up = c.post(f"{API}/upload", headers=headers, content=f.read())
        up.raise_for_status()
        job = c.post(f"{API}/transcript", headers=headers, json=build_request(up.json()["upload_url"], lang, context))
        job.raise_for_status()
        tid = job.json()["id"]
        deadline = time.time() + TIMEOUT_S
        while True:
            r = c.get(f"{API}/transcript/{tid}", headers=headers)
            r.raise_for_status()
            data = r.json()
            if data["status"] == "completed":
                break
            if data["status"] == "error":
                raise RuntimeError(f"AssemblyAI error: {data.get('error')}")
            if time.time() > deadline:
                raise TimeoutError(f"AssemblyAI transcript {tid} not ready after {TIMEOUT_S} s")
            time.sleep(POLL_S)
    work.mkdir(parents=True, exist_ok=True)
    tmp = saved.with_name(saved.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, saved)
    return parse_transcript(data)
