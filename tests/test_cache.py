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


def test_load_rejects_a_different_model_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr("lyricloom.config.WORK_ROOT", tmp_path / "work")
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    cache.save(audio, "separate", "1", {"v": 1}, inputs={"separator": "aaaa"})
    assert cache.load(audio, "separate", "1", inputs={"separator": "aaaa"}) == {"v": 1}
    assert cache.load(audio, "separate", "1", inputs={"separator": "bbbb"}) is None


def test_load_accepts_and_upgrades_a_legacy_cache_only_when_allowed(tmp_path, monkeypatch):
    """2.0 wrote no `_inputs`; a rejection can be turned into a reuse when the caller has checked
    that the resolved models are the defaults, and the cache is rewritten with the fingerprint."""
    monkeypatch.setattr("lyricloom.config.WORK_ROOT", tmp_path / "work")
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    cache.save(audio, "separate", "1", {"v": 1})          # legacy: no inputs key
    assert cache.load(audio, "separate", "1", inputs={"separator": "aaaa"}) is None
    assert cache.load(audio, "separate", "1", inputs={"separator": "aaaa"},
                      legacy_ok=True) == {"v": 1}
    # It was rewritten: the next load takes the normal path, but a different model is still stale.
    assert cache.load(audio, "separate", "1", inputs={"separator": "aaaa"}) == {"v": 1}
    assert cache.load(audio, "separate", "1", inputs={"separator": "bbbb"},
                      legacy_ok=True) is None
