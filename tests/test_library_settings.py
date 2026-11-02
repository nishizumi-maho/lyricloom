import os
import time

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
    assert assemblyai.api_key() == "abc123" and config.ASSEMBLYAI_ENABLED
    config.set_assemblyai_key("")
    assert not (tmp_path / "assemblyai.key").exists() and not config.ASSEMBLYAI_ENABLED


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
