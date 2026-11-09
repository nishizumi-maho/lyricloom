from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from .. import config
from ..brand import is_ours
from ..lrc import format_lrc
from ..model import Candidate, Line, LrcDoc, Segment


def _backup_path(lrc: Path) -> Path:
    bak = lrc.with_name(lrc.name + ".bak")
    n = 1
    while bak.exists():
        bak = lrc.with_name(f"{lrc.name}.bak{n}")
        n += 1
    return bak


def write_lrc(audio: Path, doc: LrcDoc) -> Path:
    """Writes `<audio stem>.lrc` next to the audio. An existing .lrc is never lost: a copy goes to
    .lrc.bak (or .lrc.bak1, .bak2, ... when older backups exist) and the new file replaces the old
    one atomically. The old file is copied, not moved, so a crash between the backup and the replace
    leaves the previous .lrc intact."""
    lrc = audio.with_suffix(".lrc")
    tmp = lrc.with_name(lrc.name + ".tmp")
    tmp.write_bytes(format_lrc(doc).encode("utf-8"))
    if lrc.exists():
        shutil.copy2(lrc, _backup_path(lrc))
    os.replace(tmp, lrc)
    return lrc


_JAPANESE = re.compile(r"[぀-ヿ一-鿿]")


def japanese_path(audio: Path) -> Path:
    return audio.with_name(audio.stem + ".japanese.lrc")


def romaji_path(audio: Path) -> Path:
    return audio.with_name(audio.stem + ".romaji.lrc")


def _replace(path: Path, doc: LrcDoc) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(format_lrc(doc).encode("utf-8"))
    os.replace(tmp, path)


def _is_japanese(doc: LrcDoc) -> bool:
    return any(_JAPANESE.search(l.text) for l in doc.lines)


def to_romaji(doc: LrcDoc) -> LrcDoc:
    """Same lines and word timing, each segment spelled in romaji (words separated by spaces)."""
    from ..text.japanese import reading
    lines = []
    for l in doc.lines:
        segs = [Segment((reading(s.text).strip() or s.text) + " ", s.start_ms, s.end_ms, s.conf) for s in l.segments]
        if segs:
            segs[-1].text = segs[-1].text.rstrip()
        lines.append(Line(l.start_ms, segs, l.conf))
    return LrcDoc(dict(doc.meta), lines)


def write_lyrics(audio: Path, doc: LrcDoc) -> Path:
    """Writes the .lrc. Japanese lyrics are also kept in both scripts, <song>.japanese.lrc and
    <song>.romaji.lrc, and the .lrc gets the one chosen in the app (config.japanese_script)."""
    if not _is_japanese(doc):
        return write_lrc(audio, doc)
    romaji = to_romaji(doc)
    _replace(japanese_path(audio), doc)
    _replace(romaji_path(audio), romaji)
    return write_lrc(audio, romaji if config.japanese_script() == "romaji" else doc)


def apply_script_preference(root: Path) -> int:
    """Puts the chosen script in the .lrc of every Japanese song under root; songs processed
    before both scripts were kept get them now. Returns the number of .lrc files rewritten."""
    from ..lrc import parse_lrc
    from ..runner import AUDIO_EXT
    want_romaji = config.japanese_script() == "romaji"
    n = 0
    for lrc in root.rglob("*.lrc"):
        if lrc.name.endswith((".japanese.lrc", ".romaji.lrc", ".original.lrc")):
            continue
        audio = next((lrc.with_suffix(e) for e in AUDIO_EXT if lrc.with_suffix(e).exists()), None)
        if audio is None:
            continue                       # not a song's lyric (e.g. a comparison file)
        if not japanese_path(audio).exists():
            doc = parse_lrc(lrc.read_text(encoding="utf-8", errors="replace"))
            if "#engine" not in doc.meta or not is_ours(doc.meta.get("re")) or not _is_japanese(doc):
                continue                   # not a LyricLoom Japanese lyric
            _replace(japanese_path(audio), doc)
            _replace(romaji_path(audio), to_romaji(doc))
        chosen = (romaji_path if want_romaji else japanese_path)(audio).read_bytes()
        if lrc.read_bytes() != chosen:
            tmp = lrc.with_name(lrc.name + ".tmp")
            tmp.write_bytes(chosen)
            os.replace(tmp, lrc)          # derived from the kept files: no backup needed
            n += 1
    return n


def original_path(audio: Path) -> Path:
    return audio.with_name(audio.stem + ".original.lrc")


def write_original(audio: Path, meta: dict, official: Candidate) -> Path:
    """Keeps the official lyric as found (its own timing when it has one, else plain text) in
    `<audio stem>.original.lrc`, so it survives the enhanced .lrc and any edit made to it."""
    if official.synced:
        lines = [Line(l.start_ms, l.segments if len(l.segments) > 1 else [Segment(l.text, None, None)])
                 for l in official.synced]
        body = format_lrc(LrcDoc(meta, lines))
    else:
        body = format_lrc(LrcDoc(meta, [])) + official.text.strip() + "\n"
    path = original_path(audio)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(body.encode("utf-8"))
    os.replace(tmp, path)
    return path
