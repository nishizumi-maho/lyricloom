import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from lyricloom import config, downloads, models, runner  # noqa: E402
from lyricloom.app import model as app_model  # noqa: E402
from lyricloom.app.main import (BUSY_INSTANCE_MESSAGE, FILTERS, MainWindow, QueueItem,  # noqa: E402
                                QueueWorker, handle_busy_instance)
from lyricloom.app.models_window import ModelsWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(app, cond, timeout=20):
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


LRC = ("[re:LyricLoom 2.0.0]\n[#source:demo conf:0.90]\n"
       "[#models:transcribe={transcribe};separate=separator-mel-band-roformer;"
       "align=align-mms-fa]\n[00:01.00]x\n")


def test_model_rows_are_grouped_and_show_statuses(app, monkeypatch):
    states = {"whisper-large-v3": "ready", "separator-mel-band-roformer": "missing",
              "align-mms-fa": "corrupt", "singing-mtl": "unverified"}
    monkeypatch.setattr("lyricloom.app.models_window.models.status",
                        lambda spec, root=None, verify=False: states.get(spec.id, "missing"))
    window = ModelsWindow()
    try:
        assert window.tree.topLevelItemCount() == 4
        assert [window.tree.topLevelItem(i).text(0) for i in range(4)] == [
            "Transcription", "Vocal separation", "Alignment", "Singing model"]
        _wait(app, lambda: window._items["whisper-large-v3"].text(2) == "Ready")
        assert window._items["whisper-large-v3"].text(2) == "Ready"
        assert window._items["separator-mel-band-roformer"].text(2) == "Missing"
        assert window._items["align-mms-fa"].text(2) == "Corrupt"
        assert window._items["singing-mtl"].text(2) == "Unverified"
        assert window._items["whisper-large-v3"].text(1)          # size
        assert window._items["whisper-large-v3"].text(4)          # license
        assert window._items["whisper-large-v3"].text(3) == "default"

        assert window.apply_language_choice(models.get("whisper-small"), "ja")
        assert "ja" in window._items["whisper-small"].text(3)
    finally:
        window.close()


def test_a_download_reports_progress_and_can_be_cancelled(app, monkeypatch):
    started = []
    cancelled = []

    def fake_download(spec, progress=None, cancel=None, root=None):
        started.append(spec.id)
        if progress:
            progress(50, 100)
        while cancel is not None and not cancel.is_set():
            time.sleep(0.01)
        cancelled.append(spec.id)
        raise downloads.DownloadCancelled("cancelled")

    monkeypatch.setattr("lyricloom.app.models_window.models.download", fake_download)
    monkeypatch.setattr("lyricloom.app.models_window.free_space_error",
                        lambda specs, root=None: None)
    window = ModelsWindow()
    spec = models.get("whisper-small")
    try:
        assert window.start_download([spec])
        _wait(app, lambda: "Downloading" in window._items[spec.id].text(2))
        assert "50%" in window._items[spec.id].text(2)
        assert "50%" in window.progress.format()
        window.cancel_job()
        _wait(app, lambda: window._thread is None)
        assert started == [spec.id] and cancelled == [spec.id]
        assert not window.cancel_btn.isEnabled()
    finally:
        if window._thread is not None:
            window.cancel_job()
            _wait(app, lambda: window._thread is None)
        window.close()


def test_escape_during_a_download_does_not_start_a_second(app, monkeypatch):
    started = []

    def fake_download(spec, progress=None, cancel=None, root=None):
        started.append(spec.id)
        while cancel is not None and not cancel.is_set():
            time.sleep(0.01)
        raise downloads.DownloadCancelled("cancelled")

    monkeypatch.setattr("lyricloom.app.models_window.models.download", fake_download)
    monkeypatch.setattr("lyricloom.app.models_window.free_space_error",
                        lambda specs, root=None: None)
    answers = iter([QMessageBox.No, QMessageBox.Yes])
    monkeypatch.setattr("lyricloom.app.models_window.QMessageBox.question",
                        lambda *a, **k: next(answers))
    window = ModelsWindow()
    spec = models.get("whisper-small")
    window.show()
    try:
        assert window.start_download([spec])
        _wait(app, lambda: "Downloading" in window._items[spec.id].text(2))
        QTest.keyClick(window, Qt.Key_Escape)
        app.processEvents()
        assert started == [spec.id]                 # Esc did not start another download
        assert window._thread is not None           # and did not destroy the running one
        window.close()                              # says Yes: cancel and close
        _wait(app, lambda: window._thread is None)
        assert started == [spec.id]
    finally:
        if window._thread is not None:
            window.cancel_job()
            _wait(app, lambda: window._thread is None)
        window.close()


