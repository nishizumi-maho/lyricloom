import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricloom import runner  # noqa: E402
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

    def fake(path, cancel=None):
        seen.append(path)
        return runner.TrackResult(path, "done")

    monkeypatch.setattr(runner, "research_lyrics", fake)
    q = QueueWorker([audio], force=True, research=True)
    q.run()
    assert seen == [audio]


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


def test_a_dirty_open_track_can_be_skipped_from_the_queue(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    w = MainWindow(tmp_path)
    try:
        w.audio, w.doc, w.dirty = audio, LrcDoc({}, []), True
        monkeypatch.setattr(w, "_ask_open_track", lambda: "skip")
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
        w.process([audio])
        assert w._queue is None
    finally:
        w.dirty = False
        w.close()
