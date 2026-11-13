"""The assistant's "GPU on Windows" group, with a fake in place of the real installation."""
import os
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from lyricloom import config, gpu_runtime, setup  # noqa: E402
from lyricloom.app.setup_assistant import SetupAssistant  # noqa: E402
from lyricloom.workers import WorkerCancelled  # noqa: E402


# The page drives a Windows-only feature, and the assistant's summary reads the Windows registry.
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the Windows GPU runtime")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def windows(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "IS_WINDOWS", True)
    monkeypatch.setattr(config, "RUNTIMES", tmp_path / "runtimes")


@pytest.fixture
def boxes(monkeypatch):
    """Records message boxes instead of showing them; questions are answered Yes."""
    shown = []
    for kind in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, kind,
                            lambda parent, title, text, _kind=kind: shown.append((_kind, text)))
    monkeypatch.setattr(QMessageBox, "question",
                        lambda parent, title, text: shown.append(("question", text))
                        or QMessageBox.Yes)
    return shown


def _wait(app, condition, timeout=10):
    end = time.time() + timeout
    while not condition() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert condition()


def _report(name="NVIDIA GeForce RTX 3060", vendor="nvidia"):
    return setup.SystemReport(
        os_name="Windows 11", cpu_cores=8, ram_bytes=16 * setup.GiB,
        disk_free_bytes=200 * setup.GiB,
        gpus=(setup.GpuAdapter(name, vendor, 12 * setup.GiB),),
        wsl=setup.WslState(installed=False))


def _environment(backend="cuda", device="NVIDIA GeForce RTX 3060", python="python.exe"):
    imports = {name: True for name in ("torch", "torchaudio", "audio_separator", "g2p_en",
                                       "nltk", "lyricloom")}
    return gpu_runtime.RuntimeEnvironment(
        python=python, torch_version="2.5.1+cu124", gpu_available=True, device_name=device,
        backend=backend, imports=imports)


def test_a_successful_setup_selects_the_runtime_without_a_restart(app, monkeypatch, boxes):
    assistant = SetupAssistant()
    try:
        page = assistant.acceleration_page
        page._apply_report(_report())
        assert page.gpu_backend.currentData() == "cuda"
        config.update_settings({"wsl_gpu": True})
        seen = {}

        def install(backend, gpu_name="", on_line=None, cancel=None):
            seen.update(backend=backend, gpu_name=gpu_name)
            on_line("@@step 3/5 Installing PyTorch for NVIDIA GPU")
            on_line("Downloading torch (2.4GiB)")
            return gpu_runtime.RuntimeResult(ok=True, backend=backend, python="python.exe",
                                             environment=_environment())

        monkeypatch.setattr(gpu_runtime, "install", install)
        page.start_gpu_setup()
        _wait(app, lambda: page._job is None)
        assert seen == {"backend": "cuda", "gpu_name": "NVIDIA GeForce RTX 3060"}
        assert config.gpu_runtime() == ("cuda", "python.exe")
        assert config.setting("wsl_gpu") is False
        assert "no restart is needed" in page.gpu_status.text()
        assert "NVIDIA GeForce RTX 3060" in page.gpu_status.text()
        assert page.gpu_log.rowCount() == 2
        assert page.gpu_progress.format() == "Finished"
        assert not page.cpu_radio.isChecked()
        assert "in use" in page.gpu_note.text()
        assert boxes == []
        assert "NVIDIA GPU on Windows (CUDA)" in assistant.summary_text()
    finally:
        assistant.reject()


def test_a_failed_setup_shows_the_reason_and_changes_nothing(app, monkeypatch, boxes):
    assistant = SetupAssistant()
    try:
        page = assistant.acceleration_page
        page._apply_report(_report())
        before = config.all_settings()

        def install(backend, gpu_name="", on_line=None, cancel=None):
            return gpu_runtime.RuntimeResult(
                ok=False, backend=backend, python="python.exe",
                error="The environment was installed, but it cannot be used: PyTorch found no "
                      "CUDA device.")

        monkeypatch.setattr(gpu_runtime, "install", install)
        page.start_gpu_setup()
        _wait(app, lambda: page._job is None)
        assert config.all_settings() == before
        assert boxes == [("warning", "The environment was installed, but it cannot be used: "
                                     "PyTorch found no CUDA device.")]
        assert "left as it was" in page.gpu_status.text()
        assert page.cpu_radio.isChecked()
        assert page.gpu_setup_btn.isEnabled()
    finally:
        assistant.reject()


def test_an_environment_that_did_not_pass_is_never_selected(app, monkeypatch, boxes):
    """Even if the engine wrongly reported success, use() checks the probe again."""
    assistant = SetupAssistant()
    try:
        page = assistant.acceleration_page
        page._apply_report(_report())

        def install(backend, gpu_name="", on_line=None, cancel=None):
            broken = gpu_runtime.RuntimeEnvironment(python="python.exe", error="no torch")
            return gpu_runtime.RuntimeResult(ok=True, backend=backend, python="python.exe",
                                             environment=broken)

        monkeypatch.setattr(gpu_runtime, "install", install)
        page.start_gpu_setup()
        _wait(app, lambda: page._job is None)
        assert config.gpu_runtime() is None
        assert boxes and boxes[0][0] == "warning"
    finally:
        assistant.reject()


