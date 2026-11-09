import hashlib
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from mutagen.flac import FLAC

from lyricloom import ENGINE_VERSION, cli, config, models, runner
from lyricloom.lrc import parse_lrc
from lyricloom.model import Candidate, Line, Segment, Transcript, Word
from lyricloom.stages.align import AlignResult


def _flac(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.zeros(44100, dtype="float32"), 44100, format="FLAC")
    f = FLAC(str(path))
    f["artist"], f["title"] = "Test Artist", "Synthetic Song"
    f.save()
    return path


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr("lyricloom.config.WORK_ROOT", tmp_path / "work")
    monkeypatch.setattr("lyricloom.config.LIBRARY_ROOT", tmp_path / "Library")
    calls = {"separate": 0, "transcribe": 0, "align": 0}

    def fake_separate(audio, work, cancel=None):
        calls["separate"] += 1
        return {"vocals": "v.wav", "vocals16k": "v16.wav", "model": "m", "device": "cpu"}

    def fake_transcribe(v, w, lang, prompt=None, name="whisper", extra=(), cancel=None):
        calls["transcribe"] += 1
        return Transcript("pt", [Word("eu", 0, 300, 0.9), Word("vou", 400, 700, 0.9)])

    def fake_align(meta, work, chosen, tr, v, vf=None, cancel=None):
        calls["align"] += 1
        return AlignResult(
            [Line(0, [Segment("eu ", 0, 300, 0.9), Segment("vou", 400, 700, 0.9)], 0.9)], 0.9, False)

    monkeypatch.setattr(runner, "search_all", lambda meta: [Candidate("letras", "eu vou", score=0.9)])
    monkeypatch.setattr(runner, "separate", fake_separate)
    monkeypatch.setattr(runner, "transcribe", fake_transcribe)
    monkeypatch.setattr(runner, "to_mono16k", lambda src, dst: None)
    monkeypatch.setattr(runner, "align", fake_align)
    # These tests replace the heavy stages with fakes; the dedicated preflight test below uses the
    # real model check.
    monkeypatch.setattr(runner.model_catalog, "ensure_ready", lambda *a, **k: None)
    return tmp_path / "Library", calls


def test_process_writes_lrc_with_source_and_engine(lib):
    root, _ = lib
    audio = _flac(root / "a.flac")
    res = runner.process(audio)
    assert res.status == "done" and res.source == "letras"
    doc = parse_lrc((root / "a.lrc").read_text(encoding="utf-8"))
    assert doc.meta["#source"] == "letras conf:0.90"
    assert doc.meta["#engine"] == ENGINE_VERSION
    assert "#models" in doc.meta
    assert "transcribe=whisper-large-v3" in doc.meta["#models"]
    assert "separate=separator-mel-band-roformer" in doc.meta["#models"]
    assert doc.lines[0].text == "eu vou"


def test_official_lyric_is_kept_as_original_lrc(lib, monkeypatch):
    root, _ = lib
    audio = _flac(root / "a.flac")
    synced = [Line(1000, [Segment("eu vou", 1000, None)], 1.0)]
    monkeypatch.setattr(runner, "search_all", lambda meta: [Candidate("lrclib", "eu vou", score=0.9, synced=synced)])
    runner.process(audio)
    original = parse_lrc((root / "a.original.lrc").read_text(encoding="utf-8"))
    assert original.lines[0].start_ms == 1000 and original.lines[0].text == "eu vou"
    assert original.meta["#source"] == "lrclib"
    runner.realign(audio, "outra letra")                      # pasted text is not the official lyric
    assert "eu vou" in (root / "a.original.lrc").read_text(encoding="utf-8")


def test_unsynced_official_lyric_is_kept_as_text(lib):
    root, _ = lib
    runner.process(_flac(root / "a.flac"))
    assert "eu vou" in (root / "a.original.lrc").read_text(encoding="utf-8")


def test_audio_untouched(lib):
    root, _ = lib
    audio = _flac(root / "a.flac")
    before = (audio.stat().st_mtime_ns, hashlib.sha1(audio.read_bytes()).hexdigest())
    runner.process(audio)
    assert (audio.stat().st_mtime_ns, hashlib.sha1(audio.read_bytes()).hexdigest()) == before


