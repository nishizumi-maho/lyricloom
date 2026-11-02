from lyricloom.lrc import format_lrc, format_ts, parse_lrc
from lyricloom.model import Segment

JA = "[00:22.98]<00:22.98>試験<00:23.41>が<00:23.62>歌<00:25.50>"


def test_japanese_no_spaces():
    line = parse_lrc(JA).lines[0]
    assert line.text == "試験が歌"
    assert [s.start_ms for s in line.segments] == [22980, 23410, 23620]
    assert line.segments[-1].end_ms == 25500 and line.segments[0].end_ms == 23410


def test_latin_spaces_are_text():
    line = parse_lrc("[00:01.00]<00:01.00>eu <00:01.50>vou<00:02.00>").lines[0]
    assert line.text == "eu vou"


def test_line_only_kept():
    line = parse_lrc("[00:05.00]sem palavras").lines[0]
    assert line.start_ms == 5000 and line.segments == [Segment("sem palavras", None, None)]


def test_metadata_and_roundtrip():
    src = "[ti:Synthetic Song]\n[re:LyricLoom 1.0]\n[#source:uta-net conf:0.94]\n" + JA + "\n"
    doc = parse_lrc(src)
    assert doc.meta == {"ti": "Synthetic Song", "re": "LyricLoom 1.0", "#source": "uta-net conf:0.94"}
    assert format_lrc(doc) == src


def test_line_only_roundtrip():
    src = "[00:05.00]sem palavras\n"
    assert format_lrc(parse_lrc(src)) == src


def test_format_ts_rounding():
    assert format_ts(83456) == "01:23.46" and format_ts(0) == "00:00.00"
