from pathlib import Path

from lyricloom.lyrics.clean import clean_lyrics
from lyricloom.lyrics.score import choose, duration_score, score_meta, score_transcript
from lyricloom.model import Candidate, TrackMeta

META = TrackMeta(Path("x.flac"), "Test Artist", "Synthetic Song (Test Version)", "Synthetic Song", 238.6, "pt")


def test_clean_removes_credits():
    assert clean_lyrics("作詞：Test Writer\n試験が") == "試験が"
    assert clean_lyrics("Lyrics by: Test Writer\ninvented line") == "invented line"


def test_clean_removes_chinese_credits():
    assert clean_lyrics("词：Test Writer\n曲：Test Composer\n编曲：Test Arranger\n試験が") == "試験が"


def test_clean_keeps_chorus_parens():
    assert clean_lyrics("invented line (test line)\n") == "invented line (test line)"


def test_clean_drops_urls_and_double_blank_lines():
    assert clean_lyrics("a\n\n\n\nb\nhttps://site.com/x") == "a\n\nb"


def test_duration_score_edges():
    assert duration_score(238.6, 240.6) == 1.0
    assert duration_score(238.6, 263.6) == 0.0
    assert 0.0 < duration_score(238.6, 250.0) < 1.0


def test_score_meta_title_suffix_ignored():
    c = Candidate("letras", "x")
    assert score_meta(c, META, "Synthetic Song", "Test Artist", 238.0) > 0.9


def test_choose_prefers_transcript_match():
    good = Candidate("letras", "texto inventado para o teste", score=0.8)
    bad = Candidate("genius", "outra coisa qualquer aqui", score=0.8)
    assert choose([bad, good], "texto inventado para o teste", "pt") is good


def test_choose_rejects_other_lyrics_even_with_a_perfect_title():
    # another song's lyrics can score well on metadata alone
    other = Candidate("websearch", "palavras completamente diferentes sobre outro assunto sem relação alguma", score=1.0)
    assert choose([other], "texto inventado para o teste", "pt") is None


def test_without_a_transcript_only_a_near_perfect_title_is_accepted():
    good = Candidate("netease", "試験が歌を", score=0.95)
    weak = Candidate("websearch", "試験が歌を", score=0.7)
    assert choose([good], "", "ja") is good
    assert choose([weak], "", "ja") is None


def test_choose_none_below_threshold():
    c = Candidate("websearch", "nada a ver", score=0.1)
    assert choose([c], "texto inventado para o teste", "pt") is None


def test_empty_phonetics_never_score_as_a_perfect_match():
    """Korean, Chinese and Cyrillic have no reading in this build: both sides became "" and
    rapidfuzz scored that as 100 (R1-02)."""
    for text in ("사랑은 언제나", "孤勇者", "Я люблю тебя"):
        assert score_transcript(Candidate("netease", text), text, "other") == 0.0
    assert score_transcript(Candidate("netease", "孤勇者"), "孤勇者", "zh") == 0.0


def test_choose_does_not_accept_a_non_latin_song_on_an_empty_transcript():
    wrong = Candidate("netease", "孤勇者", score=0.8)
    assert choose([wrong], "孤勇者", "other") is None
    assert choose([Candidate("netease", "Я люблю тебя", score=0.8)], "Я люблю тебя", "other") is None


def test_a_two_letter_candidate_cannot_match_everything():
    assert score_transcript(Candidate("websearch", "ab"), "ab", "other") == 0.0
    assert score_transcript(Candidate("websearch", "ab"), "texto inventado para o teste", "pt") == 0.0


def test_missing_artist_does_not_reject_an_exact_title_and_duration_without_a_transcript():
    meta = TrackMeta(Path("x.flac"), "", "Synthetic Song", "", 238.6, "other")
    good = Candidate("netease", "qualquer letra")
    good.score = score_meta(good, meta, "Synthetic Song", "", 238.0)
    assert good.score >= 0.85
    assert choose([good], "", "other") is good

    wrong = Candidate("netease", "qualquer letra")
    wrong.score = score_meta(wrong, meta, "A Different Song", "", 238.0)
    assert choose([wrong], "", "other") is None
