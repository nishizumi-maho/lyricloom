"""Creates `<song>.original.lrc` for songs processed before the engine kept the official lyric,
from the lyrics found back then (engine cache). Nothing is downloaded or reprocessed, and existing
files are never overwritten.
Usage: python tools/backfill_originals.py [library folder]   (default: the library chosen in the app)"""
import json
import sys
from pathlib import Path

from rapidfuzz import fuzz

from lyricloom import cache, config
from lyricloom.brand import is_ours
from lyricloom.lrc import parse_lrc
from lyricloom.runner import AUDIO_EXT, _cands_from_json
from lyricloom.stages.write import original_path, write_original

sys.stdout.reconfigure(encoding="utf-8")
root = Path(sys.argv[1]) if len(sys.argv) > 1 else config.library_root()
counts = {"created": 0, "exists": 0, "not official": 0, "no cache": 0, "no match": 0}
for audio in sorted(p for p in root.rglob("*") if p.suffix.lower() in AUDIO_EXT):
    lrc = audio.with_suffix(".lrc")
    if not lrc.exists():
        continue
    doc = parse_lrc(lrc.read_text(encoding="utf-8", errors="replace"))
    if not is_ours(doc.meta.get("re")):
        continue                                   # not written by LyricLoom
    if original_path(audio).exists():
        counts["exists"] += 1
        continue
    source = doc.meta.get("#source", "").split(" conf:")[0]
    if source in ("", "transcription", "manual"):
        counts["not official"] += 1
        continue
    cached = cache.work_dir(audio) / "lyrics.json"
    if not cached.exists():
        counts["no cache"] += 1
        print("no cache:", audio)
        continue
    same = [c for c in _cands_from_json(json.loads(cached.read_text(encoding="utf-8"))) if c.source == source]
    text = "\n".join(l.text for l in doc.lines)
    best = max(same, key=lambda c: fuzz.ratio(c.text, text), default=None)
    if best is None or fuzz.ratio(best.text, text) < 60:   # edits keep it close; a different lyric does not
        counts["no match"] += 1
        print("no match:", audio)
        continue
    write_original(audio, {"ti": doc.meta.get("ti", ""), "ar": doc.meta.get("ar", ""), "#source": source}, best)
    counts["created"] += 1
    print("created:", original_path(audio).name)
print(counts)
