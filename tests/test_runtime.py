from lyricloom import config, runtime


def test_human_size():
    assert runtime.human_size(0) == "0 B"
    assert runtime.human_size(1024) == "1.0 KB"
    assert runtime.human_size(3 * 1024**3) == "3.0 GB"


def test_status_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS", tmp_path)
    monkeypatch.setattr(config, "WHISPER_MODEL", tmp_path / "missing.bin")
    monkeypatch.setattr(config, "SEPARATOR_MODEL_DIR", tmp_path / "separator")
    monkeypatch.setattr(config, "MTL_CHECKPOINT", tmp_path / "checkpoint_MTL")
    assert runtime.status() == {"whisper": False, "separator": False, "mms": False, "mtl": False}


def test_whisper_status_requires_a_plausible_file(tmp_path, monkeypatch):
    model = tmp_path / "ggml-large-v3.bin"
    model.write_bytes(b"x" * 100)
    monkeypatch.setattr(config, "WHISPER_MODEL", model)
    assert runtime.whisper_status() is False
