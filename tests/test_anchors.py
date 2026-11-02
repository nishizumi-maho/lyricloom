from lyricloom.align.anchors import Block, blocks, find_anchors
from lyricloom.model import Word


def _words(spec):
    """spec: list of (text, start_ms); each word lasts 300 ms."""
    return [Word(t, s, s + 300, 0.9) for t, s in spec]


def test_exact_match_all_anchors():
    lines = ["texto inventado aqui", "para o teste"]
    words = _words([("texto", 1000), ("inventado", 1400), ("aqui", 1800), ("para", 5000), ("o", 5400), ("teste", 5800)])
    a = find_anchors(lines, "pt", words)
    assert [x.line_idx for x in a] == [0, 1]
    assert (a[0].start_ms, a[0].end_ms) == (1000, 2100)
    assert a[1].start_ms == 5000


def test_repeated_chorus_ordered():
    chorus = "texto inventado"
    lines = [chorus, "outra estrofe aqui", chorus]
    words = _words([("texto", 10000), ("inventado", 10400),
                    ("outra", 30000), ("estrofe", 30400), ("aqui", 30800),
                    ("texto", 60000), ("inventado", 60400)])
    a = {x.line_idx: x for x in find_anchors(lines, "pt", words)}
    assert a[0].start_ms == 10000
    assert a[2].start_ms >= 60000


def test_missing_line_no_anchor():
    lines = ["texto inventado aqui", "linha ausente do teste", "para o teste"]
    words = _words([("texto", 1000), ("inventado", 1400), ("aqui", 1800), ("para", 5000), ("o", 5400), ("teste", 5800)])
    a = {x.line_idx: x for x in find_anchors(lines, "pt", words)}
    assert 1 not in a
    assert a[0].start_ms == 1000 and a[2].start_ms == 5000


def test_japanese_lines_match_romanized_transcript():
    lines = ["試験が歌を"]
    words = _words([("試験が", 22980), ("歌を", 23600)])
    a = find_anchors(lines, "ja", words)
    assert [x.line_idx for x in a] == [0]


def test_blocks_cover_all_lines():
    lines = ["a a a", "b b b", "c c c", "d d d"]
    words = _words([("b", 5000), ("b", 5300), ("b", 5600), ("d", 20000), ("d", 20300), ("d", 20600)])
    anchors = find_anchors(lines, "pt", words)
    bs = blocks(anchors, len(lines), 30000)
    assert bs[0].line_start == 0 and bs[-1].line_end == len(lines)
    assert all(x.line_end == y.line_start for x, y in zip(bs, bs[1:]))
    assert bs[0].start_ms == 0 and bs[-1].end_ms == 30000
    assert all(isinstance(b, Block) and b.start_ms < b.end_ms for b in bs)


def test_blocks_without_anchors_is_one_block():
    assert blocks([], 3, 9000) == [Block(0, 3, 0, 9000)]
