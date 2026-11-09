"""Runs one track through probe -> lyrics -> separate -> transcribe -> align -> write, with a
cache per stage, and a folder of tracks without letting one failure stop the rest."""
from __future__ import annotations

import os
import time
import traceback
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from . import ENGINE_VERSION, VERSION, cache, config
from . import models as model_catalog
from .brand import is_ours, tag
from .align.confidence import REVIEW_THRESHOLD
from .align.consensus import refrain_consensus, rover
from .lrc import parse_lrc
from .lyrics.score import choose
from .lyrics.search import search_all
from .model import Candidate, Line, LrcDoc, Segment, Transcript, Word
from .probe import probe
from .stages.align import align, lyric_lang
from .stages.separate import keep_vocals, separate, to_mono16k
from .stages.assemblyai import transcribe_assemblyai
from .stages.transcribe import looks_hallucinated, transcribe
from .stages.write import write_lyrics, write_original

STAGES = ["probe", "lyrics", "separate", "transcribe", "align", "write"]
AUDIO_EXT = {".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav"}
TRANSCRIPT_MAX_WORDS = 10
SENTENCE_END = set(".!?。！？")


@dataclass
class TrackResult:
    path: Path
    status: Literal["done", "review", "skipped", "failed"]
    source: str = ""
    conf: float = 0.0
    error: str = ""
    device: str = ""   # where the vocals were separated: rocm (WSL), dml, cpu or kept
    fallback: str = ""  # why the WSL/ROCm separation failed, when it ran on the CPU instead
    models: dict[str, str] = field(default_factory=dict)  # stage -> model id used for this track


def _lines_from_json(data) -> list[Line] | None:
    if data is None:
        return None
    return [Line(l["start_ms"], [Segment(**s) for s in l["segments"]], l["conf"]) for l in data]


def _transcript_from_json(data: dict) -> Transcript:
    return Transcript(data["lang"], [Word(**w) for w in data["words"]])


def _cands_from_json(data: dict) -> list[Candidate]:
    return [Candidate(c["source"], c["text"], c["score"], _lines_from_json(c["synced"]), c["url"]) for c in data["candidates"]]


# Subtitle credits Whisper learned from video captions and tends to invent at the end of audio.
WHISPER_CREDITS = ["legenda adriana zanotto", "legendas pela comunidade amara.org", "obrigado por assistir",
                   "subtitles by the amara.org community", "thanks for watching", "ご視聴ありがとうございました"]


def _drop_trailing_credits(words: list[Word]) -> list[Word]:
    words = list(words)
    changed = True
    while changed and words:
        changed = False
        for phrase in WHISPER_CREDITS:
            n = len(phrase.split()) if " " in phrase else 1
            tail = " ".join(w.text for w in words[-n:]).lower().strip(" .!")
            if tail == phrase:
                words = words[:-n]
                changed = True
    return words


def _transcript_candidate(tr: Transcript, lang: str | None = None) -> Candidate:
    """Lyrics from Whisper, used only when no source has the song. Whisper reports no gaps between
    sung words, so lines break where it starts a capitalized phrase, after final punctuation, or at
    a maximum length. Repeated lines (refrains) then vote on disputed words."""
    sep = "" if tr.lang == "ja" else " "
    lines: list[list[Word]] = []
    cur: list[Word] = []
    for w in _drop_trailing_credits(tr.words):
        if cur and w.text[:1].isupper() and w.text != "I":
            lines.append(cur)
            cur = []
        cur.append(w)
        if w.text[-1:] in SENTENCE_END or len(cur) >= TRANSCRIPT_MAX_WORDS:
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    lines = refrain_consensus(lines, lang or tr.lang or "other")
    return Candidate("transcription", "\n".join(sep.join(w.text for w in l) for l in lines))


def _assemblyai(audio: Path, work: Path, sep: dict, lang: str, whisper: Transcript, prompt: str) -> Transcript | None:
    """AssemblyAI on the isolated vocals; None (logged) if the service fails, so the run carries on."""
    code = lang if lang in ("ja", "pt", "en") else (whisper.lang or "en")
    try:
        return transcribe_assemblyai(Path(sep["vocals16k"]), work, code, prompt, name="assemblyai_vocals")
    except Exception as e:  # noqa: BLE001 - optional cloud source: never fatal on its own
        _log(audio, f"assemblyai unavailable: {type(e).__name__}: {e}")
        return None


