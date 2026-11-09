import json
from pathlib import Path

from lyricloom.lyrics.sources import genius, lrclib, netease, qq, utaten
from lyricloom.lyrics.sources.base import lrc_to_text_and_lines

FX = Path(__file__).resolve().parent.parent / "fixtures" / "sources"


def _json(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def _html(name):
    return (FX / name).read_text(encoding="utf-8")


def test_lrc_to_text_and_lines_drops_tags_and_sorts():
    text, lines = lrc_to_text_and_lines("[ti:x]\n[00:05.00]b\n[00:01.50]a\n[00:09.00]\n")
    assert text == "a\nb"
    assert [l.start_ms for l in lines] == [1500, 5000]


def test_lrclib_keeps_its_synced_line_timing():
    out = lrclib.parse([{"id": 1, "trackName": "Synthetic Song", "artistName": "Test Artist",
                         "duration": 200, "plainLyrics": "line a\nline b",
                         "syncedLyrics": "[00:01.00]line a\n[00:05.00]line b\n"}])
    assert out[0].synced is not None
    assert [l.start_ms for l in out[0].synced] == [1000, 5000]


def test_netease_lyric_is_synthetic_and_skips_translation():
    text, synced = netease.parse_lyric(_json("netease/lyric.json"))
    assert text.splitlines()[0] == "試験用の歌詞が流れる"
    assert synced is None  # this fixture has no yrc
    assert "这是测试用的歌词" not in text  # tlyric is a translation, not sung
    assert "Test Writer" not in text  # credit lines are metadata, not lyrics


def test_netease_yrc_words():
    lines = netease.parse_yrc("[22980,2500](22980,430,0)テスト(23410,210,0)です")
    assert lines[0].start_ms == 22980
    assert [(s.text, s.start_ms, s.end_ms) for s in lines[0].segments] == [("テスト", 22980, 23410), ("です", 23410, 23620)]


def test_qq_search_and_lyric():
    songs = qq.parse_search(_json("qq/search.json"))
    assert songs[1]["songname"] == "Synthetic Song"
    text = qq.parse_lyric(_json("qq/lyric.json"))
    assert text  # non-empty text, tags stripped
    assert "[ti:" not in text
    assert "This is a synthetic line for the parser" in text


def test_qq_drops_title_artist_line():
    data = {"lyric": "[00:00.32]Synthetic Song - Test Artist\n[00:22.98]試験用の歌詞"}
    assert qq.parse_lyric(data, "Synthetic Song", "Test Artist") == "試験用の歌詞"


def test_genius_search_skips_romanizations_and_translations():
    urls = [h["url"] for h in genius.parse_search(_json("genius/search.json"))]
    assert "https://genius.com/Test-singer-synthetic-song-lyrics" in urls
    assert not any("romanizations" in u.lower() for u in urls)
    assert not any("translation" in u.lower() for u in urls)


def test_genius_page_lyrics():
    text = genius.parse_page(_html("genius/page.html"))
    assert "試験用の歌詞が流れる" in text
    assert "[Verse 1]" not in text
    assert not text.splitlines()[0].startswith("[")
    assert "この注釈は選択から除外される" not in text


def test_utaten_search_and_page():
    assert utaten.parse_search(_html("utaten/search.html"))[0] == "/lyric/hw00000001/"
    title, artist, text = utaten.parse_page(_html("utaten/page.html"))
    assert title == "Synthetic Song"
    assert artist == "テスト歌手"
    assert text.splitlines()[0] == "試験用の歌詞が流れる"
    assert "しけん" not in text  # furigana removed
    assert "かし" not in text
