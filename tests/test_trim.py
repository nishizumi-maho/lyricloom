import numpy as np
import soundfile as sf

from lyricloom.align.trim import trim_line_ends
from lyricloom.model import Line, Segment

SR = 16000


def _vocals(tmp_path, sung):
    """Noise wherever `sung` (list of (start_ms, end_ms)) says the voice is, near silence elsewhere."""
    audio = np.random.default_rng(1).normal(0, 0.0005, SR * 12).astype(np.float32)
    for a, b in sung:
        audio[a * SR // 1000: b * SR // 1000] += np.random.default_rng(a).normal(0, 0.2, (b - a) * SR // 1000)
    path = tmp_path / "vocals16k.wav"
    sf.write(str(path), audio, SR, subtype="PCM_16")
    return path


def test_last_word_ends_where_the_voice_stops(tmp_path):
    # sung 1.0-3.2 s, then an instrumental; the aligner stretched the last word to 9 s
    path = _vocals(tmp_path, [(1000, 3200)])
    line = Line(1000, [Segment("a ", 1000, 2000), Segment("b", 2000, 9000)])
    trim_line_ends([line], path)
    assert 3100 <= line.segments[-1].end_ms <= 3400


def test_end_already_right_is_kept(tmp_path):
    path = _vocals(tmp_path, [(1000, 3200), (3300, 6000)])
    line = Line(1000, [Segment("a ", 1000, 2000), Segment("b", 2000, 3000)])
    trim_line_ends([line], path)
    assert line.segments[-1].end_ms == 3000


def test_word_keeps_a_minimum_length(tmp_path):
    path = _vocals(tmp_path, [(1000, 2000)])
    line = Line(1000, [Segment("a ", 1000, 1900), Segment("b", 1950, 8000)])
    trim_line_ends([line], path)
    assert line.segments[-1].end_ms >= 1950 + 150


def test_unaligned_lines_are_left_alone(tmp_path):
    path = _vocals(tmp_path, [(1000, 2000)])
    line = Line(1000, [Segment("text", None, None)])
    trim_line_ends([line], path)
    assert line.segments[0].end_ms is None