def _extra_passes(audio: Path, work: Path, sep: dict, first: Transcript, lang: str, prompt: str,
                  extra_voters: list[Transcript] | None = None) -> Transcript:
    """Transcription-only songs: two more Whisper passes (original mix, and the vocals decoded at
    another temperature), fused word by word with the first."""
    mix16k = work / "mix16k.wav"
    to_mono16k(audio, mix16k)
    whisper_lang = lang if lang == "ja" else None
    previous = config.active_language()
    config.set_active_language(lang)   # per-language model choice for the extra passes
    try:
        mix = transcribe(mix16k, work, whisper_lang, prompt, name="whisper_mix")
        warm = transcribe(Path(sep["vocals16k"]), work, whisper_lang, prompt, name="whisper_t02", extra=["-tp", "0.2"])
    finally:
        config.set_active_language(previous)
    return rover([first, mix, warm, *(extra_voters or [])], lang)


def _separate(audio: Path, work: Path) -> dict:
    sep = separate(audio, work)
    if sep.get("fallback"):
        _log(audio, f"separation in WSL failed, ran on {sep['device']} instead: {sep['fallback']}")
    else:
        _log(audio, f"separated on {sep['device']}")
    return sep


def forget_sync(audio: Path) -> list[Path]:
    """Deletes the word timing LyricLoom wrote for a song, so it can be done again: the .lrc (only
    when LyricLoom wrote it) and the .japanese.lrc / .romaji.lrc copies. The official lyric
    (.original.lrc) and .lrc files from anywhere else are kept. Returns the files deleted."""
    from .stages.write import japanese_path, romaji_path
    removed = []
    lrc = audio.with_suffix(".lrc")
    if lrc.exists():
        meta = parse_lrc(lrc.read_text(encoding="utf-8", errors="replace")).meta
        if is_ours(meta.get("re")):
            lrc.unlink()
            removed.append(lrc)
    for p in (japanese_path(audio), romaji_path(audio)):
        if p.exists():
            p.unlink()
            removed.append(p)
    return removed


def _already_done(audio: Path) -> bool:
    lrc = audio.with_suffix(".lrc")
    if not lrc.exists():
        return False
    meta = parse_lrc(lrc.read_text(encoding="utf-8", errors="replace")).meta
    return is_ours(meta.get("re")) and meta.get("#engine") == ENGINE_VERSION


# Each cached stage has its own version: bump one only when that stage's output would change, so
# an engine change does not redo the expensive ones (separation, transcription) for the library.
# Started at "3", the engine version the existing caches were written with, so they stay valid.
STAGE_VERSIONS = {"lyrics": "4", "separate": "4", "transcribe": "3",
                  "transcribe_extra": "3", "transcribe_extra_aai": "3"}


def _cached(audio: Path, stage: str, fresh: set[str], compute: Callable[[], dict],
            inputs: dict | None = None,
            required: list[model_catalog.ModelSpec] | None = None) -> dict:
    version = STAGE_VERSIONS[stage]
    data = None if stage in fresh else cache.load(audio, stage, version, inputs=inputs)
    if data is None:
        # Never let a stage download a model on its own: check the resolved files first and turn a
        # miss into a typed, actionable failure (R3-03).
        model_catalog.ensure_ready(required or [])
        data = compute()
        cache.save(audio, stage, version, data, inputs=inputs)
    return data


def _model_inputs(stage: str, spec: model_catalog.ModelSpec, **params) -> dict:
    return {stage: model_catalog.fingerprint(spec), **params}


def _write(audio: Path, meta, chosen: Candidate, result,
           used_models: dict[str, str] | None = None) -> str:
    """Writes the .lrc; returns the status. Low-confidence lines are listed in [#review:...]."""
    tags = {"ti": meta.title, "ar": meta.artist, "re": tag(VERSION),
            "#source": f"{chosen.source} conf:{result.track_conf:.2f}", "#engine": ENGINE_VERSION}
    if used_models:
        tags["#models"] = model_catalog.tag_value(used_models)
    low = [str(i) for i, l in enumerate(result.lines) if l.conf < REVIEW_THRESHOLD]
    if low:
        tags["#review"] = ",".join(low)
    write_lyrics(audio, LrcDoc(tags, result.lines))
    if chosen.source not in ("transcription", "manual"):   # only a lyric found online is "official"
        write_original(audio, {"ti": meta.title, "ar": meta.artist, "#source": chosen.source}, chosen)
    status = "review" if chosen.source == "transcription" or result.review else "done"
    _log(audio, f"{status} source={chosen.source} conf={result.track_conf:.2f} url={chosen.url}")
    return status