def test_runner_skips_same_engine_version_and_force_reprocesses(lib):
    root, calls = lib
    audio = _flac(root / "a.flac")
    runner.process(audio)
    assert runner.process(audio).status == "skipped"
    assert runner.process(audio, force=True).status == "done"


def test_stage_cache_reused(lib):
    root, calls = lib
    audio = _flac(root / "a.flac")
    runner.process(audio)
    runner.process(audio, force=True)
    assert calls["separate"] == 1
    runner.process(audio, only_stage="separate")
    assert calls["separate"] == 2


def _count_transcribe(monkeypatch):
    calls = []

    def fake(v, w, lang, prompt=None, name="whisper", extra=(), cancel=None):
        calls.append({"wav": str(v), "prompt": prompt, "name": name, "extra": list(extra)})
        return Transcript("pt", [Word("eu", 0, 300, 0.9), Word("vou", 400, 700, 0.9)])

    monkeypatch.setattr(runner, "transcribe", fake)
    monkeypatch.setattr(runner, "to_mono16k", lambda src, dst: None)
    return calls


def test_single_whisper_pass_with_prompt_when_lyrics_found(lib, monkeypatch):
    root, _ = lib
    calls = _count_transcribe(monkeypatch)
    runner.process(_flac(root / "a.flac"))
    assert len(calls) == 1
    assert calls[0]["prompt"] == "Test Artist - Synthetic Song"


def test_extra_passes_only_for_transcription_only_songs(lib, monkeypatch):
    root, _ = lib
    calls = _count_transcribe(monkeypatch)
    monkeypatch.setattr(runner, "search_all", lambda meta: [])
    runner.process(_flac(root / "a.flac"))
    assert len(calls) == 3
    assert {c["name"] for c in calls} == {"whisper", "whisper_mix", "whisper_t02"}
    assert any("mix16k" in c["wav"] for c in calls)
    assert all(c["prompt"] == "Test Artist - Synthetic Song" for c in calls)


CREDITS = Transcript("ja", [Word("作詞・作曲・編曲", i * 30000, i * 30000 + 22000, 0.9) for i in range(8)])
SUNG_TEXT = "texto inventado para o teste com palavras simples e sem nenhuma canção real"
SUNG = Transcript("pt", [Word(w, i * 400, i * 400 + 300, 0.9) for i, w in enumerate((SUNG_TEXT + " ") .split() * 3)])


def _aai(monkeypatch, enabled=True):
    calls = []

    def fake(wav, work, lang, context=None, name="assemblyai", reuse=True):
        calls.append({"wav": str(wav), "lang": lang, "name": name})
        return SUNG

    monkeypatch.setattr(runner, "transcribe_assemblyai", fake)
    monkeypatch.setattr("lyricloom.config.assemblyai_enabled", lambda: enabled)
    return calls


def test_assemblyai_not_called_when_lyrics_found_and_whisper_is_fine(lib, monkeypatch):
    root, _ = lib
    monkeypatch.setattr(runner, "transcribe", lambda *a, **k: SUNG)
    monkeypatch.setattr(runner, "search_all", lambda meta: [Candidate("letras", " ".join([SUNG_TEXT] * 3), score=0.9)])
    calls = _aai(monkeypatch)
    assert runner.process(_flac(root / "a.flac")).status == "done"
    assert calls == []


def test_hallucinated_whisper_uses_assemblyai_to_choose_the_lyrics(lib, monkeypatch):
    root, _ = lib
    monkeypatch.setattr(runner, "transcribe", lambda *a, **k: CREDITS)
    calls = _aai(monkeypatch)
    seen = {}
    real_choose = runner.choose
    monkeypatch.setattr(runner, "choose", lambda c, text, lang: seen.setdefault("text", text) and real_choose(c, text, lang))
    runner.process(_flac(root / "a.flac"))
    assert [c["name"] for c in calls] == ["assemblyai_vocals"]
    assert seen["text"].startswith("texto inventado")


