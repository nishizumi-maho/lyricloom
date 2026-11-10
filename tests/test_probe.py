import hashlib

import numpy as np
import soundfile as sf
from mutagen.flac import FLAC

from lyricloom.probe import probe


def _make_flac(path, artist, title, seconds=2.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.zeros(int(44100 * seconds), dtype="float32"), 44100, format="FLAC")
    f = FLAC(str(path))
    f["artist"] = artist
    f["title"] = title
    f["album"] = "Synthetic Song [Single]"
    f.save()
    return path


def test_probe_japanese_path(tmp_path):
    audio = _make_flac(tmp_path / "テスト歌手" / "01 - Synthetic Song.flac", "テスト歌手", "Synthetic Song")
    meta = probe(audio)
    assert meta.artist == "テスト歌手" and meta.title == "Synthetic Song"
    assert meta.lang == "ja"
    assert abs(meta.duration_s - 2.0) < 0.05


def test_probe_latin_is_other(tmp_path):
    meta = probe(_make_flac(tmp_path / "a.flac", "Test Artist", "Synthetic Song (Test Version)"))
    assert meta.lang == "other"


def test_probe_han_only_tags_are_not_japanese(tmp_path):
    meta = probe(_make_flac(tmp_path / "a.flac", "Chinese Artist", "孤勇者"))
    assert meta.lang == "other"


def test_probe_explicit_language_tag_wins(tmp_path):
    audio = _make_flac(tmp_path / "a.flac", "Chinese Artist", "孤勇者")
    f = FLAC(str(audio))
    f["language"] = "zh"
    f.save()
    assert probe(audio).lang == "zh"


def test_probe_never_writes(tmp_path):
    audio = _make_flac(tmp_path / "a.flac", "A", "B")
    before = (audio.stat().st_mtime_ns, hashlib.sha1(audio.read_bytes()).hexdigest())
    probe(audio)
    assert (audio.stat().st_mtime_ns, hashlib.sha1(audio.read_bytes()).hexdigest()) == before
