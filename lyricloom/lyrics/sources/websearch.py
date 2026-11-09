"""DuckDuckGo HTML search; only result pages from sites with their own extractor are read."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import httpx

from ...model import TrackMeta
from . import genius, utaten
from .base import RawResult, check, get_allowed, host_matches, is_https_url

name = "websearch"
_RESULT = re.compile(r'class="result__a" href="([^"]+)"')


def parse_results(html_text: str) -> list[str]:
    urls = []
    for href in _RESULT.findall(html_text):
        href = href.replace("&amp;", "&")
        target = parse_qs(urlparse(href).query).get("uddg", [href])[0]
        if is_https_url(target):
            urls.append(target)
    return list(dict.fromkeys(urls))


def allowed_page(url: str) -> bool:
    """True for an https page on an exact allowlisted host that an extractor can read."""
    if not is_https_url(url):
        return False
    parsed = urlparse(url)
    if host_matches(parsed.hostname, "genius.com"):
        return parsed.path.endswith("-lyrics")
    if host_matches(parsed.hostname, "utaten.com"):
        return "/lyric/" in parsed.path
    return False


def search(meta: TrackMeta, client: httpx.Client) -> list[RawResult]:
    word = "歌詞" if meta.lang == "ja" else "letra lyrics"
    r = check(client.get("https://html.duckduckgo.com/html/", params={"q": f"{meta.artist} {meta.title} {word}"}))
    out = []
    for url in parse_results(r.text)[:8]:
        if not allowed_page(url):
            continue
        parsed = urlparse(url)
        if host_matches(parsed.hostname, "genius.com"):
            page = get_allowed(client, url, allowed_page).text
            text = genius.parse_page(page)
            artist, title = genius.parse_page_title(page)   # the page's own song, not ours
            if text:
                out.append(RawResult(title, artist, None, text, None, url))
        else:
            title, artist, text = utaten.parse_page(get_allowed(client, url, allowed_page).text)
            if text:
                out.append(RawResult(title, artist, None, text, None, url))
    return out