def test_assemblyai_votes_in_transcription_only_songs(lib, monkeypatch):
    root, _ = lib
    calls = _aai(monkeypatch)
    monkeypatch.setattr(runner, "search_all", lambda meta: [])
    monkeypatch.setattr(runner, "to_mono16k", lambda src, dst: None)
    voters = {}
    real_rover = runner.rover
    monkeypatch.setattr(runner, "rover", lambda ts, lang: voters.setdefault("n", len(ts)) and real_rover(ts, lang))
    res = runner.process(_flac(root / "a.flac"))
    assert voters["n"] == 4
    assert [c["name"] for c in calls] == ["assemblyai_vocals"]
    assert res.cloud is True
    assert "cloud transcription used: AssemblyAI" in _track_log(root / "a.flac")


def test_no_assemblyai_when_disabled(lib, monkeypatch):
    root, _ = lib
    calls = _aai(monkeypatch, enabled=False)
    monkeypatch.setattr(runner, "search_all", lambda meta: [])
    monkeypatch.setattr(runner, "to_mono16k", lambda src, dst: None)
    runner.process(_flac(root / "a.flac"))
    assert calls == []


def test_allow_cloud_false_never_calls_the_client(lib, monkeypatch):
    root, _ = lib
    calls = _aai(monkeypatch, enabled=True)
    monkeypatch.setattr(runner, "search_all", lambda meta: [])
    monkeypatch.setattr(runner, "to_mono16k", lambda src, dst: None)
    res = runner.process(_flac(root / "a.flac"), allow_cloud=False)
    assert calls == []
    assert res.cloud is False


def _track_log(audio: Path) -> str:
    from lyricloom import cache

    return (cache.work_dir(audio) / "log.txt").read_text(encoding="utf-8")


def test_hallucination_without_lyrics_or_assemblyai_fails_instead_of_writing_garbage(lib, monkeypatch):
    root, _ = lib
    monkeypatch.setattr(runner, "transcribe", lambda *a, **k: CREDITS)
    _aai(monkeypatch, enabled=False)
    monkeypatch.setattr(runner, "search_all", lambda meta: [])
    res = runner.process(_flac(root / "a.flac"))
    assert res.status == "failed" and "transcription" in res.error
    assert not (root / "a.lrc").exists()


def test_engine_bump_reuses_separation(lib, monkeypatch):
    root, calls = lib
    audio = _flac(root / "a.flac")
    runner.process(audio)
    monkeypatch.setattr(runner, "ENGINE_VERSION", "99")
    assert runner.process(audio).status == "done"
    assert calls["separate"] == 1


def test_stages_are_reported_in_order(lib):
    root, _ = lib
    seen = []
    runner.process(_flac(root / "a.flac"), on_stage=seen.append)
    assert seen == ["lyrics", "separate", "transcribe", "align", "write"]


def test_low_confidence_lines_are_listed_in_the_lrc(lib, monkeypatch):
    root, _ = lib
    monkeypatch.setattr(runner, "align", lambda meta, work, chosen, tr, v, vf=None, cancel=None: AlignResult(
        [Line(0, [Segment("a", 0, 300)], 0.9), Line(500, [Segment("b", 500, 800)], 0.4)], 0.7, True))
    runner.process(_flac(root / "a.flac"))
    assert parse_lrc((root / "a.lrc").read_text(encoding="utf-8")).meta["#review"] == "1"


def _strip_inputs(audio: Path, *stages: str) -> None:
    """Turn stage caches into the shape 2.0 wrote: no `_inputs` fingerprint."""
    for stage in stages:
        path = runner.cache.work_dir(audio) / f"{stage}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("_inputs", None)
        path.write_text(json.dumps(data), encoding="utf-8")


def test_legacy_stage_caches_keep_pasted_lyrics_realign_working(lib):
    """A song finished by 2.0 has no model fingerprints in its caches; Redo/pasted realign must
    reuse separation and transcription instead of asking the user to process the track again."""
    root, calls = lib
    audio = _flac(root / "a.flac")
    runner.process(audio)
    _strip_inputs(audio, "separate", "transcribe")
    before = dict(calls)
    res = runner.realign(audio, "minha letra\ncolada aqui")
    assert res.status == "done" and res.source == "manual"
    assert calls["separate"] == before["separate"]
    assert calls["transcribe"] == before["transcribe"]
    # The reused caches were rewritten with the current fingerprint.
    for stage in ("separate", "transcribe"):
        data = json.loads((runner.cache.work_dir(audio) / f"{stage}.json").read_text(encoding="utf-8"))
        assert "_inputs" in data


