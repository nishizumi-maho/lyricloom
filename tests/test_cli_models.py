"""`lyricloom models repair <id>` wires the existing repair API to the command line."""
from lyricloom import cli


def test_cli_models_repair_calls_the_repair_api(monkeypatch, capsys):
    repaired = []
    monkeypatch.setattr(cli.runtime, "repair", lambda spec: repaired.append(spec.id) or [])
    monkeypatch.setattr(cli.models, "status", lambda spec: "ready")
    assert cli.main(["models", "repair", "whisper-large-v3"]) == 0
    assert repaired == ["whisper-large-v3"]
    assert "whisper-large-v3" in capsys.readouterr().out


def test_cli_models_repair_rejects_an_unknown_id(monkeypatch, capsys):
    monkeypatch.setattr(cli.runtime, "repair",
                        lambda spec: (_ for _ in ()).throw(AssertionError("must not repair")))
    assert cli.main(["models", "repair", "does-not-exist"]) == 2
    assert "unknown model" in capsys.readouterr().err


def test_cli_cache_clean_removes_the_work_cache(tmp_path, monkeypatch, capsys):
    import time

    monkeypatch.setattr("lyricloom.config.WORK_ROOT", tmp_path / "work")
    d = tmp_path / "work" / "track"
    d.mkdir(parents=True)
    (d / "vocals.wav").write_bytes(b"x" * 1024)
    stamp = time.time() - 3600
    import os

    os.utime(d, (stamp, stamp))
    assert cli.main(["cache", "clean", "--max-gb", "0"]) == 0
    assert not d.exists()
    assert "removed 1 folder" in capsys.readouterr().out


def test_cli_cache_status_reports_size(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("lyricloom.config.WORK_ROOT", tmp_path / "work")
    d = tmp_path / "work" / "track"
    d.mkdir(parents=True)
    (d / "vocals.wav").write_bytes(b"x" * 2048)
    assert cli.main(["cache", "status"]) == 0
    assert "1 track folder" in capsys.readouterr().out
