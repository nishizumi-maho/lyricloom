from lyricloom import config
from lyricloom.lrc import parse_lrc
from lyricloom.model import Line, LrcDoc, Segment
from lyricloom.stages.write import apply_script_preference, japanese_path, romaji_path, write_lyrics


def _ja_doc():
    return LrcDoc({"ti": "Synthetic Song", "#review": "0"},
                  [Line(1000, [Segment("試験が", 1000, 1400), Segment("歌を", 1400, 1800), Segment("歌う。", 1800, 2300)])])


def _read(p):
    return parse_lrc(p.read_text(encoding="utf-8"))


def test_japanese_lyrics_are_written_in_both_scripts(tmp_path):
    audio = tmp_path / "a.flac"
    write_lyrics(audio, _ja_doc())
    ja, ro = _read(japanese_path(audio)), _read(romaji_path(audio))
    assert ja.lines[0].text == "試験が歌を歌う。"
    assert ro.lines[0].text.startswith("shikenga utawo")
    assert [s.start_ms for s in ro.lines[0].segments] == [1000, 1400, 1800]   # same word timing
    assert ro.meta["#review"] == "0"
    assert (audio.with_suffix(".lrc")).read_text(encoding="utf-8") == japanese_path(audio).read_text(encoding="utf-8")


def test_romaji_preference_puts_romaji_in_the_lrc(tmp_path):
    config.set_japanese_script("romaji")
    audio = tmp_path / "a.flac"
    write_lyrics(audio, _ja_doc())
    assert _read(audio.with_suffix(".lrc")).lines[0].text.startswith("shikenga")


def test_changing_the_preference_rewrites_processed_songs_without_backups(tmp_path):
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"")
    write_lyrics(audio, _ja_doc())
    config.set_japanese_script("romaji")
    assert apply_script_preference(tmp_path) == 1
    assert _read(audio.with_suffix(".lrc")).lines[0].text.startswith("shikenga")
    assert not list(tmp_path.glob("*.bak*"))


def test_songs_processed_before_get_both_scripts_when_the_preference_is_applied(tmp_path):
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"")
    (tmp_path / "a.aai-anchors.lrc").write_text("[#engine:5]\n[00:01.00]試験が", encoding="utf-8")   # not a song
    audio.with_suffix(".lrc").write_text("[re:LYRICS BOCA 1.0.0]\n[#engine:5]\n[00:01.00]<00:01.00>試験が<00:01.40>歌を<00:01.80>", encoding="utf-8")
    config.set_japanese_script("romaji")
    apply_script_preference(tmp_path)
    assert japanese_path(audio).exists() and _read(japanese_path(audio)).lines[0].text == "試験が歌を"
    assert _read(audio.with_suffix(".lrc")).lines[0].text.startswith("shikenga")
    assert not (tmp_path / "a.aai-anchors.japanese.lrc").exists()


def test_latin_lyrics_get_only_the_lrc(tmp_path):
    audio = tmp_path / "a.flac"
    write_lyrics(audio, LrcDoc({}, [Line(0, [Segment("eu ", 0, 300), Segment("vou", 300, 600)])]))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.lrc"]
