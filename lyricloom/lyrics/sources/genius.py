from __future__ import annotations

from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from ...model import TrackMeta
from .base import RawResult, check, get_allowed, host_matches, is_https_url

name = "genius"


def allowed_page_url(url: str) -> bool:
    """Only https pages on genius.com itself may be fetched from search results."""
    return is_https_url(url) and host_matches(urlparse(url).hostname, "genius.com")


def parse_search(data: dict) -> list[dict]:
    hits = []
    for sec in data.get("response", {}).get("sections", []):
        if sec.get("type") != "song":
            continue
        for h in sec.get("hits", []):
            r = h.get("result") or {}
            # Romanization/translation pages are not the official lyrics.
            if "Genius-romanizations" in r.get("url", "") or "translation" in r.get("url", "").lower():
                continue
            hits.append({"title": r.get("title", ""), "artist": (r.get("primary_artist") or {}).get("name", ""),
                         "url": r.get("url", "")})
    return hits


def parse_page(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")
    parts = []
    for div in soup.select("div[data-lyrics-container=true]"):
        for junk in div.select("[data-exclude-from-selection=true]"):
            junk.decompose()
        for br in div.find_all("br"):
            br.replace_with("\n")
        parts.append(div.get_text())
    lines = [l.strip() for l in "\n".join(parts).splitlines()]
    # Section headers like [Verse 1] are not sung.
    return "\n".join(l for l in lines if not (l.startswith("[") and l.endswith("]"))).strip()


def parse_page_title(html_text: str) -> tuple[str, str]:
    """(artist, title) from the page's og:title, e.g. "Artist - Title"."""
    tag = BeautifulSoup(html_text, "html.parser").find("meta", property="og:title")
    content = (tag.get("content") if tag else "") or ""
    artist, sep, title = content.partition(" – ")
    return (artist.strip(), title.strip()) if sep else ("", content.strip())


def search(meta: TrackMeta, client: httpx.Client) -> list[RawResult]:
    r = check(client.get("https://genius.com/api/search/multi", params={"q": f"{meta.title} {meta.artist}"}))
    out = []
    for hit in parse_search(r.json())[:3]:
        if not allowed_page_url(hit["url"]):
            continue
        text = parse_page(get_allowed(client, hit["url"], allowed_page_url).text)
        if text:
            out.append(RawResult(hit["title"], hit["artist"], None, text, None, hit["url"]))
    return out