def test_legacy_stage_cache_is_not_reused_for_a_per_run_override(lib):
    root, calls = lib
    audio = _flac(root / "a.flac")
    runner.process(audio)
    _strip_inputs(audio, "separate", "transcribe")
    runner.process(audio, force=True, models={"separate": "separator-bs-roformer-vocals"})
    assert calls["separate"] == 2


def test_realign_with_pasted_text_reuses_the_audio_stages(lib, monkeypatch):
    root, calls = lib
    audio = _flac(root / "a.flac")
    runner.process(audio)
    texts = []
    monkeypatch.setattr(
        runner, "align",
        lambda meta, work, chosen, tr, v, vf=None, cancel=None: texts.append(chosen.text) or AlignResult(
            [Line(0, [Segment("x", 0, 300, 0.9)], 0.9)], 0.9, False))
    res = runner.realign(audio, "minha letra\ncolada aqui")
    assert texts == ["minha letra\ncolada aqui"]
    assert res.source == "manual" and calls["separate"] == 1
    assert parse_lrc((root / "a.lrc").read_text(encoding="utf-8")).meta["#source"].startswith("manual")


def test_runner_transcription_fallback(lib, monkeypatch):
    root, _ = lib
    monkeypatch.setattr(runner, "search_all", lambda meta: [])
    res = runner.process(_flac(root / "a.flac"))
    assert res.status == "review" and res.source == "transcription"
    doc = parse_lrc((root / "a.lrc").read_text(encoding="utf-8"))
    assert doc.meta["#source"].startswith("transcription")


def test_transcript_lines_split_on_capitals_and_punctuation():
    # Whisper reports no gaps between sung words, so pauses cannot split lines.
    words = "Texto inventado para o teste Palavras de exemplo Tudo aqui fictício".split()
    tr = Transcript("pt", [Word(w, i * 300, i * 300 + 300, 0.9) for i, w in enumerate(words)])
    assert runner._transcript_candidate(tr).text.splitlines() == [
        "Texto inventado para o teste", "Palavras de exemplo", "Tudo aqui fictício"]
    ja = Transcript("ja", [Word(w, i * 300, i * 300 + 300, 0.9) for i, w in enumerate(["試験が", "歌を", "歌う。", "未来に"])])
    assert runner._transcript_candidate(ja).text.splitlines() == ["試験が歌を歌う。", "未来に"]


def test_transcript_drops_whisper_credit_hallucinations():
    words = "O teste termina agora Obrigado por assistir".split()
    tr = Transcript("pt", [Word(w, i * 300, i * 300 + 300, 0.9) for i, w in enumerate(words)])
    assert runner._transcript_candidate(tr).text.splitlines() == ["O teste termina agora"]


def test_transcript_lines_have_a_max_length():
    tr = Transcript("pt", [Word("la", i * 300, i * 300 + 300, 0.9) for i in range(30)])
    assert max(len(l.split()) for l in runner._transcript_candidate(tr).text.splitlines()) <= 10


def test_find_audio_prunes_a_directory_that_is_a_link_or_junction(tmp_path, monkeypatch):
    root = tmp_path / "library"
    album = root / "album"
    album.mkdir(parents=True)
    song = album / "song.flac"
    song.write_bytes(b"x")
    loop = album / "loop"
    loop.mkdir()
    (loop / "copied.flac").write_bytes(b"x")
    real = runner._is_link_or_junction
    monkeypatch.setattr(runner, "_is_link_or_junction",
                        lambda path: Path(path).name == "loop" or real(path))
    assert runner.find_audio(root) == [song]


def test_find_audio_does_not_descend_into_a_windows_junction(tmp_path):
    if os.name != "nt":
        pytest.skip("junctions are Windows-only")
    root = tmp_path / "library"
    album = root / "album"
    album.mkdir(parents=True)
    song = album / "song.flac"
    song.write_bytes(b"x")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "copied.flac").write_bytes(b"x")
    junction = root / "linked"
    created = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(elsewhere)],
                             capture_output=True, text=True)
    if created.returncode != 0:
        pytest.skip(f"could not create a junction: {created.stderr or created.stdout}")
    assert runner.find_audio(root) == [song]


