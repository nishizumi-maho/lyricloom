from __future__ import annotations

import html

import httpx

from ...model import TrackMeta
from .base import RawResult, check, lrc_to_text_and_lines

name = "qq"


def parse_search(data: dict) -> list[dict]:
    return ((data.get("data") or {}).get("song") or {}).get("list") or []


def parse_lyric(data: dict, title: str = "", artist: str = "") -> str:
    """QQ prepends a `title - artist` line to the lyrics; it is not sung."""
    text, _ = lrc_to_text_and_lines(html.unescape(data.get("lyric") or ""))
    lines = text.splitlines()
    if lines and title and lines[0].startswith(f"{title} - "):
        lines = lines[1:]
    return "\n".join(lines)


def search(meta: TrackMeta, client: httpx.Client) -> list[RawResult]:
    r = check(client.get("https://c.y.qq.com/soso/fcgi-bin/client_search_cp",
                         params={"w": f"{meta.title} {meta.artist}", "format": "json", "n": 5, "p": 1}))
    out = []
    for song in parse_search(r.json()):
        lr = check(client.get("https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg",
                              headers={"Referer": "https://y.qq.com"},
                              params={"songmid": song["songmid"], "format": "json", "nobase64": 1}))
        text = parse_lyric(lr.json(), song["songname"])
        if text:
            out.append(RawResult(song["songname"], (song.get("singer") or [{}])[0].get("name", ""),
                                 float(song.get("interval") or 0) or None, text, None,
                                 f"https://y.qq.com/n/ryqq/songDetail/{song['songmid']}"))
    return out
