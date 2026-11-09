import os
import shutil
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricloom import config, runner  # noqa: E402
from lyricloom.app import model  # noqa: E402
from lyricloom.app.main import MainWindow, queue_summary  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(app, cond, timeout=10):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert cond()


def _audio(root, name="01 - Song.flac"):
    audio = root / "Artist" / "Album" / name
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"x")
    return audio


class _Mime:
    def __init__(self, paths):
        self._urls = [QUrl.fromLocalFile(str(p)) for p in paths]

    def hasUrls(self):
        return True

    def urls(self):
        return self._urls


class _Drop:
    def __init__(self, paths):
        self._mime = _Mime(paths)
        self.accepted = False
        self.ignored = False

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


def test_unavailable_library_shows_banner_and_keeps_cached_rows(app, tmp_path):
    library = tmp_path / "library"
    _audio(library)
    model.scan_cached(library)          # the last known listing
    shutil.rmtree(library)

    w = MainWindow(library)
    try:
        assert not w.library_banner.isHidden()
        assert "unavailable" in w.library_banner_label.text().lower()
        assert str(library) in w.library_banner_label.text()
        assert w.table.rowCount() == 1   # the cached row was not replaced by an empty table

        library.mkdir(parents=True, exist_ok=True)
        _audio(library)
        w.btn_retry_library.click()
        _wait(app, lambda: "1 track" in w.statusBar().currentMessage())
        assert w.library_banner.isHidden() and w.table.rowCount() == 1
    finally:
        w.dirty = False
        w.close()


def test_drag_and_drop_queues_only_valid_audio(app, tmp_path, monkeypatch):
    w = MainWindow(tmp_path)
    try:
        audio = _audio(tmp_path, "a.flac")
        other = _audio(tmp_path, "b.flac")
        note = tmp_path / "notes.txt"
        note.write_text("nope", encoding="utf-8")
        queued = []
        monkeypatch.setattr(w, "process", lambda paths, redo=False: queued.append((list(paths), redo)) or True)

        assert w.acceptDrops()
        event = _Drop([audio, note, tmp_path / "Artist" / "Album"])
        w.dropEvent(event)
        assert event.accepted
        _wait(app, lambda: queued)
        assert set(queued[0][0]) == {audio.resolve(), other.resolve()}
        assert "Ignored 1 path" in w.statusBar().currentMessage()
    finally:
        w.dirty = False
        w.close()


def test_refresh_keeps_the_last_failure_details(app, tmp_path):
    audio = _audio(tmp_path)
    w = MainWindow(tmp_path)
    try:
        _wait(app, lambda: w.table.rowCount() == 1)
        row = w.rows[0]
        row.status, row.error = "failed", "WorkerError: boom"
        row.device, row.fallback = "cpu", "no GPU"
        w._update_row(row)
        w.refresh()
        _wait(app, lambda: "1 track" in w.statusBar().currentMessage())
        saved = w.rows[0]
        assert saved.status == "failed" and "boom" in saved.error
        assert saved.device == "cpu" and saved.fallback == "no GPU"
    finally:
        w.dirty = False
        w.close()


def test_queue_summary_counts_and_fallbacks():
    results = [
        runner.TrackResult(path=None, status="done"),
        runner.TrackResult(path=None, status="review"),
        runner.TrackResult(path=None, status="skipped"),
        runner.TrackResult(path=None, status="failed", error="boom", fallback="wsl failed"),
        runner.TrackResult(path=None, status="cancelled"),
    ]
    text = queue_summary(results)
    assert "1 done" in text and "1 review" in text and "1 skipped" in text
    assert "1 failed" in text and "1 stopped" in text and "1 fallback" in text


def test_a_second_batch_starts_when_the_running_queue_ends(app, tmp_path, monkeypatch):
    w = MainWindow(tmp_path)
    try:
        audio = _audio(tmp_path, "later.flac")
        started = []
        monkeypatch.setattr(w, "process", lambda paths, redo=False: started.append((list(paths), redo)) or True)

        w._queue = object()          # a queue is already running
        w.enqueue_external([audio])
        assert w._external_backlog and not started
        assert "queued" in w.statusBar().currentMessage().lower()

        w._queue = None
        w._queue_started = time.monotonic()
        w._queue_results = []
        w._prog = {"done": 0, "total": 0}
        w._queue_finished()
        assert started and started[0][0] == [audio.resolve()]
    finally:
        w._queue = None
        w.dirty = False
        w.close()


def test_open_outside_the_library_switches_folder_and_selects(app, tmp_path):
    library = tmp_path / "library"
    _audio(library)
    outside = _audio(tmp_path / "elsewhere", "other.flac")
    w = MainWindow(library)
    try:
        w.open_external(outside)
        _wait(app, lambda: w.audio == outside)
        assert w.root == outside.parent
        assert config.library_root() == outside.parent
        assert w._queue is None
    finally:
        w.dirty = False
        w.close()


def test_a_long_queue_that_ends_unseen_uses_a_notification(app, tmp_path, monkeypatch):
    w = MainWindow(tmp_path)
    try:
        notices = []
        monkeypatch.setattr(w, "_notify", lambda title, message: notices.append((title, message)))
        w._queue_results = [runner.TrackResult(path=None, status="done"),
                            runner.TrackResult(path=None, status="review")]
        w._queue_started = time.monotonic()
        w._prog = {"done": 2, "total": 2}
        w._queue_finished()
        assert notices and notices[0][0] == "Queue finished"
        assert "2 done" not in notices[0][1] and "1 done" in notices[0][1]
        assert "1 review" in notices[0][1]
    finally:
        w.dirty = False
        w.close()
