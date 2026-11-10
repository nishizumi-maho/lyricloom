from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin, urlparse

import httpx

from ...model import Line, Segment, TrackMeta

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"


class SourceBlocked(Exception):
    """The site refused a scripted request (403 / anti-bot decoy). Never worked around."""


@dataclass
class RawResult:
    title: str
    artist: str
    duration_s: float | None
    text: str
    synced: list[Line] | None
    url: str


class Source(Protocol):
    name: str

    def search(self, meta: TrackMeta, client: httpx.Client) -> list[RawResult]: ...


def check(resp: httpx.Response) -> httpx.Response:
    if resp.status_code in (401, 403, 429):
        raise SourceBlocked(f"{resp.request.url.host} answered {resp.status_code}")
    resp.raise_for_status()
    return resp


def host_matches(host: str | None, domain: str) -> bool:
    """Exact host or a real subdomain, so evilgenius.com is not genius.com."""
    host = (host or "").lower().rstrip(".")
    domain = domain.lower()
    return host == domain or host.endswith("." + domain)


def is_https_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.hostname)


def get_allowed(client: httpx.Client, url: str, allowed: Callable[[str], bool],
                max_redirects: int = 5) -> httpx.Response:
    """GET `url`, following redirects only while every hop stays allowed.

    The shared search client follows redirects by default. Pages taken from a search result are
    fetched here with redirects disabled so each Location is validated again: an allowlisted page
    that redirects off its host, or from https to http, is refused instead of parsed as lyrics.
    """
    current = url
    for _ in range(max_redirects + 1):
        if not allowed(current):
            host = urlparse(current).hostname or current
            raise SourceBlocked(f"refusing to fetch {host}: not an allowed page")
        response = client.get(current, follow_redirects=False)
        if not response.is_redirect:
            return check(response)
        location = response.headers.get("location", "")
        if not location:
            return check(response)
        current = urljoin(current, location)
    raise SourceBlocked("too many redirects while fetching a search result")


_LRC_TS = re.compile(r"\[(\d+):(\d{2})(?:[.:](\d{1,3}))?\]")


def lrc_to_text_and_lines(lrc: str) -> tuple[str, list[Line]]:
    """Plain text plus line-timed Lines from an ordinary LRC (metadata tags dropped)."""
    texts: list[str] = []
    lines: list[Line] = []
    for raw in lrc.splitlines():
        stamps = list(_LRC_TS.finditer(raw))
        if not stamps:
            continue
        body = raw[stamps[-1].end():].strip()
        if not body:
            continue
        for m in stamps:
            ms = int(m.group(1)) * 60000 + int(m.group(2)) * 1000 + int((m.group(3) or "0").ljust(3, "0")[:3])
            lines.append(Line(ms, [Segment(body, None, None)]))
        texts.append(body)
    lines.sort(key=lambda l: l.start_ms)
    return "\n".join(l.text for l in lines), lines
