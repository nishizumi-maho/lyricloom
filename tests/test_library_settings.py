import json
import os
import stat
import sys
import threading
import time

import pytest

from lyricloom import config
from lyricloom.app import model


def test_library_root_defaults_and_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    assert config.library_root() == config.DEFAULT_LIBRARY
    config.set_library_root(tmp_path / "Música")
    assert config.library_root() == tmp_path / "Música"


def test_assemblyai_key_can_be_set_and_removed(tmp_path, monkeypatch):
    from lyricloom.stages import assemblyai
    monkeypatch.setattr(config, "ASSEMBLYAI_KEY_FILE", tmp_path / "assemblyai.key")
    monkeypatch.delenv("ASSEMBLYAI_API_KEY", raising=False)
    config.set_assemblyai_key("  abc123  ")
    assert assemblyai.api_key() == "abc123" and config.has_assemblyai_key()
    assert config.assemblyai_enabled() is False   # a key alone does not turn the cloud on
    config.set_assemblyai_key("")
    assert not (tmp_path / "assemblyai.key").exists() and not config.has_assemblyai_key()


def test_assemblyai_enabled_is_a_separate_setting(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    assert config.assemblyai_enabled() is False
    config.set_assemblyai_enabled(True)
    assert config.assemblyai_enabled() is True
    config.set_assemblyai_enabled(False)
    assert config.assemblyai_enabled() is False


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_assemblyai_key_roundtrips_through_dpapi(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ASSEMBLYAI_KEY_FILE", tmp_path / "assemblyai.key")
    monkeypatch.delenv("ASSEMBLYAI_API_KEY", raising=False)
    config.set_assemblyai_key("super-secret-key")
    raw = (tmp_path / "assemblyai.key").read_bytes()
    assert b"super-secret-key" not in raw
    assert raw.startswith(config._DPAPI_MAGIC)
    assert config.read_assemblyai_key() == "super-secret-key"


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_plain_text_assemblyai_key_is_encrypted_on_first_read(tmp_path, monkeypatch):
    path = tmp_path / "assemblyai.key"
    path.write_text("plain-text-key", encoding="utf-8")
    monkeypatch.setattr(config, "ASSEMBLYAI_KEY_FILE", path)
    monkeypatch.delenv("ASSEMBLYAI_API_KEY", raising=False)
    assert config.read_assemblyai_key() == "plain-text-key"
    assert b"plain-text-key" not in path.read_bytes()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file permissions")
def test_assemblyai_key_is_private_and_plain_key_is_migrated(tmp_path, monkeypatch):
    path = tmp_path / "assemblyai.key"
    monkeypatch.setattr(config, "ASSEMBLYAI_KEY_FILE", path)
    monkeypatch.delenv("ASSEMBLYAI_API_KEY", raising=False)
    config.set_assemblyai_key("abc123")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    path.write_text("plain-key", encoding="utf-8")
    os.chmod(path, 0o644)
    assert config.read_assemblyai_key() == "plain-key"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_assemblyai_key_never_reaches_the_track_log(tmp_path, monkeypatch):
    from lyricloom import cache, runner

    monkeypatch.setattr(config, "ASSEMBLYAI_KEY_FILE", tmp_path / "assemblyai.key")
    monkeypatch.delenv("ASSEMBLYAI_API_KEY", raising=False)
    config.set_assemblyai_key("secret-value")
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    runner._log(audio, "cloud failed with secret-value in the message")
    log = (cache.work_dir(audio) / "log.txt").read_text(encoding="utf-8")
    assert "secret-value" not in log and "***" in log
    assert "secret-value" not in repr(config.all_settings())


def test_assemblyai_key_is_not_in_decryption_errors(tmp_path, monkeypatch):
    path = tmp_path / "assemblyai.key"
    path.write_bytes(config._DPAPI_MAGIC + b"not-a-real-blob")
    monkeypatch.setattr(config, "ASSEMBLYAI_KEY_FILE", path)
    monkeypatch.delenv("ASSEMBLYAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as error:
        config.read_assemblyai_key()
    assert "not-a-real-blob" not in str(error.value)


def _track(root, name, lrc=None):
    p = root / "Artist" / "Album" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    if lrc is not None:
        p.with_suffix(".lrc").write_text(lrc, encoding="utf-8")
    return p


def test_scan_cache_rereads_only_what_changed(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK_ROOT", tmp_path / "work")
    root = tmp_path / "lib"
    a = _track(root, "a.flac")
    b = _track(root, "b.flac")
    reads = []
    real = model.read_status
    monkeypatch.setattr(model, "read_status", lambda p: reads.append(p.name) or real(p))

    assert [r.status for r in model.scan_cached(root)] == ["pending", "pending"]
    assert sorted(reads) == ["a.flac", "b.flac"]

    reads.clear()
    later = time.time() + 5
    b.with_suffix(".lrc").write_text("[re:LyricLoom 1.0.0]\n[#source:netease conf:0.90]\n[00:01.00]x\n", encoding="utf-8")
    os.utime(b.with_suffix(".lrc"), (later, later))
    rows = {r.path.name: r.status for r in model.scan_cached(root)}
    assert reads == ["b.flac"]                 # only the track whose .lrc changed
    assert rows == {"a.flac": "pending", "b.flac": "done"}

    a.unlink()
    assert [r.path.name for r in model.scan_cached(root)] == ["b.flac"]


def test_cached_rows_load_without_touching_the_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK_ROOT", tmp_path / "work")
    root = tmp_path / "lib"
    _track(root, "a.flac")
    model.scan_cached(root)
    assert [r.path.name for r in model.load_cached_rows(root)] == ["a.flac"]
    assert model.load_cached_rows(tmp_path / "other") == []


def test_scan_stops_between_files_when_the_background_cancel_is_set(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK_ROOT", tmp_path / "work")
    root = tmp_path / "lib"
    _track(root, "a.flac")
    _track(root, "b.flac")
    cancel = threading.Event()
    cancel.set()
    assert model.scan_cached(root, cancel=cancel) == []
    assert not model._cache_file(root).exists()   # a cancelled scan does not replace the cache


def test_a_malformed_confidence_does_not_break_the_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK_ROOT", tmp_path / "work")
    root = tmp_path / "lib"
    bad = _track(root, "a.flac", "[re:LyricLoom 1.0.0]\n[#source:demo conf:oops]\n[00:01.00]x\n")
    _track(root, "b.flac", "[re:LyricLoom 1.0.0]\n[#source:demo conf:0.80]\n[00:01.00]x\n")
    rows = {r.path.name: r for r in model.scan_cached(root)}
    assert set(rows) == {"a.flac", "b.flac"}
    assert rows["a.flac"].conf == 0.0 and "invalid confidence" in rows["a.flac"].error
    assert rows["b.flac"].conf == 0.8
    assert bad.with_suffix(".lrc").exists()      # the bad file was not deleted or rewritten


def test_a_corrupt_or_old_cache_is_discarded_and_rebuilt(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK_ROOT", tmp_path / "work")
    root = tmp_path / "lib"
    _track(root, "a.flac")
    cache = model._cache_file(root)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("{not json", encoding="utf-8")
    assert model.load_cached_rows(root) == []
    assert [r.path.name for r in model.scan_cached(root)] == ["a.flac"]
    assert json.loads(cache.read_text(encoding="utf-8"))["schema"] == model.SCAN_SCHEMA

    cache.write_text(json.dumps({"schema": 1, "rows": {"x": {"path": "x"}}}), encoding="utf-8")
    assert model.load_cached_rows(root) == []
    assert [r.path.name for r in model.scan_cached(root)] == ["a.flac"]


def test_one_unreadable_file_is_counted_and_the_rest_still_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK_ROOT", tmp_path / "work")
    root = tmp_path / "lib"
    _track(root, "a.flac")
    _track(root, "b.flac")
    real = model._stamp

    def stamp(audio):
        if audio.name == "a.flac":
            raise PermissionError(13, "Access is denied")
        return real(audio)

    monkeypatch.setattr(model, "_stamp", stamp)
    stats = {}
    rows = model.scan_cached(root, stats)
    assert stats["unreadable"] == 1
    assert {r.path.name for r in rows} == {"a.flac", "b.flac"}
    assert next(r for r in rows if r.path.name == "a.flac").status == "other"


def test_a_malformed_cached_row_is_ignored_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK_ROOT", tmp_path / "work")
    root = tmp_path / "lib"
    _track(root, "a.flac")
    model.scan_cached(root)
    cache = model._cache_file(root)
    data = json.loads(cache.read_text(encoding="utf-8"))
    data["rows"][next(iter(data["rows"]))]["conf"] = "oops"
    cache.write_text(json.dumps(data), encoding="utf-8")
    assert model.load_cached_rows(root) == []
    assert [r.path.name for r in model.scan_cached(root)] == ["a.flac"]
