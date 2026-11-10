import json

from lyricloom import config


def test_legacy_settings_and_data_are_migrated(tmp_path, monkeypatch):
    local = tmp_path / "Local"
    old = local / "LyricsBoca"
    new = local / "LyricLoom"
    old.mkdir(parents=True)
    (old / "settings.json").write_text(json.dumps({
        "library": str(tmp_path / "Music"),
        "models": str(old / "models"),
        "vocals": str(old / "vocals"),
        "work": str(old / "work"),
    }), encoding="utf-8")
    (old / "models").mkdir()
    (old / "models" / "model.bin").write_bytes(b"model")
    (old / "vocals").mkdir()
    (old / "vocals" / "kept.flac").write_bytes(b"vocals")
    (old / "work").mkdir()
    (old / "work" / "cache.txt").write_text("cache", encoding="utf-8")
    (old / "assemblyai.key").write_text("key", encoding="utf-8")

    monkeypatch.setattr(config, "IS_WINDOWS", True)
    monkeypatch.setattr(config, "APP_DATA", new)
    monkeypatch.setattr(config, "SETTINGS_FILE", new / "settings.json")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv("LYRICLOOM_DATA_DIR", raising=False)
    monkeypatch.delenv("LYRICLOOM_MODELS", raising=False)

    assert config.migrate_legacy_settings() is True
    assert (new / "settings.json").is_file()
    assert (new / "models" / "model.bin").read_bytes() == b"model"
    assert (new / "vocals" / "kept.flac").read_bytes() == b"vocals"
    assert (new / "work" / "cache.txt").read_text(encoding="utf-8") == "cache"
    assert (new / "assemblyai.key").read_text(encoding="utf-8") == "key"
    settings = json.loads((new / "settings.json").read_text(encoding="utf-8"))
    assert settings["models"] == str(new / "models")
    assert settings["vocals"] == str(new / "vocals")
    assert settings["work"] == str(new / "work")
    assert settings["library"] == str(tmp_path / "Music")


def test_portable_profiles_are_never_migrated(tmp_path, monkeypatch):
    local = tmp_path / "Local"
    old = local / "LyricsBoca"
    old.mkdir(parents=True)
    (old / "settings.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "IS_WINDOWS", True)
    monkeypatch.setattr(config, "APP_DATA", local / "LyricLoom")
    monkeypatch.setattr(config, "SETTINGS_FILE", local / "LyricLoom" / "settings.json")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("LYRICLOOM_DATA_DIR", str(tmp_path / "portable"))
    assert config.migrate_legacy_settings() is False
    assert not (local / "LyricLoom" / "settings.json").exists()


def test_a_migrated_session_rereads_the_folder_constants(tmp_path, monkeypatch):
    local = tmp_path / "Local"
    old = local / "LyricsBoca"
    new = local / "LyricLoom"
    old.mkdir(parents=True)
    (old / "settings.json").write_text(json.dumps({
        "models": str(old / "models"),
        "work": str(old / "work"),
    }), encoding="utf-8")
    (old / "models").mkdir()
    (old / "work").mkdir()

    monkeypatch.setattr(config, "IS_WINDOWS", True)
    monkeypatch.setattr(config, "APP_DATA", new)
    monkeypatch.setattr(config, "SETTINGS_FILE", new / "settings.json")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv("LYRICLOOM_DATA_DIR", raising=False)
    monkeypatch.delenv("LYRICLOOM_MODELS", raising=False)
    monkeypatch.delenv("LYRICLOOM_WORK", raising=False)

    assert config.migrate_legacy_settings() is True
    config.refresh_folder_constants()       # the call run() makes after the migration (FRB-14)
    assert config.WORK_ROOT == new / "work"
    assert config.MODELS == new / "models"
    assert config.WHISPER_MODEL.parent == new / "models"
