import pytest

from lyricloom.align.confidence import REVIEW_THRESHOLD, line_conf, track_conf
from lyricloom.align.merge import merge_presync
from lyricloom.align.refine import refine
from lyricloom.model import Line, Segment


def _line(start, segs, conf=0.8):
    return Line(start, [Segment(t, s, e) for t, s, e in segs], conf)


OURS = _line(1000, [("試験", 1000, 1400), ("が", 1400, 1600)])


def test_presync_kept_when_close():
    pre = _line(1080, [("試験", 1080, 1480), ("が", 1480, 1700)])
    out = merge_presync([OURS], [pre])
    assert out[0].segments[0].start_ms == 1080
    assert out[0].conf == pytest.approx(0.9)


def test_presync_replaced_when_far():
    pre = _line(1300, [("試験", 1300, 1700), ("が", 1700, 1900)])
    assert merge_presync([OURS], [pre])[0].segments[0].start_ms == 1000


def test_presync_with_other_segmentation_compared_by_text_position():
    pre = _line(1050, [("試験が", 1050, 1650)])
    assert merge_presync([OURS], [pre])[0].segments[0].start_ms == 1050


def test_presync_ignored_for_different_text():
    pre = _line(1000, [("別の試験", 1000, 1600)])
    assert merge_presync([OURS], [pre])[0] is OURS


def test_line_only_presync_uses_its_line_start_without_inventing_word_times():
    """A plain LRC source has no word segments; only its line start can be used (R1-13)."""
    pre = Line(1080, [Segment("試験が", None, None)])
    out = merge_presync([OURS], [pre])
    assert out[0].start_ms == 1080
    assert [s.start_ms for s in out[0].segments] == [1000, 1400]   # CTC word timing is kept
    assert out[0].conf == pytest.approx(0.9)


def test_refine_monotonic():
    lines = [_line(1000, [("a ", 1000, 1500), ("b", 1000, 1200)]), _line(900, [("c", 900, 2000)])]
    out = refine(lines, 10000)
    starts = [s.start_ms for l in out for s in l.segments]
    assert all(a < b for a, b in zip(starts, starts[1:]))
    segs = [s for l in out for s in l.segments]
    assert all(s.end_ms <= n.start_ms for s, n in zip(segs, segs[1:]))


def test_refine_clamps_to_track_length():
    out = refine([_line(9000, [("a", 9000, 12000)])], 10000)
    assert out[0].segments[0].end_ms == 10000


def test_refine_unaligned_line_becomes_line_only():
    lines = [_line(1000, [("a", 1000, 1500)]), Line(None, [Segment("b ", None, None), Segment("c", None, None)]),
             _line(5000, [("d", 5000, 5500)])]
    out = refine(lines, 10000)
    mid = out[1]
    assert mid.segments == [Segment("b c", None, None)]
    assert 1500 <= mid.start_ms < 5000


def test_line_conf_and_review_flag():
    assert line_conf([0.9, 0.7], None) == pytest.approx(0.8)
    assert line_conf([0.4], 1.0) == pytest.approx(0.64)
    lines = [_line(0, [("a", 0, 1000)], conf=0.9), _line(1000, [("b", 1000, 4000)], conf=0.4)]
    assert track_conf(lines) == pytest.approx((0.9 * 1000 + 0.4 * 3000) / 4000)
    assert lines[1].conf < REVIEW_THRESHOLD <= lines[0].conf
