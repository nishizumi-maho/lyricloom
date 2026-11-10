"""Where the player finds the isolated vocals, and which lyric files the karaoke window offers."""
from __future__ import annotations

from pathlib import Path

from .. import cache
from ..stages.separate import kept_vocals_path
from ..stages.write import japanese_path, romaji_path


def vocal_source(audio: Path) -> Path | None:
    """The isolated vocal stem for `audio`: the work cache WAV when it exists, else the kept FLAC.

    The work cache path includes the audio mtime, so a tag edit or a cleared cache loses the WAV
    while the durable FLAC (kept_vocals_path) is still there.
    """
    try:
        work = cache.work_dir(audio) / "vocals.wav"
    except OSError:
        work = None
    if work is not None and work.is_file():
        return work
    try:
        kept = kept_vocals_path(audio)
    except (OSError, ValueError):
        return None
    return kept if kept.is_file() else None


def script_candidates(audio: Path, script: str = "japanese") -> list[tuple[str, Path]]:
    """Karaoke lyric choices: the main `.lrc` first (it follows the chosen script), then the
    kept Japanese and romaji variants when they exist."""
    main = audio.with_suffix(".lrc")
    japanese, romaji = japanese_path(audio), romaji_path(audio)
    items: list[tuple[str, Path]] = []
    if main.is_file():
        items.append(("Main (.lrc)", main))
    if japanese.is_file():
        items.append(("Japanese", japanese))
    if romaji.is_file():
        items.append(("Romaji", romaji))
    if items:
        return items
    return [("Main (.lrc)", main)]


def default_script_path(audio: Path, script: str = "japanese") -> Path:
    """The lyric file the karaoke window opens first. The main .lrc follows the script setting;
    when it is missing, use the variant that matches the setting, then the other one."""
    main = audio.with_suffix(".lrc")
    if main.is_file():
        return main
    preferred = romaji_path(audio) if script == "romaji" else japanese_path(audio)
    fallback = japanese_path(audio) if script == "romaji" else romaji_path(audio)
    if preferred.is_file():
        return preferred
    if fallback.is_file():
        return fallback
    return main