def test_runner_failed_track_does_not_stop_folder(lib):
    root, _ = lib
    (root / "a_bad.flac").parent.mkdir(parents=True, exist_ok=True)
    (root / "a_bad.flac").write_bytes(b"not audio")
    _flac(root / "b_ok.flac")
    results = runner.process_all(runner.find_audio(root))
    assert [r.status for r in results] == ["failed", "done"]
    assert results[0].error


def test_cli_rejects_outside_library(lib, tmp_path):
    outside = _flac(tmp_path / "_Inbox" / "a.flac")
    assert cli.main(["process", str(outside)]) == 2


def test_cli_processes_folder(lib, capsys):
    root, _ = lib
    _flac(root / "Artist" / "a.flac")
    assert cli.main(["process", str(root)]) == 0
    assert "done" in capsys.readouterr().out


def test_per_song_model_override_is_written_to_the_lrc_and_log(lib):
    root, _ = lib
    audio = _flac(root / "a.flac")
    res = runner.process(audio, models={"transcribe": "whisper-small"})
    assert res.status == "done" and res.models["transcribe"] == "whisper-small"
    doc = parse_lrc((root / "a.lrc").read_text(encoding="utf-8"))
    assert "transcribe=whisper-small" in doc.meta["#models"]
    assert "transcribe=whisper-small" in (runner.cache.work_dir(audio) / "log.txt").read_text(encoding="utf-8")


def test_changing_the_separator_model_recomputes_separation_and_transcription_but_not_lyrics(lib):
    root, calls = lib
    audio = _flac(root / "a.flac")
    runner.process(audio)
    assert calls == {"separate": 1, "transcribe": 1, "align": 1}
    models.use("separate", "separator-bs-roformer-vocals")
    runner.process(audio, force=True)
    assert calls == {"separate": 2, "transcribe": 2, "align": 2}


def test_changing_only_the_align_model_reuses_separation_and_transcription(lib, tmp_path):
    root, calls = lib
    audio = _flac(root / "a.flac")
    runner.process(audio)
    custom = tmp_path / "align.pt"
    custom.write_bytes(b"a custom alignment checkpoint")
    spec = models.add("align", str(custom))
    models.use("align", spec.id)
    runner.process(audio, force=True)
    assert calls == {"separate": 1, "transcribe": 1, "align": 2}


def test_a_missing_model_fails_the_track_before_the_stage_runs(tmp_path, monkeypatch):
    root = tmp_path / "Library"
    monkeypatch.setattr("lyricloom.config.LIBRARY_ROOT", root)
    audio = _flac(root / "a.flac")
    called = []
    monkeypatch.setattr(runner, "search_all", lambda meta: [Candidate("letras", "eu vou", score=0.9)])
    monkeypatch.setattr(runner, "separate", lambda *a, **k: called.append("separate"))
    res = runner.process(audio)
    assert res.status == "failed"
    assert "missing models" in res.error
    assert "separator-mel-band-roformer" in res.error
    assert "lyricloom models download" in res.error
    assert [spec.id for spec in res.missing] == ["separator-mel-band-roformer"]
    assert called == []


def test_an_empty_lyric_search_is_not_cached_and_the_next_run_retries(lib, monkeypatch):
    """R1-08: a first run offline must not pin the track to Whisper text forever."""
    root, _ = lib
    audio = _flac(root / "a.flac")
    calls = []

    def search(meta):
        calls.append(meta.title)
        return [] if len(calls) == 1 else [Candidate("letras", "eu vou", score=0.9)]

    monkeypatch.setattr(runner, "search_all", search)
    first = runner.process(audio)
    assert first.status == "review" and first.source == "transcription"
    assert not (runner.cache.work_dir(audio) / "lyrics.json").exists()
    doc = parse_lrc((root / "a.lrc").read_text(encoding="utf-8"))
    assert doc.meta["#lyrics"] == "search-empty"

    second = runner.process(audio)      # the #lyrics tag makes _already_done retry
    assert second.source == "letras" and second.status == "done"
    assert len(calls) == 2


