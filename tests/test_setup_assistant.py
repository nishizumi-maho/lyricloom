import os
import logging
import threading
import time
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricloom import config, runner, setup  # noqa: E402
from lyricloom.app import main as main_module  # noqa: E402
from lyricloom.app import dialogs  # noqa: E402
from lyricloom.app import setup_assistant as setup_assistant_module  # noqa: E402
from lyricloom.app.main import MainWindow  # noqa: E402
from lyricloom.app.setup_assistant import ASK_BEFORE_UPLOAD, SetupAssistant  # noqa: E402
from lyricloom.workers import WorkerCancelled  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(app, condition, timeout=10):
    end = time.time() + timeout
    while not condition() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert condition()


def _imports(**overrides):
    values = {name: True for name in setup.WslEnvironment.REQUIRED_IMPORTS}
    values.update(overrides)
    return values


def _environment(*, passed=True, distro="Ubuntu", python="/opt/lyricloom/venv/bin/python"):
    return setup.WslEnvironment(
        distro=distro, python=python, python_version="3.12.3", torch_version="2.14.1+rocm7.2",
        gpu_available=passed, device_name="AMD Radeon RX 6900 XT", backend="rocm" if passed else "cpu",
        imports=_imports() if passed else _imports(torch=False),
        error=None if passed else "ModuleNotFoundError: torch")


def _report():
    return setup.SystemReport(
        os_name="Windows 11", cpu_cores=8, ram_bytes=16 * setup.GiB,
        gpus=(setup.GpuAdapter("AMD Radeon RX 6900 XT", "amd", 16 * setup.GiB),),
        wsl=setup.WslState(installed=True, version2=True,
                           distros=(setup.WslDistro("Ubuntu", "Running", 2, True),)))


def test_setup_assistant_is_shown_on_first_start_and_not_after_setup_complete(app, tmp_path, monkeypatch):
    config.set_library_root(tmp_path)   # the window's root and the saved library agree
    w = MainWindow(tmp_path)
    calls = []
    try:
        _wait(app, lambda: not w._threads)   # the library scan thread has finished
        monkeypatch.setattr(w, "open_setup_assistant", lambda *a, **k: calls.append(a))
        w._first_run()
        assert len(calls) == 1
        config.set_setting("setup_complete", True)
        w._first_run()
        assert len(calls) == 1
    finally:
        w.dirty = False
        w.close()
        w.finish_shutdown()


def test_use_this_is_enabled_only_for_a_passing_wsl_environment(app, tmp_path):
    assistant = SetupAssistant()
    try:
        page = assistant.acceleration_page
        failing = _environment(passed=False, distro="Ubuntu")
        passing = _environment(passed=True, distro="Debian", python="/opt/torch/bin/python")
        page._environments_found([failing, passing])
        assert page.existing_combo.count() == 2

        page.existing_combo.setCurrentIndex(0)
        assert not page.use_btn.isEnabled()
        page.existing_combo.setCurrentIndex(1)
        assert page.use_btn.isEnabled()

        page.use_environment()
        assert config.setting("wsl_gpu") is True
        assert config.setting("wsl_distro") == "Debian"
        assert config.setting("wsl_python") == "/opt/torch/bin/python"
    finally:
        assistant.reject()


def test_a_cancelled_wsl_setup_leaves_the_settings_untouched(app, tmp_path, monkeypatch):
    assistant = SetupAssistant()
    try:
        page = assistant.acceleration_page
        wheel = tmp_path / "lyricloom-2.1.0-py3-none-any.whl"
        wheel.write_bytes(b"wheel")
        page._wsl_wheel = wheel
        before = config.all_settings()

        def cancelled(distro, backend, wheel_path, on_line=None, cancel=None):
            assert cancel is not None
            while not cancel.is_set():
                time.sleep(0.01)
            raise WorkerCancelled

        monkeypatch.setattr(setup, "run_wsl_setup", cancelled)
        page.start_wsl_setup()
        _wait(app, lambda: page._job is not None)
        page._cancel_wsl_setup()
        _wait(app, lambda: page._job is None)
        assert config.all_settings() == before
        assert "cancelled" in page.existing_status.text().lower()
    finally:
        assistant.reject()


def test_the_blas_install_sets_whisper_cli_through_the_engine(app, tmp_path, monkeypatch):
    assistant = SetupAssistant()
    try:
        page = assistant.acceleration_page
        data = tmp_path / "data"
        monkeypatch.setattr(config, "APP_DATA", data)
        page.transcription.setCurrentIndex(page.transcription.findData("blas"))
        real_install = setup.install_whisper_backend

        def download(spec, destination, progress=None, cancel=None):
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(destination, "w") as bundle:
                bundle.writestr("Release/whisper-cli.exe", b"fake exe")
            return destination

        def wrapper(name, progress=None, cancel=None):
            return real_install(name, progress=progress, cancel=cancel, download=download,
                                runner=lambda *args, **kwargs: setup.CommandResult(0, b"usage"))

        monkeypatch.setattr(setup, "install_whisper_backend", wrapper)
        page.install_transcription()
        _wait(app, lambda: page._job is None)
        installed = Path(str(config.setting("whisper_cli")))
        assert installed.is_file()
        assert installed.name == "whisper-cli.exe"
        assert "installed" in page.existing_status.text().lower()
    finally:
        assistant.reject()


