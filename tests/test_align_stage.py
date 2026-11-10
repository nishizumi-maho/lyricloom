from pathlib import Path

import pytest

from lyricloom.model import Candidate, Line, Segment, TrackMeta, Transcript, Word
from lyricloom.stages import align as stage

META = TrackMeta(Path("x.flac"), "A", "T", "", 20.0, "other")


def _fake_ctc(score):
    def fake(vocals16k, blocks, seg_tokens, cancel=None):
        out, t = [], 1000
        for block in seg_tokens:
            for line in block:
                segs = []
                for tok in line:
                    segs.append(None if not tok else Segment("", t, t + 300, score))
                    t += 400
                out.append(segs)
        return out
    return fake


def test_align_builds_word_timed_lines(monkeypatch):
    monkeypatch.setattr(stage, "align_blocks", _fake_ctc(0.9))
    tr = Transcript("pt", [Word("eu", 1000, 1300, 0.9), Word("vou", 1400, 1700, 0.9)])
    res = stage.align(META, Path("."), Candidate("letras", "eu vou\n\nde novo"), tr, Path("v.wav"))
    assert [l.text for l in res.lines] == ["eu vou", "de novo"]
    assert [s.text for s in res.lines[0].segments] == ["eu ", "vou"]
    assert res.lines[0].start_ms == 1000 and not res.review


def test_align_flags_review_on_low_confidence(monkeypatch):
    monkeypatch.setattr(stage, "align_blocks", _fake_ctc(0.3))
    res = stage.align(META, Path("."), Candidate("letras", "eu vou"), Transcript("pt", []), Path("v.wav"))
    assert res.review and res.track_conf < 0.6


def test_align_uses_close_presync(monkeypatch):
    monkeypatch.setattr(stage, "align_blocks", _fake_ctc(0.9))
    pre = [Line(1050, [Segment("eu ", 1050, 1400), Segment("vou", 1400, 1750)])]
    res = stage.align(META, Path("."), Candidate("netease", "eu vou", synced=pre), Transcript("pt", []), Path("v.wav"))
    assert res.lines[0].segments[0].start_ms == 1050


@pytest.mark.parametrize("text,lang,script", [
    ("孤勇者", "zh", "Chinese (Han)"),
    ("사랑은 언제나", "ko", "Korean (Hangul)"),
    ("Я люблю тебя", "ru", "Russian (Cyrillic)"),
])
def test_unsupported_scripts_get_line_timing_review_and_a_note(monkeypatch, text, lang, script):
    """R1-11: never run a whole-song CTC attempt that silently returns no words."""
    def no_ctc(*args, **kwargs):
        raise AssertionError("the CTC aligner must not run for an unsupported script")

    monkeypatch.setattr(stage, "align_blocks", no_ctc)
    meta = TrackMeta(Path("x.flac"), "A", "T", "", 20.0, lang)
    res = stage.align(meta, Path("."), Candidate("netease", text), Transcript(lang, []), Path("v.wav"))
    assert res.review is True
    assert script in res.notes[0]
    assert res.lines[0].start_ms == 0
    assert all(s.start_ms is None for s in res.lines[0].segments)


def test_a_successful_singing_alignment_does_not_report_the_ctc_model(monkeypatch):
    """FR-A-04: [#models] must name the model that actually timed the words."""
    def good_mtl(vocals, seg_texts, cancel=None):
        out, t = [], 1000
        for line in seg_texts:
            row = []
            for _ in line:
                row.append(Segment("", t, t + 300, 1.0))
                t += 400
            out.append(row)
        return out

    monkeypatch.setattr(stage, "align_lines_mtl", good_mtl)
    monkeypatch.setattr(stage.models, "singing_ready", lambda lang=None: True)
    tr = Transcript("en", [Word("hello", 1000, 1300, 0.9), Word("world", 1400, 1700, 0.9)])
    res = stage.align(META, Path("."), Candidate("netease", "hello world"), tr,
                      Path("v16.wav"), Path("v.wav"))
    assert res.models_used.get("singing") == "singing-mtl"
    assert "align" not in res.models_used


def test_a_bad_singing_model_alignment_falls_back_to_ctc_and_review(monkeypatch):
    calls = []

    def bad_mtl(vocals, seg_texts, cancel=None):
        return [[Segment("", 50_000 + 400 * i, 50_300 + 400 * i, 1.0) for i, _ in enumerate(line)]
                for line in seg_texts]

    def fake_ctc(vocals16k, bs, seg_tokens, cancel=None):
        calls.append("ctc")
        return [[Segment("", 1000 + 400 * i, 1300 + 400 * i, 0.9) for i, _ in enumerate(line)]
                for block in seg_tokens for line in block]

    monkeypatch.setattr(stage, "align_lines_mtl", bad_mtl)
    monkeypatch.setattr(stage, "align_blocks", fake_ctc)
    monkeypatch.setattr(stage.models, "singing_ready", lambda lang=None: True)
    tr = Transcript("en", [Word("texto", 1000, 1300, 0.9), Word("inventado", 1400, 1700, 0.9),
                           Word("para", 1800, 2100, 0.9)])
    res = stage.align(META, Path("."), Candidate("netease", "texto inventado para"), tr,
                      Path("v16.wav"), Path("v.wav"))
    assert calls == ["ctc"]
    assert res.models_used.get("align") == "align-mms-fa"
    assert "singing" not in res.models_used
    assert res.review is True and res.notes and "sanity check" in res.notes[0]
