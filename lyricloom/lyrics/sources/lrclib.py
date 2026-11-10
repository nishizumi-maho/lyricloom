from __future__ import annotations

import httpx

from ...model import TrackMeta
from .base import RawResult, check, lrc_to_text_and_lines

name = "lrclib"


def parse(items: list[dict]) -> list[RawResult]:
    out = []
    for it in items:
        if it.get("instrumental"):
            continue
        synced = None
        text = it.get("plainLyrics") or ""
        if it.get("syncedLyrics"):
            text2, synced = lrc_to_text_and_lines(it["syncedLyrics"])
            text = text or text2
        if text:
            out.append(RawResult(it.get("trackName", ""), it.get("artistName", ""), it.get("duration"),
                                 text, synced, f"https://lrclib.net/api/get/{it.get('id')}"))
    return out


def search(meta: TrackMeta, client: httpx.Client) -> list[RawResult]:
    r = check(client.get("https://lrclib.net/api/search",
                         params={"track_name": meta.title, "artist_name": meta.artist}))
    return parse(r.json())
