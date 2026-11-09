import json
import os
import time

import pytest

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


@pytest.mark.parametrize("payload", ["{bad", "null", "[]"])
def test_corrupt_or_non_object_cache_is_discarded_and_recomputed(tmp_path, monkeypatch, payload):
    """A truncated file, null or a list must not fail the track forever; force and a normal run
    both treat it as absent (R1-14)."""
    monkeypatch.setattr("lyricloom.config.WORK_ROOT", tmp_path / "work")
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    cache.save(audio, "separate", "1", {"v": 1})
    p = cache.work_dir(audio) / "separate.json"
    p.write_text(payload, encoding="utf-8")
    assert cache.load(audio, "separate", "1") is None
    assert not p.exists()
    cache.save(audio, "separate", "1", {"v": 2})
    assert cache.load(audio, "separate", "1") == {"v": 2}


def test_a_live_lock_refuses_the_second_run_and_a_stale_lock_is_recovered(tmp_path, monkeypatch):
    monkeypatch.setattr("lyricloom.config.WORK_ROOT", tmp_path / "work")
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    lock = cache.acquire(audio)
    assert lock is not None
    assert cache.acquire(audio) is None          # the app/CLI must not process the same track twice
    lock.release()
    assert cache.acquire(audio) is not None

    work = cache.work_dir(audio)
    (work / cache.LOCK_NAME).write_text(json.dumps({"pid": 999999}), encoding="utf-8")
    recovered = cache.acquire(audio)
    assert recovered is not None                 # the owner is gone: not a permanent lock
    recovered.release()


def test_prune_removes_the_oldest_folders_and_never_the_running_track(tmp_path, monkeypatch):
    monkeypatch.setattr("lyricloom.config.WORK_ROOT", tmp_path / "work")
    root = tmp_path / "work"
    dirs = []
    for i in range(3):
        d = root / f"track{i}"
        d.mkdir(parents=True)
        (d / "vocals.wav").write_bytes(b"x" * (100 * (i + 1)))
        stamp = time.time() - (30 - i * 10)
        os.utime(d, (stamp, stamp))
        dirs.append(d)
    keep = dirs[-1]
    report = cache.size_report()
    assert report["files"] == 3 and report["bytes"] == 600
    result = cache.prune(0, keep=keep)
    assert result["removed"] == 2
    assert not dirs[0].exists() and not dirs[1].exists()
    assert keep.exists()
    assert cache.size_report()["bytes"] == 300


def test_clear_removes_one_stage_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("lyricloom.config.WORK_ROOT", tmp_path / "work")
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    cache.save(audio, "lyrics", "1", {"a": 1})
    cache.save(audio, "separate", "1", {"b": 2})
    assert cache.clear(audio, "lyrics") == 1
    assert cache.load(audio, "lyrics", "1") is None
    assert cache.load(audio, "separate", "1") == {"b": 2}