def realign(audio: Path, text: str, source: str = "manual") -> TrackResult:
    """Aligns lyrics given by hand (e.g. pasted in the app) and writes the .lrc. Reuses the cached
    separation and transcription; the track must have been processed once."""
    try:
        meta = probe(audio)
        work = cache.work_dir(audio)
        prompt = f"{meta.artist} - {meta.title}"
        whisper_lang = meta.lang if meta.lang == "ja" else None
        sep_spec = config.resolve_model("separate", meta.lang)
        tr_spec = config.resolve_model("transcribe", meta.lang)
        sep_inputs = _model_inputs("separator", sep_spec, overlap=config.SEPARATOR_OVERLAP,
                                   device=config.SEPARATOR_DEVICE, wsl=config.SEPARATOR_WSL_ENABLED)
        tr_inputs = _model_inputs("transcribe", tr_spec, separator=sep_inputs["separator"],
                                  lang=whisper_lang, prompt=prompt)
        sep = cache.load(audio, "separate", STAGE_VERSIONS["separate"], inputs=sep_inputs)
        tr = cache.load(audio, "transcribe", STAGE_VERSIONS["transcribe"], inputs=tr_inputs)
        if sep is None or tr is None:
            raise RuntimeError("process the track once before realigning it")
        whisper = _transcript_from_json(tr)
        anchor = Transcript(whisper.lang, []) if looks_hallucinated(whisper, meta.duration_s) else whisper
        chosen = Candidate(source, text.strip())
        lang = lyric_lang(meta, whisper)
        config.set_active_language(lang)
        align_spec = config.resolve_model("align", lang)
        model_catalog.ensure_ready([align_spec])
        result = align(meta, work, chosen, anchor, Path(sep["vocals16k"]), Path(sep["vocals"]))
        used = {"transcribe": tr_spec.id, "separate": sep_spec.id, **result.models_used}
        status = _write(audio, meta, chosen, result, used_models=used)
        return TrackResult(audio, status, source, result.track_conf,
                           device=sep.get("device", ""), fallback=sep.get("fallback", ""),
                           models=used)
    except model_catalog.MissingModels as e:
        _log(audio, f"realign failed: {e}")
        return TrackResult(audio, "failed", error=str(e))
    except Exception as e:  # noqa: BLE001 - reported to the app, never raised into the UI
        _log(audio, "realign failed\n" + traceback.format_exc())
        return TrackResult(audio, "failed", error=f"{type(e).__name__}: {e}")
    finally:
        config.clear_active_models()
        config.clear_active_language()


