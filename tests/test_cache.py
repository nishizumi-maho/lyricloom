import os
import time

from lyricloom import cache


def test_work_dir_changes_with_mtime(tmp_path, monkeypatch):
    monkeypatch.setattr("lyricloom.config.WORK_ROOT", tmp_path / "work")
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    first = cache.work_dir(audio)
    later = time.time() + 10
    os.utime(audio, (later, later))
    assert cache.work_dir(audio) != first


def test_load_ignores_other_version(tmp_path, monkeypatch):
    monkeypatch.setattr("lyricloom.config.WORK_ROOT", tmp_path / "work")
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    cache.save(audio, "lyrics", "1", {"k": "日本語"})
    assert cache.load(audio, "lyrics", "1") == {"k": "日本語"}
    assert cache.load(audio, "lyrics", "2") is None
