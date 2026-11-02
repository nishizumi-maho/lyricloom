"""DuckDuckGo HTML search; only result pages from sites with their own extractor are read."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import httpx

from ...model import TrackMeta
from . import genius, utaten
from .base import RawResult, check

name = "websearch"
_RESULT = re.compile(r'class="result__a" href="([^"]+)"')


def parse_results(html_text: str) -> list[str]:
    urls = []
    for href in _RESULT.findall(html_text):
        href = href.replace("&amp;", "&")
        target = parse_qs(urlparse(href).query).get("uddg", [href])[0]
        if target.startswith("http"):
            urls.append(target)
    return list(dict.fromkeys(urls))


def search(meta: TrackMeta, client: httpx.Client) -> list[RawResult]:
    word = "歌詞" if meta.lang == "ja" else "letra lyrics"
    r = check(client.get("https://html.duckduckgo.com/html/", params={"q": f"{meta.artist} {meta.title} {word}"}))
    out = []
    for url in parse_results(r.text)[:8]:
        host = urlparse(url).netloc
        if host.endswith("genius.com") and url.endswith("-lyrics"):
            page = check(client.get(url)).text
            text = genius.parse_page(page)
            artist, title = genius.parse_page_title(page)   # the page's own song, not ours
            if text:
                out.append(RawResult(title, artist, None, text, None, url))
        elif host.endswith("utaten.com") and "/lyric/" in url:
            title, artist, text = utaten.parse_page(check(client.get(url)).text)
            if text:
                out.append(RawResult(title, artist, None, text, None, url))
    return out