def process(audio: Path, force: bool = False, only_stage: str | None = None,
            on_stage: Callable[[str], None] | None = None,
            models: dict[str, str] | None = None) -> TrackResult:
    """Runs one track.  ``models`` is a per-song override ``{stage: model_id}`` (for that run
    only); it is written to the track log and to the .lrc ``[#models:...]`` tag."""
    stage = on_stage or (lambda name: None)
    if only_stage is not None and only_stage not in STAGES:
        raise ValueError(f"unknown stage {only_stage}")
    fresh = set(STAGES[STAGES.index(only_stage):]) if only_stage else set()
    if "transcribe" in fresh:
        fresh.add("transcribe_extra")
    config.set_active_models(models)
    try:
        if not (force or only_stage) and _already_done(audio):
            return TrackResult(audio, "skipped")
        meta = probe(audio)
        config.set_active_language(meta.lang)
        if models:
            unknown = sorted(set(models) - set(model_catalog.STAGES))
            if unknown:
                _log(audio, f"ignoring unknown model stage(s): {', '.join(unknown)}")
        work = cache.work_dir(audio)
        if models:
            _log(audio, "model overrides for this run: " + model_catalog.tag_value(models))
        stage("lyrics")
        cands = _cands_from_json(_cached(audio, "lyrics", fresh, lambda: {
            "candidates": [asdict(c) for c in search_all(meta)]}))
        stage("separate")
        sep_spec = config.resolve_model("separate", meta.lang)
        sep_inputs = _model_inputs("separator", sep_spec, overlap=config.SEPARATOR_OVERLAP,
                                   device=config.SEPARATOR_DEVICE, wsl=config.SEPARATOR_WSL_ENABLED)
        sep = _cached(audio, "separate", fresh, lambda: _separate(audio, work),
                      inputs=sep_inputs, required=[sep_spec])
        device = sep.get("device", "")
        keep_vocals(audio, Path(sep["vocals"]), model=sep_spec)   # also for tracks separated before vocals were kept
        stage("transcribe")
        prompt = f"{meta.artist} - {meta.title}"
        whisper_lang = meta.lang if meta.lang == "ja" else None
        tr_spec = config.resolve_model("transcribe", meta.lang)
        tr_inputs = _model_inputs("transcribe", tr_spec, separator=sep_inputs["separator"],
                                  lang=whisper_lang, prompt=prompt)
        tr_data = _cached(audio, "transcribe", fresh, lambda: asdict(
            transcribe(Path(sep["vocals16k"]), work, whisper_lang, prompt)),
            inputs=tr_inputs, required=[tr_spec])
        whisper = _transcript_from_json(tr_data)
        lang = lyric_lang(meta, whisper)
        hallucinated = looks_hallucinated(whisper, meta.duration_s)
        if hallucinated:
            _log(audio, "whisper output looks hallucinated (credits / repetition / too few words): not used")

        aai: list[Transcript | None] = []   # computed at most once, only when needed

        def assemblyai() -> Transcript | None:
            if not aai:
                aai.append(_assemblyai(audio, work, sep, lang, whisper, prompt) if config.ASSEMBLYAI_ENABLED else None)
            return aai[0]

        # Transcript that drives the anchors and the choice of lyrics: Whisper, unless it is unusable
        # (or the song is Japanese, where AssemblyAI proved far more reliable).
        anchor = whisper
        if hallucinated or lang == "ja":
            anchor = assemblyai() or (Transcript(whisper.lang, []) if hallucinated else whisper)

        chosen = choose(cands, anchor.text, lang)
        transcription_spec = tr_spec
        if chosen is None:
            if hallucinated and assemblyai() is None:
                raise RuntimeError("no lyrics found anywhere and the transcription is unusable (Whisper hallucinated)")
            voter = assemblyai()
            if hallucinated:
                fused = voter
            else:
                vote_stage = "transcribe_extra_aai" if voter else "transcribe_extra"
                extra_spec = config.resolve_model("transcribe", lang)
                transcription_spec = extra_spec
                extra_inputs = _model_inputs("transcribe", extra_spec,
                                             separator=sep_inputs["separator"],
                                             lang=lang, prompt=prompt,
                                             assemblyai=bool(voter))
                fused = _transcript_from_json(_cached(audio, vote_stage, fresh, lambda: asdict(
                    _extra_passes(audio, work, sep, whisper, lang, prompt, [voter] if voter else [])),
                    inputs=extra_inputs, required=[extra_spec]))
            chosen = _transcript_candidate(fused, lang)
        stage("align")
        align_spec = config.resolve_model("align", lang)
        model_catalog.ensure_ready([align_spec])
        result = align(meta, work, chosen, anchor, Path(sep["vocals16k"]), Path(sep["vocals"]))
        used = {"transcribe": transcription_spec.id, "separate": sep_spec.id, **result.models_used}
        stage("write")
        status = _write(audio, meta, chosen, result, used_models=used)
        _log(audio, "models used: " + model_catalog.tag_value(used))
        return TrackResult(audio, status, chosen.source, result.track_conf, device=device,
                           fallback=sep.get("fallback", ""), models=used)
    except model_catalog.MissingModels as e:
        _log(audio, f"missing models: {e}")
        return TrackResult(audio, "failed", error=str(e))
    except Exception as e:  # noqa: BLE001 - one broken track must not stop a folder run
        _log(audio, "failed\n" + traceback.format_exc())
        return TrackResult(audio, "failed", error=f"{type(e).__name__}: {e}")
    finally:
        config.clear_active_models()
        config.clear_active_language()


def _log(audio: Path, msg: str) -> None:
    try:
        with (cache.work_dir(audio) / "log.txt").open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def find_audio(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    # os.walk avoids one stat per directory entry that Path.rglob performs; on a large external
    # library that difference is minutes, not seconds.
    found: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if Path(name).suffix.lower() in AUDIO_EXT:
                found.append(Path(dirpath) / name)
    return sorted(found)


def process_all(paths: Iterable[Path], force: bool = False, only_stage: str | None = None,
                on_result: Callable[[TrackResult], None] | None = None) -> list[TrackResult]:
    results = []
    for p in paths:
        r = process(p, force=force, only_stage=only_stage)
        if on_result:
            on_result(r)
        results.append(r)
    return results