def test_the_privacy_page_writes_the_update_choice_and_cloud_flag(app, tmp_path):
    assistant = SetupAssistant()
    try:
        page = assistant.privacy_page
        page.check_updates.setChecked(True)
        page.cloud.setChecked(True)
        page.ask.setChecked(False)
        assert page.apply() is True
        assert config.setting("check_updates") is True
        assert config.assemblyai_enabled() is True
        assert config.setting(ASK_BEFORE_UPLOAD) is False
    finally:
        assistant.reject()


def test_finish_writes_setup_complete(app, tmp_path):
    config.set_library_root(tmp_path)
    assistant = SetupAssistant()
    try:
        assistant.accept()
        assert config.setting("setup_complete") is True
    finally:
        assistant.reject()


def test_declining_cloud_consent_passes_allow_cloud_false(app, tmp_path, monkeypatch):
    audio = tmp_path / "Artist" / "Album" / "01 - Song.flac"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"x")
    config.set_assemblyai_enabled(True)
    config.set_setting(ASK_BEFORE_UPLOAD, True)
    w = MainWindow(tmp_path)
    seen = []
    try:
        monkeypatch.setattr(w, "_ask_cloud_for_queue", lambda: False)
        monkeypatch.setattr(w, "_preflight", lambda *a, **k: True)

        def process(path, **kwargs):
            seen.append(kwargs)
            return runner.TrackResult(path, "done")

        monkeypatch.setattr(main_module.runner, "process", process)
        assert w.process([audio]) is True
        _wait(app, lambda: w._queue is None)
        assert seen and seen[0]["allow_cloud"] is False
    finally:
        w.dirty = False
        w.close()


def test_privacy_page_defaults_to_update_checks_on_and_saves_the_install_mode(app):
    """Owner decision: update checks are on by default, with automatic installation."""
    from lyricloom.app.setup_assistant import PrivacyPage

    page = PrivacyPage()
    assert page.check_updates.isChecked()
    assert page.update_install.currentData() == "auto"
    page.update_install.setCurrentIndex(page.update_install.findData("notify"))
    assert page.apply()
    assert config.setting("check_updates") is True
    assert config.setting("update_install") == "notify"
    page.check_updates.setChecked(False)
    assert not page.update_install.isEnabled()
    assert page.apply()
    assert config.setting("check_updates") is False


def test_skipped_plugin_notice_offers_the_musicbee_page(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from lyricloom import updater

    # The setting holds the version the skipping install was installing: this build's.
    config.set_setting(updater.PLUGIN_SKIP_NOTICE_SETTING, updater.VERSION)
    opened = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "clickedButton",
                        lambda self: next(b for b in self.buttons() if b.text().startswith("Open")))
    w = MainWindow(tmp_path)
    try:
        monkeypatch.setattr(w, "open_setup_assistant", lambda page=None: opened.append(page))
        w._show_pending_plugin_notice()
        assert opened == ["musicbee"]
        w._show_pending_plugin_notice()   # shown once
        assert opened == ["musicbee"]
    finally:
        w.dirty = False
        w.close()


# ---------- FRB-06: setup threads are cancelled, joined and logged ----------

def test_the_system_check_honours_a_cancel_before_and_after_detection(monkeypatch):
    class Worker:
        def __init__(self):
            self.cancel = threading.Event()

    worker = Worker()
    worker.cancel.set()
    with pytest.raises(WorkerCancelled):
        setup_assistant_module._detect(worker)

    worker = Worker()

    def detect():
        worker.cancel.set()
        return object()

    monkeypatch.setattr(setup_assistant_module.setup, "detect", detect)
    with pytest.raises(WorkerCancelled):
        setup_assistant_module._detect(worker)


def test_a_job_that_ignores_cancel_logs_and_is_not_destroyed(app, caplog):
    started, release = threading.Event(), threading.Event()

    def stuck(worker):
        started.set()
        release.wait(5)

    job = setup_assistant_module._Job(stuck)
    job.start()
    assert started.wait(3)
    try:
        with caplog.at_level(logging.WARNING):
            assert job.stop(wait_ms=10) is False
        assert "did not stop" in caplog.text
        assert job.is_busy()
    finally:
        release.set()
        assert job.stop(wait_ms=5000) is True
        job.close()
    assert not job.is_busy()


def test_join_background_jobs_closes_every_kept_job(monkeypatch):
    calls = []

    class FakeJob:
        def close(self, wait_ms=5000):
            calls.append(wait_ms)

    monkeypatch.setattr(setup_assistant_module, "_KEEP_ALIVE", [FakeJob()])
    setup_assistant_module.join_background_jobs(123)
    assert calls == [123]


def test_join_test_threads_quits_a_running_acceleration_test(monkeypatch):
    calls = []

    class FakeThread:
        def isRunning(self):
            return True

        def quit(self):
            calls.append("quit")

        def wait(self, timeout_ms):
            calls.append(timeout_ms)
            return True

    monkeypatch.setattr(dialogs, "_TEST_KEEP_ALIVE", [(FakeThread(), object())])
    dialogs.join_test_threads(77)
    assert calls == ["quit", 77]
