from pathlib import Path

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
