import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lyricloom.app.karaoke import KaraokeWindow  # noqa: E402
from lyricloom.lrc import parse_lrc  # noqa: E402
from lyricloom.model import Line, Segment  # noqa: E402

LRC = ("[00:01.00]<00:01.00>eu <00:01.50>vou<00:02.00>\n"
       "[00:03.00]<00:03.00>de <00:03.40>novo<00:04.00>\n")


def test_current_line_index():
    lines = parse_lrc(LRC).lines
    assert KaraokeWindow._current_line_index(lines, 999) == -1
    assert KaraokeWindow._current_line_index(lines, 1000) == 0
    assert KaraokeWindow._current_line_index(lines, 2999) == 0
    assert KaraokeWindow._current_line_index(lines, 3000) == 1
    assert KaraokeWindow._current_line_index(lines, 99999) == 1


def test_word_state():
    word = Segment("vou", 1000, 2000)
    assert KaraokeWindow._word_state(word, 999) == "future"
    assert KaraokeWindow._word_state(word, 1000) == "active"
    assert KaraokeWindow._word_state(word, 1999) == "active"
    assert KaraokeWindow._word_state(word, 2000) == "past"
    assert KaraokeWindow._word_state(Segment("line only", None, None), 0) == "past"


def test_word_state_uses_the_next_word_when_end_is_missing():
    word = Segment("novo", 3000, None)
    assert KaraokeWindow._word_state(word, 3500, 4000) == "active"
    assert KaraokeWindow._word_state(word, 4000, 4000) == "past"


def test_line_html_escapes_lyrics():
    line = Line(0, [Segment("<b>&", 0, 1000), Segment(" ok", 1000, 2000)])
    markup = KaraokeWindow._line_html(line, 500, None)
    assert "&lt;b&gt;&amp;" in markup
    assert "<b>" not in markup
    assert "#ffd166" in markup      # the first word is being sung
    assert "#657199" in markup      # the second one is still dim
