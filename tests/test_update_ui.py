import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTextBrowser  # noqa: E402

from lyricloom import updater  # noqa: E402
from lyricloom.app import main as app_main  # noqa: E402
from lyricloom.app import update_ui  # noqa: E402
from lyricloom.app.dialogs import SettingsDialog  # noqa: E402
from lyricloom.app.main import MainWindow  # noqa: E402
from lyricloom.app.update_ui import ReleaseNotesDialog, UpdateBar  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def _info(notes="Fixed things."):
    return updater.UpdateInfo(
        "9.9", "v9.9", "https://github.com/nishizumi-maho/lyricloom/releases/tag/v9.9", notes,
        "LyricLoom-Setup.exe",
        "https://github.com/nishizumi-maho/lyricloom/releases/download/v9.9/LyricLoom-Setup.exe",
        10, "0" * 64,
        tarball_name="LyricLoom-9.9-linux-x86_64.tar.gz",
        tarball_url="https://github.com/nishizumi-maho/lyricloom/releases/download/v9.9/"
                    "LyricLoom-9.9-linux-x86_64.tar.gz",
    )


def test_update_bar_shows_the_version_and_only_the_modes_action():
    _app()
    bar = UpdateBar()
    bar.show_update(_info(), action_text="Restart now")
    assert bar.label.text() == "LyricLoom 9.9 is available"
    assert not bar.btn_action.isHidden() and bar.btn_action.text() == "Restart now"
    bar.show_update(_info(), action_text=None)
    assert bar.btn_action.isHidden()
    bar.show_update(_info(), show_tarball=True)
    assert not bar.btn_tarball.isHidden()
    bar.hide()
    bar.deleteLater()


def test_whats_new_opens_the_release_page_and_the_notes_popup(monkeypatch):
    _app()
    bar = UpdateBar()
    info = _info()
    opened = []
    dialogs = []

    class FakeNotes:
        def __init__(self, info, parent=None):
            dialogs.append(info)

        def show(self):
            pass

    monkeypatch.setattr(update_ui, "ReleaseNotesDialog", FakeNotes)
    monkeypatch.setattr(updater, "open_release_page", lambda release: opened.append(release))
    bar.show_update(info)
    bar.btn_whats_new.click()
    assert opened == [info]
    assert dialogs == [info]
    bar.deleteLater()


def test_release_notes_are_shown_in_a_scrollable_text_browser():
    _app()
    info = _info("Line one\nLine two")
    dialog = ReleaseNotesDialog(info)
    browser = dialog.findChild(QTextBrowser)
    assert browser is not None
    assert browser.toPlainText() == "Line one\nLine two"
    dialog.close()


def test_settings_show_the_new_defaults(monkeypatch):
    _app()
    monkeypatch.setattr(updater, "check_enabled", lambda: True)
    monkeypatch.setattr(updater, "install_mode", lambda: "auto")
    dialog = SettingsDialog()
    assert dialog.check_updates.isChecked()
    assert dialog.update_install.currentData() == "auto"
    dialog.close()


def test_main_window_schedules_the_startup_check_absent_but_not_when_disabled(tmp_path, monkeypatch):
    from lyricloom import config

    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    scheduled = []
    monkeypatch.setattr(app_main.QTimer, "singleShot",
                        staticmethod(lambda ms, function: scheduled.append(ms)))
    w = MainWindow(tmp_path)
    try:
        assert 4000 in scheduled
    finally:
        w.dirty = False
        w.close()

    config.set_setting("check_updates", False)
    scheduled.clear()
    w = MainWindow(tmp_path)
    try:
        assert 4000 not in scheduled
    finally:
        w.dirty = False
        w.close()


def test_main_window_rechecks_every_24_hours_when_enabled(tmp_path, monkeypatch):
    from lyricloom import config

    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    calls = []
    monkeypatch.setattr(updater, "cleanup_stale_downloads", lambda: calls.append("cleanup"))
    monkeypatch.setattr(app_main, "check_for_updates", lambda parent, silent=False: calls.append("check"))
    w = MainWindow(tmp_path)
    try:
        assert calls.count("cleanup") == 1
        assert w._update_timer.interval() == 24 * 60 * 60 * 1000
        monkeypatch.setattr(updater, "should_check_automatically", lambda: True)
        w._periodic_update_check()
        assert calls.count("check") == 1
        monkeypatch.setattr(updater, "should_check_automatically", lambda: False)
        w._periodic_update_check()
        assert calls.count("check") == 1
    finally:
        w.dirty = False
        w.close()


def test_install_on_exit_never_runs_during_a_queue(tmp_path, monkeypatch):
    from lyricloom import config

    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    w = MainWindow(tmp_path)
    try:
        path = tmp_path / "LyricLoom-Setup.exe"
        path.write_bytes(b"installer")
        w._update_controller._downloaded = path
        calls = []
        monkeypatch.setattr(updater, "install_mode", lambda: "auto")
        monkeypatch.setattr(updater, "launch_installer",
                            lambda *args, **kwargs: calls.append((args, kwargs)))
        w._queue = object()
        w._install_update_on_exit()
        assert calls == []
        w._queue = None
        w._install_update_on_exit()
        assert calls == [((path,), {"silent": True, "relaunch": False, "skip_plugin": False})]
    finally:
        w.dirty = False
        w.close()


def test_install_on_exit_ignores_a_skipped_download(tmp_path, monkeypatch):
    from lyricloom import config

    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    w = MainWindow(tmp_path)
    try:
        path = tmp_path / "LyricLoom-Setup.exe"
        path.write_bytes(b"installer")
        w._update_controller._info = _info()
        w._update_controller._downloaded = path
        w._update_controller._notice_skip()
        calls = []
        monkeypatch.setattr(updater, "install_mode", lambda: "auto")
        monkeypatch.setattr(updater, "launch_installer",
                            lambda *args, **kwargs: calls.append((args, kwargs)))
        w._install_update_on_exit()
        assert calls == []
        assert not path.exists()
    finally:
        w.dirty = False
        w.close()