def test_research_lyrics_reruns_the_search(lib, monkeypatch):
    root, _ = lib
    audio = _flac(root / "a.flac")
    monkeypatch.setattr(runner, "search_all", lambda meta: [])
    runner.process(audio)
    seen = []
    monkeypatch.setattr(runner, "search_all",
                        lambda meta: seen.append(meta.title) or [Candidate("letras", "eu vou", score=0.9)])
    heavy = []
    real_separate, real_transcribe = runner.separate, runner.transcribe
    monkeypatch.setattr(runner, "separate", lambda *a, **k: heavy.append("separate") or real_separate(*a, **k))
    monkeypatch.setattr(runner, "transcribe", lambda *a, **k: heavy.append("transcribe") or real_transcribe(*a, **k))
    result = runner.research_lyrics(audio)
    assert seen and result.source == "letras"
    assert heavy == []   # searching again reuses the separation and transcription caches


def test_a_hallucinated_transcript_forces_review_and_is_reported(lib, monkeypatch):
    """R1-09: a hallucinated anchor must surface in TrackResult.notes and in the .lrc."""
    root, _ = lib
    audio = _flac(root / "a.flac")
    monkeypatch.setattr(runner, "transcribe", lambda *a, **k: CREDITS)
    monkeypatch.setattr(runner, "search_all", lambda meta: [Candidate("letras", "eu vou", score=0.9)])
    res = runner.process(audio)
    assert res.status == "review"
    assert res.notes and "hallucinated" in res.notes[0]
    doc = parse_lrc((root / "a.lrc").read_text(encoding="utf-8"))
    assert "hallucinated" in doc.meta["#warning"]
    assert doc.meta["#review"] == "0"   # every line of the only line is marked for review


def test_a_second_process_is_skipped_while_the_track_lock_is_held(lib):
    root, _ = lib
    audio = _flac(root / "a.flac")
    lock = runner.cache.acquire(audio)
    assert lock is not None
    try:
        res = runner.process(audio)
        assert res.status == "skipped" and "already being processed" in res.error
    finally:
        lock.release()
    assert runner.process(audio).status == "done"


def test_find_audio_skips_kept_vocals_and_work_cache(tmp_path, monkeypatch):
    library = tmp_path / "Library"
    monkeypatch.setattr("lyricloom.config.LIBRARY_ROOT", library)
    monkeypatch.setattr("lyricloom.config.DEFAULT_VOCALS", library / "Vocals")
    monkeypatch.setattr("lyricloom.config.WORK_ROOT", library / "Work")
    song = library / "Artist" / "Album" / "song.flac"
    song.parent.mkdir(parents=True)
    song.write_bytes(b"")
    (song.parent / "song.vocals.flac").write_bytes(b"")
    (library / "Vocals" / "x.flac").parent.mkdir(parents=True)
    (library / "Vocals" / "x.flac").write_bytes(b"")
    (library / "Work" / "y.flac").parent.mkdir(parents=True)
    (library / "Work" / "y.flac").write_bytes(b"")
    assert runner.find_audio(library) == [song]


def test_a_failed_keep_vocals_step_is_only_logged(lib, monkeypatch):
    root, _ = lib
    audio = _flac(root / "a.flac")

    def boom(*args, **kwargs):
        raise OSError("the vocals cache is read-only")

    monkeypatch.setattr(runner, "keep_vocals", boom)
    assert runner.process(audio).status == "done"


def test_cli_exit_code_is_one_when_every_track_failed(lib):
    root, _ = lib
    (root / "bad.flac").parent.mkdir(parents=True, exist_ok=True)
    (root / "bad.flac").write_bytes(b"not audio")
    assert cli.main(["process", str(root)]) == 1


def test_process_language_override_is_logged_and_used(lib, monkeypatch):
    root, _ = lib
    audio = _flac(root / "a.flac")
    seen = {}

    def fake_transcribe(v, w, lang, prompt=None, name="whisper", extra=(), cancel=None):
        seen["lang"] = lang
        return Transcript("pt", [Word("eu", 0, 300, 0.9), Word("vou", 400, 700, 0.9)])

    monkeypatch.setattr(runner, "transcribe", fake_transcribe)
    res = runner.process(audio, lang="zh")
    assert res.status == "done" and seen["lang"] == "zh"
    assert "language override: zh" in (runner.cache.work_dir(audio) / "log.txt").read_text(encoding="utf-8")
    assert parse_lrc((root / "a.lrc").read_text(encoding="utf-8")).meta["#language"] == "zh"
