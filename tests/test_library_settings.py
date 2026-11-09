import os
import stat
import sys
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
