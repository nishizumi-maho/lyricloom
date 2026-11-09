from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

from lyricloom.lyrics import search
from lyricloom.lyrics.sources import genius, lrclib, websearch
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


def _ddg(*urls: str) -> str:
    links = "".join(
        f'<a class="result__a" href="//duckduckgo.com/l/?uddg={quote(url, safe="")}&amp;rut=test">x</a>'
        for url in urls)
    return f"<html><body>{links}</body></html>"


def test_websearch_drops_http_and_lookalike_hosts():
    html = _ddg(
        "http://genius.com/Test-singer-song-lyrics",
        "https://evilgenius.com/Test-singer-song-lyrics",
        "https://genius.com.evil.example/Test-singer-song-lyrics",
        "https://genius.com/Test-singer-song-lyrics",
        "https://evilutaten.com/lyric/hw00000001/",
        "https://utaten.com/lyric/hw00000001/",
    )
    urls = websearch.parse_results(html)
    allowed = [url for url in urls if websearch.allowed_page(url)]
    assert allowed == ["https://genius.com/Test-singer-song-lyrics",
                       "https://utaten.com/lyric/hw00000001/"]
    assert not any(url.startswith("http://") for url in urls)


def test_websearch_fetches_only_allowlisted_pages(monkeypatch):
    fetched = []
    page = (FX / "genius" / "page.html").read_text(encoding="utf-8")

    def fake_get(url, **kwargs):
        fetched.append(url)
        if url.startswith("https://html.duckduckgo.com/"):
            text = _ddg(
                "https://evilgenius.com/Test-singer-song-lyrics",
                "https://genius.com/Test-singer-synthetic-song-lyrics",
            )
        else:
            text = page
        return httpx.Response(200, text=text, request=httpx.Request("GET", url))

    class Client:
        get = staticmethod(fake_get)

    out = websearch.search(META, Client())
    assert fetched == ["https://html.duckduckgo.com/html/",
                       "https://genius.com/Test-singer-synthetic-song-lyrics"]
    assert [r.url for r in out] == ["https://genius.com/Test-singer-synthetic-song-lyrics"]


@pytest.mark.parametrize("redirect_to", [
    "https://evil.example/Test-singer-song-lyrics",
    "http://genius.com/Test-singer-song-lyrics",
])
def test_websearch_does_not_follow_a_redirect_off_the_allowlist(redirect_to):
    page_url = "https://genius.com/Test-singer-synthetic-song-lyrics"
    fetched = []

    def fake_get(url, **kwargs):
        fetched.append(url)
        if url.startswith("https://html.duckduckgo.com/"):
            return httpx.Response(200, text=_ddg(page_url), request=httpx.Request("GET", url))
        assert kwargs.get("follow_redirects") is False
        assert url == page_url
        return httpx.Response(302, headers={"location": redirect_to},
                              request=httpx.Request("GET", url))

    class Client:
        get = staticmethod(fake_get)

    with pytest.raises(SourceBlocked, match="not an allowed page"):
        websearch.search(META, Client())
    assert fetched == ["https://html.duckduckgo.com/html/", page_url]


def test_websearch_follows_a_redirect_that_stays_on_the_allowlist():
    page_url = "https://genius.com/Test-singer-synthetic-song-lyrics"
    moved = "https://genius.com/Test-singer-synthetic-song-remix-lyrics"
    page = (FX / "genius" / "page.html").read_text(encoding="utf-8")
    fetched = []

    def fake_get(url, **kwargs):
        fetched.append(url)
        if url.startswith("https://html.duckduckgo.com/"):
            return httpx.Response(200, text=_ddg(page_url), request=httpx.Request("GET", url))
        if url == page_url:
            assert kwargs.get("follow_redirects") is False
            return httpx.Response(302, headers={"location": moved}, request=httpx.Request("GET", url))
        assert url == moved and kwargs.get("follow_redirects") is False
        return httpx.Response(200, text=page, request=httpx.Request("GET", url))

    class Client:
        get = staticmethod(fake_get)

    out = websearch.search(META, Client())
    assert fetched == ["https://html.duckduckgo.com/html/", page_url, moved]
    assert [r.url for r in out] == [page_url]


def test_genius_does_not_follow_a_redirect_off_the_allowlist():
    page_url = "https://genius.com/Test-singer-synthetic-song-lyrics"
    results = {"response": {"sections": [{"type": "song", "hits": [
        {"result": {"title": "Synthetic Song", "url": page_url,
                    "primary_artist": {"name": "Test Singer"}}},
    ]}]}}
    fetched = []

    def fake_get(url, **kwargs):
        fetched.append(url)
        if "api/search" in url:
            return httpx.Response(200, json=results, request=httpx.Request("GET", url))
        assert kwargs.get("follow_redirects") is False
        assert url == page_url
        return httpx.Response(302, headers={"location": "https://evil.example/lyrics"},
                              request=httpx.Request("GET", url))

    class Client:
        get = staticmethod(fake_get)

    with pytest.raises(SourceBlocked, match="not an allowed page"):
        genius.search(META, Client())
    assert fetched == ["https://genius.com/api/search/multi", page_url]


def test_genius_search_never_fetches_a_lookalike_or_http_url():
    fetched = []
    page = (FX / "genius" / "page.html").read_text(encoding="utf-8")
    results = {"response": {"sections": [{"type": "song", "hits": [
        {"result": {"title": "T", "url": "https://genius.com.evil.example/song-lyrics",
                    "primary_artist": {"name": "A"}}},
        {"result": {"title": "T", "url": "http://genius.com/song-lyrics",
                    "primary_artist": {"name": "A"}}},
        {"result": {"title": "Synthetic Song", "url": "https://genius.com/Test-singer-synthetic-song-lyrics",
                    "primary_artist": {"name": "Test Singer"}}},
    ]}]}}

    def fake_get(url, **kwargs):
        fetched.append(url)
        if "api/search" in url:
            return httpx.Response(200, json=results, request=httpx.Request("GET", url))
        return httpx.Response(200, text=page, request=httpx.Request("GET", url))

    class Client:
        get = staticmethod(fake_get)

    out = genius.search(META, Client())
    assert fetched == ["https://genius.com/api/search/multi",
                       "https://genius.com/Test-singer-synthetic-song-lyrics"]
    assert [r.url for r in out] == ["https://genius.com/Test-singer-synthetic-song-lyrics"]
