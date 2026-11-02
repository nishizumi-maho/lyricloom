from __future__ import annotations

import re

import httpx

from ...model import Line, Segment, TrackMeta
from .base import RawResult, check, lrc_to_text_and_lines

name = "netease"
_HDR = {"Referer": "https://music.163.com"}
_YRC_LINE = re.compile(r"^\[(\d+),(\d+)\](.*)$")
_YRC_WORD = re.compile(r"\((\d+),(\d+),\d+\)([^(]*)")


def parse_yrc(yrc: str) -> list[Line]:
    """NetEase word-timed lyrics: `[lineStartMs,lineDurMs](wordStartMs,wordDurMs,0)word...`."""
    lines = []
    for raw in yrc.splitlines():
        m = _YRC_LINE.match(raw.strip())
        if not m:
            continue
        segs = [Segment(w.group(3), int(w.group(1)), int(w.group(1)) + int(w.group(2)))
                for w in _YRC_WORD.finditer(m.group(3)) if w.group(3)]
        if segs:
            lines.append(Line(int(m.group(1)), segs))
    return lines


def parse_lyric(data: dict) -> tuple[str, list[Line] | None]:
    lrc = (data.get("lrc") or {}).get("lyric") or ""
    text, _ = lrc_to_text_and_lines(lrc)
    yrc = (data.get("yrc") or {}).get("lyric") or ""
    synced = parse_yrc(yrc) if yrc else None
    if synced and not text:
        text = "\n".join(l.text for l in synced)
    return text, synced or None


def search(meta: TrackMeta, client: httpx.Client) -> list[RawResult]:
    r = check(client.get("https://music.163.com/api/cloudsearch/pc", headers=_HDR,
                         params={"s": f"{meta.title} {meta.artist}", "type": 1, "limit": 5}))
    out = []
    for song in (r.json().get("result") or {}).get("songs") or []:
        lr = check(client.get("https://music.163.com/api/song/lyric/v1", headers=_HDR,
                              params={"id": song["id"], "lv": 1, "yv": 1, "tv": -1}))
        text, synced = parse_lyric(lr.json())
        if text:
            out.append(RawResult(song["name"], (song.get("ar") or [{}])[0].get("name", ""),
                                 song.get("dt", 0) / 1000, text, synced,
                                 f"https://music.163.com/song?id={song['id']}"))
    return out
