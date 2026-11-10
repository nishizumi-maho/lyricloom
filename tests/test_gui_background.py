"""FRB-04, FRB-07 and FRB-11: background work never runs or mutates GUI state on the GUI thread."""
import logging
import os
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from lyricloom.app import main as main_module  # noqa: E402
from lyricloom.app.main import FuncWorker, MainWindow  # noqa: E402
from lyricloom.app.models_window import ModelsWindow  # noqa: E402
from lyricloom.app.setup_assistant import SetupAssistant  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(app, condition, timeout=20):
    end = time.time() + timeout
    while not condition() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert condition()


def _audio(root, name="01 - Song.flac"):
    audio = root / "Artist" / "Album" / name
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"x")
    return audio


def test_preflight_checks_model_statuses_in_a_worker(app, tmp_path, monkeypatch):
    audio = _audio(tmp_path)
    main_thread = threading.current_thread()
    seen = []

    def status(spec):
        seen.append(threading.current_thread())
        return "ready"

    monkeypatch.setattr("lyricloom.models.status", status)
    w = MainWindow(tmp_path)
    monkeypatch.setattr(w, "_start_queue", lambda pending: True)
    try:
        assert w.process([audio]) is True
        _wait(app, lambda: seen and not w._preflight_running)
        assert seen and all(thread is not main_thread for thread in seen)
        assert w._pending_queue is None
    finally:
        w.dirty = False
        w.close()


def test_models_window_rows_are_checked_in_a_worker(app, monkeypatch):
    main_thread = threading.current_thread()
    seen = []
    monkeypatch.setattr("lyricloom.models.status",
                        lambda spec: seen.append(threading.current_thread()) or "ready")
    window = ModelsWindow()
    try:
        _wait(app, lambda: window._states and window._status_thread is None)
        assert seen and all(thread is not main_thread for thread in seen)
        assert window._items["whisper-large-v3"].text(2) == "Ready"
    finally:
        window.close()


def test_setup_assistant_models_page_is_checked_in_a_worker(app, monkeypatch):
    main_thread = threading.current_thread()
    seen = []
    monkeypatch.setattr("lyricloom.models.status",
                        lambda spec: seen.append(threading.current_thread()) or "ready")
    assistant = SetupAssistant()
    try:
        page = assistant.models_page
        page.initializePage()
        _wait(app, lambda: page._states and page._status_job is None)
        assert seen and all(thread is not main_thread for thread in seen)
        assert page.table.item(0, 2).text() == "Ready"
        assert "suggested models ready" in page.status_summary()
    finally:
        assistant.reject()


def test_the_first_run_model_offer_checks_in_a_worker(app, tmp_path, monkeypatch):
    main_thread = threading.current_thread()
    seen = []

    def status():
        seen.append(threading.current_thread())
        return {"whisper": True, "separator": True, "mms": True, "mtl": True}

    monkeypatch.setattr("lyricloom.app.main.runtime.status", status)
    monkeypatch.setattr("lyricloom.app.main.runtime._nltk_ready", lambda: True)
    monkeypatch.setattr("lyricloom.app.main.QMessageBox.question",
                        lambda *args, **kwargs: QMessageBox.No)
    w = MainWindow(tmp_path)
    try:
        w._offer_models()
        _wait(app, lambda: seen)
        assert seen and all(thread is not main_thread for thread in seen)
    finally:
        w.dirty = False
        w.close()


def test_diagnostics_statuses_are_read_in_a_worker(app, tmp_path, monkeypatch):
    main_thread = threading.current_thread()
    seen = []
    shown = []

    def build(root):
        seen.append((threading.current_thread(), Path(root)))
        return "diagnostics text"

    class FakeDialog:
        def __init__(self, text, parent=None):
            shown.append(text)

        def exec(self):
            return 0

    monkeypatch.setattr("lyricloom.app.main.diagnostics_text", build)
    monkeypatch.setattr("lyricloom.app.main.DiagnosticsDialog", FakeDialog)
    w = MainWindow(tmp_path)
    try:
        w.show_diagnostics()
        _wait(app, lambda: shown)
        assert seen and seen[0][0] is not main_thread and seen[0][1] == tmp_path
        assert shown == ["diagnostics text"]
    finally:
        w.dirty = False
        w.close()


def test_thread_bookkeeping_runs_on_the_gui_thread(app, tmp_path):
    main_thread = threading.current_thread()
    seen = []

    class RecordingWindow(MainWindow):
        def _thread_finished(self, thread):
            seen.append(threading.current_thread())
            super()._thread_finished(thread)

    w = RecordingWindow(tmp_path)
    try:
        w._run(FuncWorker(lambda: None), on_done=lambda _value: None)
        _wait(app, lambda: not w._threads)
        assert seen and all(thread is main_thread for thread in seen)
    finally:
        w.dirty = False
        w.close()


def test_finish_shutdown_uses_a_bounded_join_and_logs_a_warning(app, tmp_path, monkeypatch, caplog):
    calls = []

    class StuckThread:
        def quit(self):
            calls.append("quit")

        def wait(self, timeout_ms=None):
            calls.append(timeout_ms)
            return False

    monkeypatch.setattr(main_module, "_join_background_jobs", lambda: None)
    w = MainWindow(tmp_path)
    try:
        _wait(app, lambda: not w._threads)   # the window's first scan finishes before the fake
        w._threads = [(StuckThread(), object())]
        with caplog.at_level(logging.WARNING):
            w.finish_shutdown()
        assert calls == ["quit", main_module.BACKGROUND_JOIN_TIMEOUT_MS]
        assert "did not stop" in caplog.text
        w._threads = []
    finally:
        w.dirty = False
        w.close()
