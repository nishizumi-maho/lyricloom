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


class FakeBar:
    def __init__(self):
        self.shows = []
        self.on_action = None
        self.on_later = None
        self.on_skip = None
        self.visible = False

    def show_update(self, info, *, action_text=None, show_tarball=False,
                    on_action=None, on_later=None, on_skip=None):
        self.shows.append((info, action_text, show_tarball))
        self.on_action, self.on_later, self.on_skip = on_action, on_later, on_skip
        self.visible = True

    def hide(self):
        self.visible = False


class FakeWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.prepared = []
        self.records = []
        self._bar = FakeStatusBar()
        self.update_bar = FakeBar()

    def statusBar(self):
        return self._bar

    def prepare_update(self, path, *, info=None, silent=True, relaunch=True):
        self.records.append(("prepare", _in_gui()))
        self.prepared.append((path, silent, relaunch))
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
    assert window.prepared == [(Path("Setup.exe"), False, False)]
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


def test_auto_mode_downloads_in_the_background_and_arms_restart(app, tmp_path, monkeypatch):
    window = FakeWindow()
    controller = UpdateController(window)
    downloads = []
    path = tmp_path / "LyricLoom-Setup.exe"

    def fake_download(info, progress=None, cancel=None):
        downloads.append(info.version)
        return path

    monkeypatch.setattr(updater, "installer_available", lambda: True)
    monkeypatch.setattr(updater, "install_mode", lambda: "auto")
    monkeypatch.setattr(updater, "download", fake_download)
    controller.check_done(_info())
    _wait(app, lambda: controller._download_thread is None and controller._downloaded is not None)
    assert downloads == ["9.9"]
    assert window.update_bar.shows[-1][1] == "Restart now"
    assert controller._downloaded == path
    window.close()


def test_ask_mode_downloads_only_when_the_action_is_clicked(app, tmp_path, monkeypatch):
    window = FakeWindow()
    controller = UpdateController(window)
    downloads = []

    def fake_download(info, progress=None, cancel=None):
        downloads.append(info.version)
        return tmp_path / "LyricLoom-Setup.exe"

    monkeypatch.setattr(updater, "installer_available", lambda: True)
    monkeypatch.setattr(updater, "install_mode", lambda: "ask")
    monkeypatch.setattr(updater, "download", fake_download)
    controller.check_done(_info())
    assert downloads == []
    assert window.update_bar.shows[-1][1] == "Install now"
    window.update_bar.on_action()
    _wait(app, lambda: controller._download_thread is None)
    assert downloads == ["9.9"]
    assert window.prepared[-1][1:] == (False, False)
    window.close()


def test_notify_mode_never_downloads(app, monkeypatch):
    window = FakeWindow()
    controller = UpdateController(window)
    downloads = []
    monkeypatch.setattr(updater, "installer_available", lambda: True)
    monkeypatch.setattr(updater, "install_mode", lambda: "notify")
    monkeypatch.setattr(updater, "download", lambda *a, **k: downloads.append(1))
    controller.check_done(_info())
    assert downloads == []
    assert window.update_bar.shows[-1][1] is None
    window.close()


def test_skip_version_is_remembered_and_never_offered_again(app, tmp_path, monkeypatch):
    window = FakeWindow()
    controller = UpdateController(window)
    downloaded = tmp_path / "LyricLoom-Setup.exe"
    downloaded.write_bytes(b"installer")
    controller._info = _info()
    controller._downloaded = downloaded
    controller._notice_skip()
    assert updater.skipped_version() == "9.9"
    assert not downloaded.exists()
    shown = len(window.update_bar.shows)
    monkeypatch.setattr(dialogs.QMessageBox, "information", lambda *args, **kwargs: None)
    controller.check_done(_info())
    assert len(window.update_bar.shows) == shown
    window.close()


def test_download_for_an_older_offer_is_not_installed_as_a_newer_release(app, tmp_path):
    window = FakeWindow()
    controller = UpdateController(window)
    controller._info = updater.UpdateInfo("9.10", "v9.10", "https://example.invalid", "", "Setup.exe",
                                         "https://example.invalid/Setup.exe", 1, "")
    controller._download_info = _info()
    controller.download_done(tmp_path / "LyricLoom-Setup.exe")
    assert controller._downloaded is None
    window.close()


def test_latest_version_message_says_there_is_nothing_to_install(app, monkeypatch):
    window = FakeWindow()
    controller = UpdateController(window)
    messages = []
    monkeypatch.setattr(dialogs.QMessageBox, "information",
                        lambda *args, **kwargs: messages.append(args[2]))
    controller.check_done(None)
    assert messages == [f"You have the latest version (LyricLoom {dialogs.VERSION})."]
    window.close()


def test_skip_during_a_download_never_arms_the_skipped_version(app, tmp_path, monkeypatch):
    """M4: "Skip this version" while the installer downloads cancels it and discards the file."""
    window = FakeWindow()
    controller = UpdateController(window)
    monkeypatch.setattr(updater, "installer_available", lambda: True)
    monkeypatch.setattr(updater, "install_mode", lambda: "auto")
    info = _info()
    controller._info = info
    controller._download_info = info
    controller._download_automatic = True
    controller._download_thread = object()      # a download is running
    path = tmp_path / "LyricLoom-Setup.exe"
    path.write_bytes(b"installer")
    controller._notice_skip()
    assert controller._cancel.is_set()
    controller._download_thread = None
    controller.download_done(str(path))
    assert controller._downloaded is None
    assert not path.exists()
    assert window.prepared == []
    window.close()