def test_a_cancelled_gpu_setup_leaves_the_settings_untouched(app, monkeypatch, boxes):
    assistant = SetupAssistant()
    try:
        page = assistant.acceleration_page
        page._apply_report(_report())
        before = config.all_settings()

        def install(backend, gpu_name="", on_line=None, cancel=None):
            while not cancel.is_set():
                time.sleep(0.01)
            raise WorkerCancelled

        monkeypatch.setattr(gpu_runtime, "install", install)
        page.start_gpu_setup()
        _wait(app, lambda: page._job is not None)
        assert not page.gpu_setup_btn.isEnabled() and page.gpu_cancel_btn.isEnabled()
        page._cancel_gpu_setup()
        _wait(app, lambda: page._job is None)
        assert config.all_settings() == before
        assert "cancelled" in page.gpu_status.text().lower()
        assert boxes == []
    finally:
        assistant.reject()


def test_cuda_without_an_nvidia_card_asks_first_and_directml_is_the_default(app, monkeypatch,
                                                                             boxes):
    assistant = SetupAssistant()
    try:
        page = assistant.acceleration_page
        page._apply_report(_report("AMD Radeon RX 6900 XT", "amd"))
        assert page.gpu_backend.currentData() == "directml"
        assert "RoFormer" in page.gpu_note.text()        # says what DirectML does not speed up
        assert page.cpu_radio.isChecked()                 # nothing is selected by a suggestion
        monkeypatch.setattr(QMessageBox, "question",
                            lambda parent, title, text: boxes.append(("question", text))
                            or QMessageBox.No)
        monkeypatch.setattr(gpu_runtime, "install",
                            lambda *args, **kwargs: pytest.fail("the setup must not start"))
        page.gpu_backend.setCurrentIndex(page.gpu_backend.findData("cuda"))
        page.start_gpu_setup()
        assert page._job is None
        assert boxes and "No NVIDIA GPU was found" in boxes[0][1]
    finally:
        assistant.reject()


def test_roformer_on_the_gpu_is_ticked_for_a_16_gb_card_and_saved_with_the_setup(
        app, monkeypatch, boxes):
    assistant = SetupAssistant()
    try:
        page = assistant.acceleration_page
        report = setup.SystemReport(
            os_name="Windows 11", cpu_cores=8, ram_bytes=32 * setup.GiB,
            gpus=(setup.GpuAdapter("AMD Radeon RX 6900 XT", "amd", 17_163_091_968),),
            wsl=setup.WslState(installed=False))
        page._apply_report(report)
        assert page.gpu_backend.currentData() == "directml"
        assert not page.gpu_roformer.isHidden() and page.gpu_roformer.isChecked()
        assert config.setting("directml_roformer") is None        # a suggestion saves nothing

        def install(backend, gpu_name="", on_line=None, cancel=None):
            return gpu_runtime.RuntimeResult(
                ok=True, backend=backend, python="python.exe",
                environment=_environment("directml", "AMD Radeon RX 6900 XT"))

        monkeypatch.setattr(gpu_runtime, "install", install)
        page.start_gpu_setup()
        _wait(app, lambda: page._job is None)
        assert config.gpu_runtime() == ("directml", "python.exe")
        assert gpu_runtime.directml_roformer() is True
        # Unticking it later takes effect at once, without another setup.
        page.gpu_roformer.click()
        assert gpu_runtime.directml_roformer() is False
        assert "CPU" in page.gpu_status.text()
    finally:
        assistant.reject()


def test_the_roformer_option_is_hidden_for_cuda_and_unticked_for_a_small_card(app, boxes):
    assistant = SetupAssistant()
    try:
        page = assistant.acceleration_page
        page._apply_report(_report("AMD Radeon RX 6600", "amd"))      # 12 GB in this fixture
        assert not page.gpu_roformer.isChecked()
        page.gpu_backend.setCurrentIndex(page.gpu_backend.findData("cuda"))
        assert page.gpu_roformer.isHidden()
    finally:
        assistant.reject()


def test_choosing_the_cpu_deselects_the_runtime_and_wsl(app, boxes):
    assistant = SetupAssistant()
    try:
        page = assistant.acceleration_page
        assert gpu_runtime.use(_environment(), "cuda")
        page._refresh_selection()
        assert not page.cpu_radio.isChecked()
        page.cpu_radio.click()
        assert config.gpu_runtime() is None and config.setting("wsl_gpu") is False
        assert page.cpu_radio.isChecked()
        assert "CPU" in page.gpu_status.text()
        assert assistant.summary_text().count("CPU only") == 1
    finally:
        assistant.reject()


def test_remove_deletes_the_runtime_after_a_confirmation(app, tmp_path, boxes):
    assistant = SetupAssistant()
    try:
        page = assistant.acceleration_page
        python = tmp_path / "runtimes" / "cuda" / "Scripts" / "python.exe"
        python.parent.mkdir(parents=True)
        python.write_bytes(b"")
        assert gpu_runtime.use(_environment(python=str(python)), "cuda")
        page.gpu_backend.setCurrentIndex(page.gpu_backend.findData("cuda"))
        page._refresh_selection()
        assert page.gpu_remove_btn.isEnabled()
        page.remove_gpu_runtime()
        _wait(app, lambda: page._job is None)
        assert not python.exists() and config.gpu_runtime() is None
        assert boxes[0][0] == "question" and "Delete the downloaded" in boxes[0][1]
        assert "was removed" in page.gpu_status.text()
        assert not page.gpu_remove_btn.isEnabled()
        assert page.cpu_radio.isChecked()
    finally:
        assistant.reject()


def test_using_a_wsl_environment_deselects_the_windows_runtime():
    assert gpu_runtime.use(_environment(), "cuda")
    environment = setup.WslEnvironment(
        distro="Ubuntu", python="/opt/lyricloom/venv/bin/python", gpu_available=True,
        backend="rocm", imports={name: True for name in setup.WslEnvironment.REQUIRED_IMPORTS})
    assert setup.use_wsl_environment(environment)
    assert config.gpu_runtime() is None and config.setting("wsl_gpu") is True
