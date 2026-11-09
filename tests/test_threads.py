import os
import subprocess
import sys
from pathlib import Path

from lyricloom import config, workers
from lyricloom.stages import transcribe as tr


def test_whisper_uses_thread_limit(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, cancel=None, **kwargs):
        seen["cmd"] = cmd
        (tmp_path / "whisper.json").write_text('{"result": {"language": "pt"}, "transcription": []}', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(tr, "run_process", fake_run)
    cli = tmp_path / "whisper-cli"
    cli.write_text("", encoding="utf-8")
    model = tmp_path / "ggml.bin"
    model.write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "whisper_cli", lambda: cli)
    monkeypatch.setattr(tr, "_model_path", lambda spec: model)
    tr.transcribe(Path("v.wav"), tmp_path, "pt")
    assert seen["cmd"][seen["cmd"].index("-t") + 1] == str(config.CPU_THREADS)


def test_workers_get_thread_limit_env():
    out = workers.run_worker("fake_worker", {"env_probe": True}, python=sys.executable,
                             cwd=Path(__file__).resolve().parent)
    assert out["env"]["OMP_NUM_THREADS"] == str(config.CPU_THREADS)
    assert out["env"]["MKL_NUM_THREADS"] == str(config.CPU_THREADS)


def test_thread_limit_is_a_sane_fraction_of_the_cpu():
    assert 1 <= config.CPU_THREADS <= max(1, (os.cpu_count() or 4))


def test_default_thread_limit_is_cpu_minus_two_capped_at_sixteen(monkeypatch):
    if os.environ.get("LYRICLOOM_CPU_THREADS"):
        import pytest

        pytest.skip("an explicit override is set")
    assert config.CPU_THREADS == max(1, min(16, (os.cpu_count() or 4) - 2))
