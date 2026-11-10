import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricloom import config, runner  # noqa: E402
from lyricloom.app.main import MainWindow, QueueWorker  # noqa: E402
from lyricloom.app.model import TrackRow  # noqa: E402
from lyricloom.model import LrcDoc  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(app, cond, timeout=20):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert cond()


def _audio(tmp_path, name="01 - Song.flac"):
    audio = tmp_path / "Artist" / "Album" / name
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"x")
    return audio


def test_a_raising_track_does_not_wedge_the_queue(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    w = MainWindow(tmp_path)
    try:
        _wait(app, lambda: w.proxy.rowCount() == 1)
        def broken(path):
            raise ValueError("bad .lrc")

        monkeypatch.setattr("lyricloom.app.main.read_status", broken)
        monkeypatch.setattr("lyricloom.runner.process",
                            lambda path, **kwargs: runner.TrackResult(path, "done"))
        monkeypatch.setattr("lyricloom.app.main.QMessageBox.warning", lambda *a, **k: None)
        monkeypatch.setattr(w, "_preflight", lambda *a, **k: True)
        w.process([audio])
        _wait(app, lambda: w._queue is None)
        assert not w.progress.isVisible()
        assert not w.btn_stop.isEnabled() and not w.btn_stop_now.isEnabled() and not w.btn_pause.isEnabled()
        assert w._queue_error == ""
    finally:
        w.dirty = False
        w.close()


def test_research_mode_calls_research_lyrics(tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    seen = []

    def fake(path, cancel=None, allow_cloud=None):
        seen.append((path, allow_cloud))
        return runner.TrackResult(path, "done")

    monkeypatch.setattr(runner, "research_lyrics", fake)
    q = QueueWorker([audio], force=True, research=True, allow_cloud=False)
    q.run()
    assert seen == [(audio, False)]


def test_redo_restores_the_original_lrc_when_align_fails(tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    lrc = audio.with_suffix(".lrc")
    original = "[re:LyricLoom 1.0.0]\n[#source:netease conf:0.90]\n[00:01.00]<00:01.00>eu<00:02.00>\n"
    lrc.write_text(original, encoding="utf-8")
    monkeypatch.setattr("lyricloom.runner.process",
                        lambda path, **kwargs: runner.TrackResult(path, "failed", error="align boom"))

    q = QueueWorker([audio], force=True, redo=True)
    rows = []
    q.track_done.connect(rows.append)
    q.run()

    assert lrc.read_text(encoding="utf-8") == original
    assert rows and rows[0].status == "failed" and "align boom" in rows[0].error
    assert not list(tmp_path.glob("*.redo-backup"))


def test_cancelled_track_has_its_own_status_and_shows_as_stopped(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    monkeypatch.setattr("lyricloom.runner.process",
                        lambda path, **kwargs: runner.TrackResult(path, "cancelled", error="Stopped by the user"))
    q = QueueWorker([audio], force=True)
    rows = []
    q.track_done.connect(rows.append)
    q.run()
    assert rows[0].status == "cancelled"
    assert rows[0].error == "Stopped by the user"

    w = MainWindow(tmp_path)
    try:
        w.rows = [TrackRow(audio, "Artist", "Song", "cancelled")]
        w._fill_table()
        assert w.proxy.index(0, 2).data() == "Stopped"
    finally:
        w.dirty = False
        w.close()


def test_closing_with_a_queue_uses_stop_now_not_terminate(app, tmp_path, monkeypatch):
    w = MainWindow(tmp_path)
    calls = []

    class FakeQueue:
        def stop(self, now=False):
            calls.append(now)

    try:
        w._queue = FakeQueue()
        monkeypatch.setattr(w, "_ask_queue_shutdown", lambda: "now")
        w.close()
        assert calls == [True]                  # Stop now sets the cancellation event
        assert w._quit_after_queue
    finally:
        w._queue = None
        w._quit_after_queue = False
        w.dirty = False
        w.close()


def test_process_refuses_an_unusable_cache_folder(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    w = MainWindow(tmp_path)
    try:
        seen = []
        monkeypatch.setattr("lyricloom.app.main.QMessageBox.warning",
                            lambda parent, title, text: seen.append((title, text)))
        monkeypatch.setattr("lyricloom.app.main.config.vocals_root", lambda: audio)   # a file
        w.process([audio])
        assert w._queue is None
        assert seen and seen[0][0] == "Vocals cache" and str(audio) in seen[0][1]
    finally:
        w.dirty = False
        w.close()


def test_save_write_error_is_shown_and_keeps_the_edits_dirty(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    w = MainWindow(tmp_path)
    try:
        w.audio, w.doc, w.dirty = audio, LrcDoc({}, []), True
        seen = []
        monkeypatch.setattr("lyricloom.app.main.QMessageBox.critical",
                            lambda parent, title, text: seen.append((title, text)))

        def denied(*args, **kwargs):
            raise OSError(13, "Access is denied")

        monkeypatch.setattr("lyricloom.app.main.write_lyrics", denied)
        assert w.save() is False
        assert w.dirty
        assert seen and seen[0][0] == "Save lyrics"
        assert str(audio.with_suffix(".lrc")) in seen[0][1] and "Access is denied" in seen[0][1]
    finally:
        w.dirty = False
        w.close()


# ---------- FRB-01: the per-queue cloud consent reaches every queue kind ----------

def _declined_cloud_window(tmp_path, monkeypatch):
    config.set_assemblyai_enabled(True)
    w = MainWindow(tmp_path)
    monkeypatch.setattr(w, "_ask_cloud_for_queue", lambda: False)
    monkeypatch.setattr(w, "_preflight", lambda *args, **kwargs: True)
    return w


def _done(path, **kwargs):
    return runner.TrackResult(path, "done")


def test_declined_cloud_consent_reaches_a_normal_queue(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    seen = []
    monkeypatch.setattr("lyricloom.runner.process",
                        lambda path, **kwargs: seen.append(kwargs) or _done(path))
    w = _declined_cloud_window(tmp_path, monkeypatch)
    try:
        assert w.process([audio]) is True
        _wait(app, lambda: seen and w._queue is None)
        assert seen[0]["allow_cloud"] is False
    finally:
        w.dirty = False
        w.close()


def test_declined_cloud_consent_reaches_a_redo_queue(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    seen = []
    monkeypatch.setattr("lyricloom.runner.forget_sync", lambda path: {})
    monkeypatch.setattr("lyricloom.runner.process",
                        lambda path, **kwargs: seen.append(kwargs) or _done(path))
    w = _declined_cloud_window(tmp_path, monkeypatch)
    try:
        assert w.process([audio], redo=True) is True
        _wait(app, lambda: seen and w._queue is None)
        assert seen[0]["only_stage"] == "align" and seen[0]["allow_cloud"] is False
    finally:
        w.dirty = False
        w.close()


def test_declined_cloud_consent_reaches_search_lyrics_again(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    seen = []
    monkeypatch.setattr("lyricloom.runner.research_lyrics",
                        lambda path, **kwargs: seen.append(kwargs) or _done(path))
    w = _declined_cloud_window(tmp_path, monkeypatch)
    try:
        assert w.process([audio], research=True) is True
        _wait(app, lambda: seen and w._queue is None)
        assert seen[0]["allow_cloud"] is False
    finally:
        w.dirty = False
        w.close()


def test_declined_cloud_consent_reaches_a_per_song_models_queue(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    seen = []
    monkeypatch.setattr("lyricloom.runner.process",
                        lambda path, **kwargs: seen.append(kwargs) or _done(path))
    w = _declined_cloud_window(tmp_path, monkeypatch)
    try:
        models = {"transcribe": "whisper-small"}
        assert w.process([audio], models=models) is True
        _wait(app, lambda: seen and w._queue is None)
        assert seen[0]["models"] == models and seen[0]["allow_cloud"] is False
    finally:
        w.dirty = False
        w.close()


def test_declined_cloud_consent_reaches_a_command_line_process_queue(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    seen = []
    monkeypatch.setattr("lyricloom.runner.process",
                        lambda path, **kwargs: seen.append(kwargs) or _done(path))
    w = _declined_cloud_window(tmp_path, monkeypatch)
    try:
        w._handle_external({"cmd": "process", "paths": [str(audio)], "redo": False})
        _wait(app, lambda: seen and w._queue is None)
        assert seen[0]["allow_cloud"] is False
    finally:
        w.dirty = False
        w.close()


def test_declined_cloud_consent_reaches_a_drag_and_drop_queue(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    seen = []
    monkeypatch.setattr("lyricloom.runner.process",
                        lambda path, **kwargs: seen.append(kwargs) or _done(path))
    w = _declined_cloud_window(tmp_path, monkeypatch)
    try:
        w.drop_paths([str(audio)])
        _wait(app, lambda: seen and w._queue is None)
        assert seen[0]["allow_cloud"] is False
    finally:
        w.dirty = False
        w.close()


def test_a_dirty_open_track_can_be_skipped_from_the_queue(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    w = MainWindow(tmp_path)
    try:
        w.audio, w.doc, w.dirty = audio, LrcDoc({}, []), True
        monkeypatch.setattr(w, "_ask_open_track", lambda: "skip")
        monkeypatch.setattr(w, "_preflight", lambda *a, **k: True)
        w.process([audio])
        assert w._queue is None
        assert "No tracks left" in w.statusBar().currentMessage()
    finally:
        w.dirty = False
        w.close()

    w = MainWindow(tmp_path)
    try:
        w.audio, w.doc, w.dirty = audio, LrcDoc({}, []), True
        monkeypatch.setattr(w, "_ask_open_track", lambda: "save")
        monkeypatch.setattr(w, "save", lambda: False)      # saving failed: do not start
        monkeypatch.setattr(w, "_preflight", lambda *a, **k: True)
        w.process([audio])
        assert w._queue is None
    finally:
        w.dirty = False
        w.close()


def test_redo_with_current_models_runs_a_forced_full_queue(app, tmp_path, monkeypatch):
    """The library action re-runs every stage of a finished song with the current model choices,
    whatever the window's Force checkbox says (it used to raise TypeError on click)."""
    audio = _audio(tmp_path)
    seen = []
    monkeypatch.setattr("lyricloom.runner.process",
                        lambda path, **kwargs: seen.append(kwargs) or _done(path))
    w = MainWindow(tmp_path)
    try:
        monkeypatch.setattr(w, "_preflight", lambda *a, **k: True)
        assert not w.force.isChecked()
        w._redo_with_current_models(audio)
        _wait(app, lambda: seen and w._queue is None)
        assert seen[0]["force"] is True
        assert seen[0].get("only_stage") is None and seen[0].get("models") is None
        assert not w.force.isChecked()   # the window's own choice is untouched
    finally:
        w.dirty = False
        w.close()
