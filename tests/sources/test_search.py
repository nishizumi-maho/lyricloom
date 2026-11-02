from pathlib import Path

from lyricloom.lyrics import search
from lyricloom.lyrics.sources import lrclib, websearch
from lyricloom.lyrics.sources.base import RawResult, SourceBlocked
from lyricloom.model import TrackMeta

META = TrackMeta(Path("x.flac"), "Test Artist", "Synthetic Song (Test Version)", "Synthetic Song", 238.6, "other")
FX = Path(__file__).resolve().parent.parent / "fixtures" / "sources"


def test_title_variants_strip_suffix():
    v = search.title_variants(META)
    assert v[0] == "Synthetic Song (Test Version)" and "Synthetic Song" in v


class _Ok:
    name = "letras"

    def search(self, meta, client):
        return [RawResult("Synthetic Song", "Test Artist", 238.0, "作詞：Test Writer\ninvented line", None, "u")]


class _Boom:
    name = "genius"

    def search(self, meta, client):
        raise RuntimeError("down")


class _Blocked:
    name = "uta-net"

    def search(self, meta, client):
        raise SourceBlocked("403")


def test_search_all_survives_failing_sources():
    log = []
    cands = search.search_all(META, sources=[_Boom(), _Blocked(), _Ok()], log=log.append)
    assert [c.source for c in cands] == ["letras"]
    assert cands[0].text == "invented line"  # cleaned
    assert cands[0].score > 0.9
    assert any("genius" in m for m in log) and any("blocked" in m for m in log)


def test_lrclib_parse_prefers_plain_and_skips_instrumental():
    out = lrclib.parse([
        {"id": 1, "trackName": "Synthetic Song", "artistName": "Test Artist", "duration": 237, "instrumental": False,
         "plainLyrics": "a\nb", "syncedLyrics": "[00:01.00]a\n[00:02.00]b"},
        {"id": 2, "instrumental": True},
    ])
    assert len(out) == 1 and out[0].text == "a\nb" and out[0].duration_s == 237


def test_genius_page_title_comes_from_the_page():
    from lyricloom.lyrics.sources import genius
    artist, title = genius.parse_page_title((FX / "genius" / "page.html").read_text(encoding="utf-8"))
    assert title == "Synthetic Song" and artist == "Test Singer"


def test_websearch_result_urls():
    urls = websearch.parse_results((FX / "websearch" / "ddg.html").read_text(encoding="utf-8"))
    assert urls and all(u.startswith("http") for u in urls)
    assert any("letras.mus.br" in u for u in urls)
