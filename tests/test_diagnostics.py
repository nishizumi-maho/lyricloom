from lyricloom import VERSION, config
from lyricloom.app.diagnostics import app_log_path, diagnostics_text, tail_app_log


def test_diagnostics_never_contains_the_assemblyai_key(tmp_path, monkeypatch):
    key_file = tmp_path / "assemblyai.key"
    key_file.write_text("fake-secret-key-value", encoding="utf-8")
    monkeypatch.setattr(config, "ASSEMBLYAI_KEY_FILE", key_file)
    config.set_assemblyai_enabled(True)   # the isolated test settings file (conftest)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    app_log_path().parent.mkdir(parents=True, exist_ok=True)
    app_log_path().write_text("2026-01-01 INFO lyricloom.runner: started\n", encoding="utf-8")

    text = diagnostics_text(tmp_path / "Library")
    assert "fake-secret-key-value" not in text
    assert VERSION in text
    assert "AssemblyAI" in text and "value not shown" in text
    assert str(tmp_path / "Library") in text
    assert "started" in text


def test_tail_app_log_keeps_the_last_200_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    app_log_path().parent.mkdir(parents=True, exist_ok=True)
    app_log_path().write_text("\n".join(f"line {i}" for i in range(250)), encoding="utf-8")
    tail = tail_app_log()
    assert "line 50" in tail and "line 249" in tail and "line 49" not in tail
    assert len(tail.splitlines()) == 200


def test_missing_log_is_reported_not_raised(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "nothing")
    assert tail_app_log() == "(no app log yet)"
    assert "App log" in diagnostics_text()
