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


_WORDS = ["alpha beta", "gamma delta", "epsilon zeta", "eta theta",
          "iota kappa", "lambda mu", "nu xi", "omicron pi"]
_LONG = TrackMeta(Path("x.flac"), "A", "T", "", 120.0, "other")


def _heard(line_starts):
    """Whisper heard every line: two words per line, starting at the given times."""
    words = []
    for text, start in zip(_WORDS, line_starts):
        first, second = text.split()
        words += [Word(first, start, start + 400, 0.9), Word(second, start + 600, start + 1000, 0.9)]
    return Transcript("en", words)


def _sung(line_starts, offsets):
    def mtl(vocals, seg_texts, cancel=None):
        return [[Segment("", s + o, s + o + 400, 1.0), Segment("", s + o + 600, s + o + 1000, 1.0)]
                for s, o in zip(line_starts, offsets)]
    return mtl


def test_singing_alignment_is_kept_when_only_whispers_usual_timing_error_disagrees(monkeypatch):
    """Real data (Adele, 2026-11-10): the singing model and MMS agreed within ~0.1 s, while Whisper's
    anchors started most lines 0.3-0.7 s early and the first line 5.7 s early. That is Whisper's
    timing error on sung vocals, not a broken alignment, so the singing model must be kept."""
    starts = [5000 + 10_000 * k for k in range(len(_WORDS))]
    ctc_calls = []
    monkeypatch.setattr(stage, "align_lines_mtl", _sung(starts, [5700] + [600] * (len(_WORDS) - 1)))
    monkeypatch.setattr(stage, "align_blocks", lambda *a, **k: ctc_calls.append(1) or [])
    monkeypatch.setattr(stage.models, "singing_ready", lambda lang=None: True)
    res = stage.align(_LONG, Path("."), Candidate("netease", "\n".join(_WORDS)), _heard(starts),
                      Path("v16.wav"), Path("v.wav"))
    assert ctc_calls == []
    assert res.models_used.get("singing") == "singing-mtl" and "align" not in res.models_used
    assert not res.notes


def test_a_singing_alignment_shifted_by_one_line_falls_back_to_ctc(monkeypatch):
    """Each line gets the next line's timing: a broken alignment the check must still catch."""
    starts = [5000 + 10_000 * k for k in range(len(_WORDS))]
    shifted = [s for s in starts[1:]] + [starts[-1] + 10_000]
    monkeypatch.setattr(stage, "align_lines_mtl", _sung(shifted, [0] * len(_WORDS)))
    monkeypatch.setattr(stage, "align_blocks", _fake_ctc(0.9))
    monkeypatch.setattr(stage.models, "singing_ready", lambda lang=None: True)
    res = stage.align(_LONG, Path("."), Candidate("netease", "\n".join(_WORDS)), _heard(starts),
                      Path("v16.wav"), Path("v.wav"))
    assert "singing" not in res.models_used and res.models_used.get("align") == "align-mms-fa"
    assert res.review is True and "sanity check" in res.notes[0]
