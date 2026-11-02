from lyricloom.app.model import (apply_edits, delete_line, delete_word, insert_line, insert_word,
                                  merge_with_previous, read_status, scan)
from lyricloom.lrc import parse_lrc
from lyricloom.model import Segment


def _audio(tmp_path, name="01 - Song.flac"):
    p = tmp_path / "Artist" / "2024 - Album" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return p


def test_no_lrc_is_pending(tmp_path):
    row = read_status(_audio(tmp_path))
    assert row.status == "pending" and row.artist == "Artist" and row.title == "01 - Song"


def test_engine_lrc_done_or_review(tmp_path):
    a = _audio(tmp_path)
    a.with_suffix(".lrc").write_text("[re:LyricLoom 1.0.0]\n[#source:netease conf:0.91]\n[00:01.00]x\n", encoding="utf-8")
    row = read_status(a)
    assert (row.status, row.source, row.conf) == ("done", "netease", 0.91)
    a.with_suffix(".lrc").write_text("[re:LyricLoom 1.0.0]\n[#source:netease conf:0.53]\n[#review:2,5]\n[00:01.00]x\n", encoding="utf-8")
    row = read_status(a)
    assert row.status == "review" and row.review_lines == [2, 5]


def test_transcription_is_always_review(tmp_path):
    a = _audio(tmp_path)
    a.with_suffix(".lrc").write_text("[re:LyricLoom 1.0.0]\n[#source:transcription conf:0.80]\n[00:01.00]x\n", encoding="utf-8")
    assert read_status(a).status == "review"


def test_hand_made_lrc_is_other(tmp_path):
    a = _audio(tmp_path)
    a.with_suffix(".lrc").write_text("[00:22.98]試験用の歌詞が流れる\n", encoding="utf-8")
    assert read_status(a).status == "other"


def test_scan_lists_audio_only(tmp_path):
    _audio(tmp_path, "a.flac")
    _audio(tmp_path, "b.mp3")
    (tmp_path / "Artist" / "cover.jpg").write_bytes(b"x")
    assert [r.title for r in scan(tmp_path)] == ["a", "b"]


def test_delete_line_shifts_review_indices():
    doc = parse_lrc("[#review:0,2]\n[00:11.11]Speaker:\n[00:22.60]First line\n[00:25.26]Second line\n")
    out = delete_line(doc, 0)
    assert [l.text for l in out.lines] == ["First line", "Second line"]
    assert out.meta["#review"] == "1"
    assert "#review" not in delete_line(parse_lrc("[#review:0]\n[00:01.00]a\n[00:02.00]b\n"), 0).meta


def test_titles_come_from_the_tags(tmp_path):
    import numpy as np
    import soundfile as sf
    from mutagen.flac import FLAC
    a = tmp_path / "Test Artist" / "Test Album" / "01 - Synthetic Song.flac"
    a.parent.mkdir(parents=True)
    sf.write(str(a), np.zeros(4410, dtype="float32"), 44100, format="FLAC")
    f = FLAC(str(a))
    f["title"], f["artist"] = "Synthetic Song", "Test Artist"
    f.save()
    row = read_status(a)
    assert (row.artist, row.title) == ("Test Artist", "Synthetic Song")


DOC = "[#review:1]\n[00:01.00]<00:01.00>eu <00:01.50>vou<00:02.00>\n[00:05.00]<00:05.00>de <00:05.40>novo<00:06.00>\n"


def test_insert_word_after_selected_gets_the_gap_after_it():
    out = insert_word(parse_lrc(DOC), 0, 0, "já", total_ms=10000)
    segs = out.lines[0].segments
    assert [s.text for s in segs] == ["eu ", "já ", "vou"]
    assert segs[0].start_ms < segs[1].start_ms < segs[2].start_ms
    assert segs[1].start_ms >= segs[0].start_ms


def test_insert_word_at_line_start():
    out = insert_word(parse_lrc(DOC), 1, -1, "e", total_ms=10000)
    assert [s.text for s in out.lines[1].segments] == ["e ", "de ", "novo"]


def test_delete_word_and_empty_line_goes_away():
    out = delete_word(parse_lrc(DOC), 0, 1)
    assert out.lines[0].text == "eu"
    out = delete_word(out, 0, 0)
    assert [l.text for l in out.lines] == ["de novo"] and out.meta["#review"] == "0"


def test_insert_line_spreads_word_times_and_shifts_review():
    out = insert_line(parse_lrc(DOC), 0, "nova linha aqui", 2500, 4500, total_ms=10000)
    assert [l.text for l in out.lines] == ["eu vou", "nova linha aqui", "de novo"]
    starts = [s.start_ms for s in out.lines[1].segments]
    assert starts[0] == 2500 and starts == sorted(starts) and out.lines[1].segments[-1].end_ms <= 4500
    assert out.meta["#review"] == "2"


def test_insert_japanese_line_splits_into_segments():
    out = insert_line(parse_lrc(DOC), 1, "試験が歌を", 7000, 9000, total_ms=10000)
    assert [s.text for s in out.lines[2].segments] == ["試験", "が", "歌", "を"]


def test_merge_with_line_above_keeps_word_times():
    doc = parse_lrc("[#review:1,2]\n[00:01.00]<00:01.00>Texto <00:01.40>de<00:02.00>\n"
                    "[00:02.10]<00:02.10>teste<00:02.60>\n[00:05.00]<00:05.00>outra<00:06.00>\n")
    out = merge_with_previous(doc, 1)
    assert [l.text for l in out.lines] == ["Texto de teste", "outra"]
    assert [s.start_ms for s in out.lines[0].segments] == [1000, 1400, 2100]
    assert out.meta["#review"] == "0,1"


def test_merge_japanese_adds_no_space():
    doc = parse_lrc("[00:01.00]<00:01.00>試験<00:01.50>\n[00:02.00]<00:02.00>が<00:02.30>\n")
    assert merge_with_previous(doc, 1).lines[0].text == "試験が"


def test_merge_first_line_does_nothing():
    doc = parse_lrc(DOC)
    assert merge_with_previous(doc, 0) is doc


def test_progress_moves_inside_a_stage_and_never_finishes_early():
    from lyricloom.app.model import track_progress
    a = track_progress("separate", 0, 240)
    b = track_progress("separate", 300, 240)
    c = track_progress("separate", 99999, 240)
    assert 0 < a < b < c < track_progress("transcribe", 0, 240)   # moves, and stays inside its slice
    assert track_progress("write", 99999, 240) < 1.0               # 100% only when the track is done


def test_progress_stages_are_in_order():
    from lyricloom.app.model import track_progress
    starts = [track_progress(s, 0, 240) for s in ("lyrics", "separate", "transcribe", "align", "write")]
    assert starts == sorted(starts) and starts[0] == 0.0


def test_apply_edits_keeps_times_ordered():
    doc = parse_lrc("[00:01.00]<00:01.00>a <00:01.50>b<00:02.00>\n[00:03.00]<00:03.00>c<00:03.50>\n")
    # user drags "b" before "a": refine must restore order
    edited = apply_edits(doc, 0, [Segment("a ", 1000, 1500), Segment("b", 900, 2000)], total_ms=10000)
    starts = [s.start_ms for l in edited.lines for s in l.segments]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)
    assert edited.lines[1].segments[0].start_ms == 3000   # other lines untouched
