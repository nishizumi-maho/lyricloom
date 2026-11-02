from lyricloom.text import reading, split_line
from lyricloom.text.mms import to_mms_tokens


def test_split_concat_identity():
    for line, lang in [
        ("試験用の歌詞が流れる", "ja"),
        ("空と海が色を変える", "ja"),
        ("Texto inventado, para o teste!", "pt"),
    ]:
        assert "".join(split_line(line, lang)) == line


def test_split_japanese_particles():
    assert split_line("試験が歌を", "ja") == ["試験", "が", "歌", "を"]


def test_split_latin_keeps_space():
    assert split_line("eu vou", "pt") == ["eu ", "vou"]


def test_reading():
    assert reading("試験", "ja") == "shiken"
    assert reading("coração", "pt") == "coracao"


def test_punctuation_never_stands_alone():
    for line in ["これは「テスト」です", "歌って さぁ、進もう", "ほかでもない”試験”"]:
        parts = split_line(line, "ja")
        assert "".join(parts) == line
        assert all(to_mms_tokens(reading(p, "ja")) for p in parts), parts


def test_furigana_stays_with_its_kanji_and_gives_the_reading():
    parts = split_line("この試験(しけん)の歌でも", "ja")
    assert "".join(parts) == "この試験(しけん)の歌でも"
    seg = next(p for p in parts if "試験" in p)
    assert "(しけん)" in seg
    assert reading(seg, "ja").startswith("shiken")
    assert reading("歌(うた)う", "ja") == "utau"


def test_mms_tokens():
    assert to_mms_tokens("kotoba!") == "kotoba"
    assert to_mms_tokens("…") == ""
