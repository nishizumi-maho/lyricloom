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


# Japanese needs kana.  Han characters alone are also Chinese; script variants are only written
# when the resolved language is Japanese (R1-03).
_JAPANESE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_TAG_UNSAFE = re.compile(r"[\]\r\n]+")


def _tag_safe(value) -> str:
    """A title/artist value that cannot break out of its ``[ti:...]``/``[ar:...]`` tag.  A semicolon
    is left alone: it is unsafe only in the ``#models``/``#warning`` values, not in a title."""
    return _TAG_UNSAFE.sub(" ", str(value)).strip()


def japanese_path(audio: Path) -> Path:
    return audio.with_name(audio.stem + ".japanese.lrc")


def romaji_path(audio: Path) -> Path:
    return audio.with_name(audio.stem + ".romaji.lrc")


def _replace(path: Path, doc: LrcDoc) -> None:
    """Replaces a script variant, keeping the previous file as ``.bak`` (FR-A-05)."""
    _replace_bytes_with_backup(path, format_lrc(doc).encode("utf-8"))


def _replace_bytes_with_backup(path: Path, data: bytes) -> None:
    """Replaces `path` after copying the old file to the engine's .bak name."""
    if path.exists():
        shutil.copy2(path, _backup_path(path))
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
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


def write_lyrics(audio: Path, doc: LrcDoc, lang: str | None = None) -> Path:
    """Writes the .lrc. Japanese lyrics are also kept in both scripts, <song>.japanese.lrc and
    <song>.romaji.lrc, and the .lrc gets the one chosen in the app (config.japanese_script).

    ``lang`` is the resolved lyric language.  A Chinese or Korean lyric that merely contains Han
    characters must not get Japanese readings and romaji sidecars (R1-03).  ``None`` falls back to
    the document's [#language] tag, then to the old character heuristic for hand-written calls."""
    if lang is None:
        lang = doc.meta.get("#language")
    japanese = (lang == "ja") if lang else _is_japanese(doc)
    if not japanese:
        return write_lrc(audio, doc)
    romaji = to_romaji(doc)
    _replace(japanese_path(audio), doc)
    _replace(romaji_path(audio), romaji)
    return write_lrc(audio, romaji if config.japanese_script() == "romaji" else doc)


def apply_script_preference(root: Path, *, script: str | None = None, dry_run: bool = False) -> int:
    """Puts the chosen script in the .lrc of every Japanese song under root; songs processed
    before both scripts were kept get them now. Returns the number of .lrc files rewritten.

    With `dry_run=True` nothing is written and the return value is how many files a real run would
    rewrite, so the GUI can ask for confirmation with the exact count. The main .lrc gets the same
    .bak copy as a save; the two variant files are derived and are replaced without one."""
    from ..lrc import parse_lrc
    from ..runner import AUDIO_EXT
    want_romaji = (script or config.japanese_script()) == "romaji"
    n = 0
    for lrc in root.rglob("*.lrc"):
        if lrc.name.endswith((".japanese.lrc", ".romaji.lrc", ".original.lrc")):
            continue
        audio = next((lrc.with_suffix(e) for e in AUDIO_EXT if lrc.with_suffix(e).exists()), None)
        if audio is None:
            continue                       # not a song's lyric (e.g. a comparison file)
        japanese = japanese_path(audio)
        romaji = romaji_path(audio)
        if not japanese.exists():
            doc = parse_lrc(lrc.read_text(encoding="utf-8", errors="replace"))
            if (doc.meta.get("#language") not in (None, "ja")
                    or "#engine" not in doc.meta or not is_ours(doc.meta.get("re"))
                    or not _is_japanese(doc)):
                continue                   # not a LyricLoom Japanese lyric
            if dry_run:
                chosen = format_lrc(to_romaji(doc) if want_romaji else doc).encode("utf-8")
            else:
                _replace(japanese, doc)
                _replace(romaji, to_romaji(doc))
                chosen = (romaji if want_romaji else japanese).read_bytes()
        else:
            chosen = (romaji if want_romaji else japanese).read_bytes()
        if lrc.read_bytes() != chosen:
            n += 1
            if not dry_run:
                _replace_bytes_with_backup(lrc, chosen)
    return n


def original_path(audio: Path) -> Path:
    return audio.with_name(audio.stem + ".original.lrc")


def write_original(audio: Path, meta: dict, official: Candidate) -> Path:
    """Keeps the official lyric as found (its own timing when it has one, else plain text) in
    `<audio stem>.original.lrc`, so it survives the enhanced .lrc and any edit made to it.

    A user may have hand-corrected the fetched lyric, so a rewrite keeps a ``.bak`` copy; title and
    artist are sanitized like every other tag (FR-A-05, FR-A-06)."""
    safe_meta = {key: _tag_safe(value) if key in ("ti", "ar") else value
                 for key, value in meta.items()}
    if official.synced:
        lines = [Line(l.start_ms, l.segments if len(l.segments) > 1 else [Segment(l.text, None, None)])
                 for l in official.synced]
        body = format_lrc(LrcDoc(safe_meta, lines))
    else:
        body = format_lrc(LrcDoc(safe_meta, [])) + official.text.strip() + "\n"
    path = original_path(audio)
    _replace_bytes_with_backup(path, body.encode("utf-8"))
    return path
