import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QThread  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow  # noqa: E402

from lyricloom import updater  # noqa: E402
from lyricloom.app import dialogs  # noqa: E402
from lyricloom.app.dialogs import UpdateController  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(app, cond, timeout=20):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert cond()


def _in_gui() -> bool:
    return QThread.currentThread() is QApplication.instance().thread()


class FakeStatusBar:
    def __init__(self):
        self.records = []

    def showMessage(self, message, timeout=0):
        self.records.append(("status", _in_gui()))


class FakeProgress:
    records: list[tuple[str, bool]] = []

    def __init__(self, *args, **kwargs):
        pass

    def setWindowTitle(self, title):
        pass

    def setCancelButton(self, button):
        pass

    def setAutoClose(self, value):
        pass

    def setAutoReset(self, value):
        pass

    def show(self):
        self.records.append(("progress-show", _in_gui()))

    def close(self):
        self.records.append(("progress-close", _in_gui()))

    def setRange(self, low, high):
        self.records.append(("progress-range", _in_gui()))

    def setValue(self, value):
        self.records.append(("progress-value", _in_gui()))


class FakeWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.prepared = []
        self.records = []
        self._bar = FakeStatusBar()

    def statusBar(self):
        return self._bar

    def prepare_update(self, path):
        self.records.append(("prepare", _in_gui()))
        self.prepared.append(path)
        return False


def _info():
    return updater.UpdateInfo("9.9", "v9.9", "https://example.invalid", "", "Setup.exe",
                              "https://example.invalid/Setup.exe", 1, "")


def test_check_done_and_failure_run_in_the_gui_thread(app, monkeypatch):
    window = FakeWindow()
    controller = UpdateController(window)
    monkeypatch.setattr(updater, "check", lambda: _info())
    controller.check(silent=True)
    _wait(app, lambda: controller._check_thread is None)
    assert window._bar.records == [("status", True)]

    def broken():
        raise RuntimeError("no network")

    monkeypatch.setattr(updater, "check", broken)
    records = []
    monkeypatch.setattr(dialogs.QMessageBox, "warning",
                        lambda *a, **k: records.append(("warning", _in_gui())))
    controller.check()
    _wait(app, lambda: controller._check_thread is None)
    assert records == [("warning", True)]
    window.close()


def test_download_progress_and_done_run_in_the_gui_thread(app, monkeypatch):
    window = FakeWindow()
    controller = UpdateController(window)
    FakeProgress.records.clear()
    monkeypatch.setattr(dialogs, "QProgressDialog", FakeProgress)

    def fake_download(info, progress=None, cancel=None):
        progress(1, 2)
        return Path("Setup.exe")

    monkeypatch.setattr(updater, "download", fake_download)
    controller.download(_info())
    _wait(app, lambda: controller._download_thread is None)
    assert window.records == [("prepare", True)]
    assert window.prepared == [Path("Setup.exe")]
    assert FakeProgress.records and all(in_gui for _, in_gui in FakeProgress.records)
    window.close()


def test_download_failure_runs_in_the_gui_thread(app, monkeypatch):
    window = FakeWindow()
    controller = UpdateController(window)
    monkeypatch.setattr(dialogs, "QProgressDialog", FakeProgress)
    records = []
    monkeypatch.setattr(dialogs.QMessageBox, "critical",
                        lambda *a, **k: records.append(("critical", _in_gui())))

    def broken(info, progress=None, cancel=None):
        raise RuntimeError("download broke")

    monkeypatch.setattr(updater, "download", broken)
    controller.download(_info())
    _wait(app, lambda: controller._download_thread is None)
    assert records == [("critical", True)]
    window.close()


def test_shutdown_waits_for_a_running_update_check(app, monkeypatch):
    def slow_check():
        time.sleep(0.4)
        return None

    monkeypatch.setattr(updater, "check", slow_check)
    window = FakeWindow()
    controller = UpdateController(window)
    controller.check(silent=True)
    controller.shutdown()
    assert controller._threads and all(not thread.isRunning() for thread in controller._threads)
    window.close()


def test_main_window_close_stops_update_threads(app, tmp_path, monkeypatch):
    from lyricloom.app.main import MainWindow

    def slow_check():
        time.sleep(0.3)
        return None

    monkeypatch.setattr(updater, "check", slow_check)
    w = MainWindow(tmp_path)
    try:
        w._update_controller.check(silent=True)
        w.close()
        assert all(not thread.isRunning() for thread in w._update_controller._threads)
    finally:
        w.dirty = False
        w.close()
