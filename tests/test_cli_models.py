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
