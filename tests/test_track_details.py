import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lyricloom import runner  # noqa: E402
from lyricloom.app import model  # noqa: E402
from lyricloom.app.details import details_text  # noqa: E402
from lyricloom.app.main import QueueWorker  # noqa: E402


def _audio(root):
    audio = root / "Artist" / "Album" / "01 - Song.flac"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"x")
    return audio


def test_a_failed_result_survives_a_rescan(tmp_path, monkeypatch):
    monkeypatch.setattr("lyricloom.config.WORK_ROOT", tmp_path / "work")
    root = tmp_path / "lib"
    audio = _audio(root)
    model.scan_cached(root)
    row = next(r for r in model.scan_cached(root) if r.path == audio)
    row.status = "failed"
    row.error = "WorkerError: align crashed"
    row.device = "cpu"
    row.fallback = "WSL/ROCm failed"
    row.log_path = str(tmp_path / "work" / "x" / "log.txt")
    model.store_result(root, row)

    rows = model.scan_cached(root)
    saved = next(r for r in rows if r.path == audio)
    assert saved.status == "failed"
    assert "align crashed" in saved.error
    assert saved.device == "cpu" and "WSL/ROCm failed" in saved.fallback
    assert saved.log_path.endswith("log.txt")
    text = details_text(saved, "Device: CPU (fallback)")
    assert "align crashed" in text and "WSL/ROCm failed" in text and "log.txt" in text


def test_queue_worker_keeps_device_fallback_error_and_log(tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    monkeypatch.setattr("lyricloom.runner.process",
                        lambda path, **kwargs: runner.TrackResult(path, "failed", error="boom",
                                                                 device="cpu", fallback="no GPU"))
    worker = QueueWorker([audio], force=True)
    rows = []
    worker.track_done.connect(rows.append)
    worker.run()

    assert rows and rows[0].status == "failed" and rows[0].error == "boom"
    assert rows[0].device == "cpu" and rows[0].fallback == "no GPU"
    assert rows[0].log_path.endswith("log.txt")