def test_a_download_is_refused_when_the_models_folder_has_no_space(app, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr("lyricloom.app.models_window.shutil.disk_usage",
                        lambda path: SimpleNamespace(free=0))
    warnings = []
    monkeypatch.setattr("lyricloom.app.models_window.QMessageBox.warning",
                        lambda parent, title, text: warnings.append((title, text)))
    monkeypatch.setattr("lyricloom.app.models_window.models.download",
                        lambda *a, **k: pytest.fail("a download must not start without disk space"))
    window = ModelsWindow()
    spec = models.get("whisper-small")
    try:
        assert window.start_download([spec]) is False
        assert window._thread is None
        assert warnings and "Not enough free disk space" in warnings[0][1]
        assert str(config.MODELS) in warnings[0][1]
    finally:
        window.close()


def test_use_for_a_language_writes_the_choice(app, monkeypatch):
    window = ModelsWindow()
    spec = models.get("whisper-small")
    try:
        window.select_specs([spec])
        monkeypatch.setattr("lyricloom.app.models_window.QInputDialog.getItem",
                            lambda *a, **k: ("ja — Japanese", True))
        assert window.use_for_language()
        assert config.resolve_model("transcribe", "ja").id == "whisper-small"
        assert "ja" in models.choices_for(spec)

        # Choosing "(default)" in the language section removes the override again.
        index = window.language_combo.findData("ja")
        assert index >= 0
        window.language_combo.setCurrentIndex(index)
        assert window._language_combos["transcribe"].currentData() == "whisper-small"
        window._language_combos["transcribe"].setCurrentIndex(0)
        assert config.resolve_model("transcribe", "ja").id == "whisper-large-v3"
        assert "ja" not in models.choices_for(spec)
    finally:
        window.close()


def test_removing_a_custom_model_keeps_the_users_file(app, tmp_path, monkeypatch):
    custom = tmp_path / "my-model.bin"
    custom.write_bytes(b"custom bytes")
    spec = models.add("transcribe", str(custom))
    monkeypatch.setattr("lyricloom.app.models_window.QMessageBox.question",
                        lambda *a, **k: QMessageBox.Yes)
    window = ModelsWindow()
    try:
        assert spec.id in window._items
        window.select_specs([spec])
        assert window.remove_custom_model()
        assert custom.read_bytes() == b"custom bytes"
        assert spec.id not in window._items
        assert models.find(spec.id) is None
    finally:
        window.close()


def test_preflight_blocks_the_queue_when_a_model_is_missing(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    w = MainWindow(tmp_path)
    try:
        monkeypatch.setattr("lyricloom.app.main.model_catalog.status",
                            lambda spec: "missing" if spec.id == "separator-mel-band-roformer"
                            else "ready")
        asked = []
        monkeypatch.setattr(w, "_ask_missing_models",
                            lambda specs: asked.append(list(specs)) or "cancel")
        # The status check runs in a worker now, so the call is accepted first (FRB-04).
        assert w.process([audio]) is True
        _wait(app, lambda: asked)
        assert asked and asked[0][0].id == "separator-mel-band-roformer"
        assert w._queue is None
    finally:
        w.dirty = False
        w.close()


def test_search_lyrics_again_preflights_only_the_alignment_model(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    w = MainWindow(tmp_path)
    asked = []
    monkeypatch.setattr("lyricloom.app.main.model_catalog.status",
                        lambda spec: "missing" if spec.id == "align-mms-fa" else "ready")
    monkeypatch.setattr(w, "_ask_missing_models",
                        lambda specs: asked.append(list(specs)) or "cancel")
    try:
        # The transcription model may be missing: "Search lyrics again" reuses everything but the
        # alignment, so only the alignment model blocks the queue.
        assert w.process([audio], research=True) is True
        _wait(app, lambda: asked)
        assert [spec.id for spec in asked[0]] == ["align-mms-fa"]
        assert w._queue is None
    finally:
        w.dirty = False
        w.close()


def test_a_missing_models_pause_still_honours_stop_after_this_song(tmp_path, monkeypatch):
    first, second = _audio(tmp_path), _audio(tmp_path, "02 - Other.flac")
    spec = models.get("align-mms-fa")
    calls = []

    def fake_process(path, **kwargs):
        calls.append(path)
        return runner.TrackResult(path, "failed", error="missing models", missing=[spec])

    def stop_after(specs):
        worker.stop()

    monkeypatch.setattr("lyricloom.runner.process", fake_process)
    worker = QueueWorker([first, second], force=True)
    worker.missing_models.connect(stop_after)
    rows = []
    worker.track_done.connect(rows.append)
    worker.run()

    assert calls == [first]          # paused on the missing model, then the stop won
    # The started track must get a terminal row, not stay "processing" forever (FRB-08).
    assert len(rows) == 1 and rows[0].path == first
    assert rows[0].status == "cancelled" and "waiting for models" in rows[0].error


def test_missing_models_failure_pauses_and_retries_the_track(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    spec = models.get("align-mms-fa")
    calls = []

    def fake_process(path, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return runner.TrackResult(path, "failed", error="missing models", missing=[spec])
        return runner.TrackResult(path, "done")

    monkeypatch.setattr("lyricloom.runner.process", fake_process)
    worker = QueueWorker([audio], force=True)
    seen = []
    worker.missing_models.connect(lambda specs: (seen.append(list(specs)), worker.resume()))
    rows = []
    worker.track_done.connect(rows.append)
    worker.run()

    assert seen and seen[0][0].id == spec.id
    assert len(calls) == 2                      # the same track ran again after the resume
    assert rows and rows[-1].path == audio


def test_a_finished_unrelated_download_does_not_resume_the_paused_queue(app, tmp_path, monkeypatch):
    w = MainWindow(tmp_path)
    spec = models.get("align-mms-fa")
    results = []
    monkeypatch.setattr("lyricloom.models.status", lambda spec: "missing")
    try:
        w._models_after_download = [((spec,), results.append)]
        w._models_downloads_finished(True)
        _wait(app, lambda: results)
        assert results == [False]          # the missing model is still missing
    finally:
        w._models_after_download = []
        w.dirty = False
        w.close()


def test_a_download_resumes_only_when_the_requested_model_is_ready(app, tmp_path, monkeypatch):
    w = MainWindow(tmp_path)
    spec = models.get("align-mms-fa")
    results = []
    monkeypatch.setattr("lyricloom.models.status", lambda spec: "ready")
    try:
        w._models_after_download = [((spec,), results.append)]
        w._models_downloads_finished(True)
        _wait(app, lambda: results)
        assert results == [True]
    finally:
        w._models_after_download = []
        w.dirty = False
        w.close()


def test_a_missing_models_failure_pauses_the_window_queue(app, tmp_path, monkeypatch):
    w = MainWindow(tmp_path)
    spec = models.get("align-mms-fa")

    class FakeQueue:
        paused = False
        resumed = False

        def pause(self):
            self.paused = True

        def resume(self):
            self.resumed = True

    queue = FakeQueue()
    try:
        w._queue = queue

        def offer(specs, callback=None):
            assert specs == [spec]
            if callback is not None:
                callback(True)
            return "download"

        monkeypatch.setattr(w, "_offer_missing_models", offer)
        w._queue_missing_models([spec])
        assert queue.paused and queue.resumed
        assert w.btn_pause.text() == "Pause after this song"
    finally:
        w._queue = None
        w.dirty = False
        w.close()


def test_per_song_options_reach_runner_process(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    w = MainWindow(tmp_path)
    seen = []

    class FakeDialog:
        def exec(self):
            return QDialog.Accepted

        def chosen_models(self):
            return {"transcribe": "whisper-small", "separate": "separator-mdx-voc-ft"}

    def fake_process(path, **kwargs):
        seen.append(kwargs.get("models"))
        return runner.TrackResult(path, "done")

    try:
        monkeypatch.setattr("lyricloom.app.main.PerSongModelsDialog", lambda parent: FakeDialog())
        monkeypatch.setattr("lyricloom.runner.process", fake_process)
        monkeypatch.setattr(w, "_preflight", lambda *a, **k: True)
        w._process_with_other_models([audio])
        _wait(app, lambda: w._queue is None)
        assert seen == [{"transcribe": "whisper-small", "separate": "separator-mdx-voc-ft"}]
    finally:
        w.dirty = False
        w.close()


def test_a_per_song_queue_item_passes_its_models(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    seen = {}

    def fake_process(path, **kwargs):
        seen.update(kwargs)
        return runner.TrackResult(path, "done")

    monkeypatch.setattr("lyricloom.runner.process", fake_process)
    worker = QueueWorker([QueueItem(audio, {"transcribe": "whisper-small"})], force=True)
    worker.run()
    assert seen["models"] == {"transcribe": "whisper-small"}


def test_marker_and_filter_for_a_song_made_with_other_models(app, tmp_path):
    audio = _audio(tmp_path)
    lrc = audio.with_suffix(".lrc")
    lrc.write_text(LRC.format(transcribe="whisper-small"), encoding="utf-8")
    w = MainWindow(tmp_path)
    try:
        _wait(app, lambda: w.proxy.rowCount() == 1)
        row = w.rows[0]
        assert app_model.other_model_stages(row) == ["transcribe"]
        assert "Transcription" in app_model.other_models_text(row)
        notes = w.model.index(0, 5)
        assert "⇄ other" in notes.data()
        assert "whisper-small" in notes.data(Qt.ToolTipRole)

        w.filter.setCurrentIndex(FILTERS.index("Made with other models"))
        assert w.proxy.rowCount() == 1

        # A song made with exactly the current choices is not marked and the filter hides it.
        lrc.write_text(LRC.format(transcribe="whisper-large-v3"), encoding="utf-8")
        the_time = time.time() + 2
        os.utime(lrc, (the_time, the_time))
        w.refresh()
        _wait(app, lambda: w.proxy.rowCount() == 0)
        assert app_model.other_model_stages(w.rows[0]) == []
    finally:
        w.dirty = False
        w.close()


def test_track_table_model_marks_a_song_made_with_other_models(app, tmp_path):
    from lyricloom.app.library import TrackTableModel

    audio = _audio(tmp_path)
    lrc = audio.with_suffix(".lrc")
    lrc.write_text(LRC.format(transcribe="whisper-small"), encoding="utf-8")
    model = TrackTableModel([app_model.read_status(audio)])
    notes = model.index(0, 5)
    assert "⇄ other" in notes.data()
    tooltip = notes.data(Qt.ToolTipRole)
    assert "Made with other models" in tooltip
    assert "Transcription" in tooltip and "whisper-small" in tooltip

    # Exactly the current default is not marked.
    lrc.write_text(LRC.format(transcribe=config.resolve_model("transcribe").id), encoding="utf-8")
    same = TrackTableModel([app_model.read_status(audio)])
    assert "other" not in same.index(0, 5).data()


def test_proxy_filters_songs_made_with_other_models(app, tmp_path):
    from lyricloom.app.library import TrackFilterProxyModel, TrackTableModel

    other = _audio(tmp_path, "01 - Other.flac")
    other.with_suffix(".lrc").write_text(LRC.format(transcribe="whisper-small"), encoding="utf-8")
    same = _audio(tmp_path, "02 - Same.flac")
    same.with_suffix(".lrc").write_text(
        LRC.format(transcribe=config.resolve_model("transcribe").id), encoding="utf-8")
    model = TrackTableModel([app_model.read_status(other), app_model.read_status(same)])
    proxy = TrackFilterProxyModel()
    proxy.setSourceModel(model)
    assert proxy.rowCount() == 2

    proxy.set_status_filter("Made with other models")
    assert proxy.rowCount() == 1
    assert proxy.index(0, 0).data() == "Artist"

    proxy.set_status_filter("All")
    proxy.set_search_text("made with other models")
    assert proxy.rowCount() == 1


def test_library_context_menu_starts_per_song_models_and_a_full_redo(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    audio.with_suffix(".lrc").write_text(LRC.format(transcribe="whisper-small"), encoding="utf-8")
    w = MainWindow(tmp_path)
    target = {"text": "Redo with current models"}

    class FakeAction:
        def __init__(self, text):
            self._text = text
            self.enabled = True

        def text(self):
            return self._text

        def setEnabled(self, enabled):
            self.enabled = enabled

    class FakeMenu:
        def __init__(self, parent=None):
            self.items = []

        def addAction(self, text):
            action = FakeAction(text)
            self.items.append(action)
            return action

        def addSeparator(self):
            pass

        def exec(self, pos):
            return next(action for action in self.items if action.text() == target["text"])

    class FakeDialog:
        def exec(self):
            return QDialog.Accepted

        def chosen_models(self):
            return {"transcribe": "whisper-small"}

    calls = []

    def fake_process(paths, **kwargs):
        calls.append((list(paths), kwargs))
        return True

    monkeypatch.setattr("lyricloom.app.main.QMenu", FakeMenu)
    monkeypatch.setattr("lyricloom.app.main.PerSongModelsDialog", lambda parent: FakeDialog())
    monkeypatch.setattr(w, "process", fake_process)
    try:
        _wait(app, lambda: w.proxy.rowCount() == 1)
        index = w.proxy.index(0, 0)
        monkeypatch.setattr(w.table, "indexAt", lambda pos: index)
        monkeypatch.setattr(w, "_selected_rows", lambda: list(w.rows))

        w._table_context_menu(QPoint(0, 0))
        assert calls[-1] == ([audio], {"force": True})

        target["text"] = "Process with other models…"
        w._table_context_menu(QPoint(0, 0))
        assert calls[-1] == ([audio], {"models": {"transcribe": "whisper-small"}})
    finally:
        w.dirty = False
        w.close()


def test_busy_instance_retries_with_the_long_timeout(monkeypatch):
    class FakeServer:
        def remove_stale(self, probe_ms=5000):
            return False

    calls, notices = [], []

    def fake_send(command, timeout_ms=2000):
        calls.append((command, timeout_ms))
        return {"ok": True}

    assert handle_busy_instance(FakeServer(), {"cmd": "activate"}, send=fake_send,
                                notify=notices.append) is True
    assert calls == [({"cmd": "activate"}, 10_000)]
    assert notices == []


def test_busy_instance_explains_when_nobody_answers():
    class FakeServer:
        def remove_stale(self, probe_ms=5000):
            return False

    notices = []
    assert handle_busy_instance(FakeServer(), {"cmd": "activate"},
                                send=lambda *a, **k: None, notify=notices.append) is True
    assert notices == [BUSY_INSTANCE_MESSAGE]


def test_busy_instance_removes_a_stale_name_and_stays():
    class FakeServer:
        def remove_stale(self, probe_ms=5000):
            return True

    def must_not_send(*a, **k):
        raise AssertionError("a stale name must not be probed with a command")

    assert handle_busy_instance(FakeServer(), {"cmd": "activate"}, send=must_not_send) is False


def test_main_window_marks_a_late_race_as_a_duplicate_instance(app, tmp_path, monkeypatch):
    class FakeServer:
        name = "LyricLoom-test-busy"

        @property
        def is_listening(self):
            return False

        def listen(self):
            return False

        def remove_stale(self, probe_ms=5000):
            return False

        def close(self):
            pass

    calls = []
    monkeypatch.setattr("lyricloom.app.main.ipc_send",
                        lambda command, timeout_ms=2000: calls.append(timeout_ms) or {"ok": True})
    w = MainWindow(tmp_path, server=FakeServer())
    try:
        assert w._duplicate_instance
        assert calls == [10_000]
    finally:
        w.dirty = False
        w.close()
