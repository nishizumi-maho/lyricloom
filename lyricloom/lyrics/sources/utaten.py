from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from ...model import TrackMeta
from .base import RawResult, check, get_allowed, host_matches, is_https_url

name = "utaten"
_LINK = re.compile(r'href="(/lyric/[a-z]{2}\d+/)"')


def allowed_page(url: str) -> bool:
    """Only https utaten.com pages may be fetched from its own search results."""
    return is_https_url(url) and host_matches(urlparse(url).hostname, "utaten.com")


def parse_search(html_text: str) -> list[str]:
    return list(dict.fromkeys(_LINK.findall(html_text)))


def parse_page(html_text: str) -> tuple[str, str, str]:
    """(title, artist, lyrics); furigana (<span class=rt>) is dropped from the text."""
    soup = BeautifulSoup(html_text, "html.parser")
    body = soup.select_one("div.lyricBody div.hiragana")
    if body is None:
        return "", "", ""
    for rt in body.select("span.rt"):
        rt.decompose()
    for br in body.find_all("br"):
        br.replace_with("\n")
    text = "\n".join(l.strip() for l in body.get_text().splitlines()).strip()
    h2 = soup.select_one("h2.newLyricTitle__main") or soup.find("h2")
    title = h2.contents[0].strip() if h2 and h2.contents else ""
    artist_el = soup.select_one(".newLyricWork__name a, .newLyricWork a[href*='/artist/']")
    return title, artist_el.get_text(strip=True) if artist_el else "", text


def search(meta: TrackMeta, client: httpx.Client) -> list[RawResult]:
    r = check(client.get("https://utaten.com/search", params={"title": meta.title, "artist_name": meta.artist}))
    out = []
    for path in parse_search(r.text)[:3]:
        url = "https://utaten.com" + path
        title, artist, text = parse_page(get_allowed(client, url, allowed_page).text)
        if text:
            out.append(RawResult(title, artist, None, text, None, url))
    return out
