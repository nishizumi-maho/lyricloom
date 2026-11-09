"""The first-run setup assistant: library, system check, acceleration, models and privacy.

The assistant only draws the process.  Every long call (``setup.detect``,
``setup.find_wsl_environments``, ``setup.run_wsl_setup``,
``setup.install_whisper_backend`` and the model downloads) runs in a worker ``QObject`` moved to a
``QThread``.  The worker's signals are queued to the page, so no widget is touched from a worker
thread, and every job has a cancellation event that reaches the engine.

The engine owns every setting: ``use_wsl_environment`` writes the WSL settings only after a
passing probe, ``install_whisper_backend``/``use_bundled_whisper`` write ``whisper_cli``,
``models.download`` verifies each file, and ``assemblyai_enabled`` is a separate consent flag from
the API key.  The assistant adds only ``setup_complete`` (on Finish).
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QProgressBar, QPushButton, QRadioButton, QScrollArea, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWizard, QWizardPage, QWidget)

from .. import config, models, musicbee, runtime, setup, updater
from ..workers import WorkerCancelled
from .dialogs import validate_folder

PAGE_WELCOME = 0
PAGE_LIBRARY = 1
PAGE_SYSTEM = 2
PAGE_ACCELERATION = 3
PAGE_MODELS = 4
PAGE_PRIVACY = 5
PAGE_MUSICBEE = 6
PAGE_FINISH = 7

PAGE_KEYS = {
    "welcome": PAGE_WELCOME,
    "library": PAGE_LIBRARY,
    "system": PAGE_SYSTEM,
    "acceleration": PAGE_ACCELERATION,
    "models": PAGE_MODELS,
    "privacy": PAGE_PRIVACY,
    "musicbee": PAGE_MUSICBEE,
    "finish": PAGE_FINISH,
}

SETUP_COMPLETE = "setup_complete"
ASK_BEFORE_UPLOAD = "assemblyai_ask_before_upload"


def _human_size(n: int | None) -> str:
    return runtime.human_size(int(n)) if n else "unknown"


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _detect(_worker: "_Worker"):
    """``setup.detect`` in the worker thread.  The probes have their own timeouts."""
    return setup.detect()


# --------------------------------------------------------------------------- worker plumbing


class _Worker(QObject):
    """Runs one callable in a worker thread and reports its result with signals."""

    done = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    line = Signal(str)
    progress = Signal(int, int)
    finished = Signal()

    def __init__(self, function):
        super().__init__()
        self._function = function
        self.cancel = threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            value = self._function(self)
        except Exception as exc:  # noqa: BLE001 - the page shows the error, never the thread dies
            if self.cancel.is_set():
                self.cancelled.emit()
            else:
                self.failed.emit(_error_text(exc))
        else:
            self.done.emit(value)
        finally:
            self.finished.emit()


_KEEP_ALIVE: list[object] = []


class _Job(QObject):
    """One worker thread; relays the worker's signals to the page in the GUI thread."""

    done = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    line = Signal(str)
    progress = Signal(int, int)
    finished = Signal()

    def __init__(self, function, parent: QObject | None = None):
        # Deliberately not parented: a setup assistant creates only a handful of jobs, and keeping
        # the QThread/worker alive for the process avoids destroying Qt objects from the garbage
        # collector's thread or from a page deletion while a thread is still winding down.
        super().__init__()
        self._thread = QThread()
        self._worker = _Worker(function)
        _KEEP_ALIVE.append(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._relay_done, Qt.QueuedConnection)
        self._worker.failed.connect(self._relay_failed, Qt.QueuedConnection)
        self._worker.cancelled.connect(self._relay_cancelled, Qt.QueuedConnection)
        self._worker.line.connect(self._relay_line, Qt.QueuedConnection)
        self._worker.progress.connect(self._relay_progress, Qt.QueuedConnection)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._thread_finished)
        self._thread.finished.connect(self.finished)

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel.set()

    def stop(self, wait_ms: int = 5000) -> None:
        self.cancel()
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(wait_ms)

    def close(self) -> None:
        """Cancels, joins and disconnects the job so no later signal reaches a deleted page."""
        self.stop()
        for signal in (self.done, self.failed, self.cancelled, self.line, self.progress,
                       self.finished):
            try:
                signal.disconnect()
            except (RuntimeError, TypeError):
                pass

    def is_busy(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    @Slot()
    def _thread_finished(self) -> None:
        # ``QThread.finished`` is emitted just before the OS thread returns.  Join it here so the
        # QThread can never be destroyed while still winding down.
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait(2000)

    @Slot(object)
    def _relay_done(self, value) -> None:
        self.done.emit(value)

    @Slot(str)
    def _relay_failed(self, message: str) -> None:
        self.failed.emit(message)

    @Slot()
    def _relay_cancelled(self) -> None:
        self.cancelled.emit()

    @Slot(str)
    def _relay_line(self, text: str) -> None:
        self.line.emit(text)

    @Slot(int, int)
    def _relay_progress(self, done: int, total: int) -> None:
        self.progress.emit(done, total)


class _JobPage(QWizardPage):
    """A wizard page that can run one cancellable engine call at a time."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._job: _Job | None = None
        self._retired_jobs: list[_Job] = []

    def _start_job(self, function, *, on_done=None, on_failed=None, on_cancelled=None,
                   on_line=None, on_progress=None, on_finished=None) -> _Job | None:
        if self._job is not None:
            return None
        job = _Job(function, self)
        self._job = job
        if on_done is not None:
            job.done.connect(on_done, Qt.QueuedConnection)
        if on_failed is not None:
            job.failed.connect(on_failed, Qt.QueuedConnection)
        if on_cancelled is not None:
            job.cancelled.connect(on_cancelled, Qt.QueuedConnection)
        if on_line is not None:
            job.line.connect(on_line, Qt.QueuedConnection)
        if on_progress is not None:
            job.progress.connect(on_progress, Qt.QueuedConnection)
        job.finished.connect(self._job_finished, Qt.QueuedConnection)
        if on_finished is not None:
            job.finished.connect(on_finished, Qt.QueuedConnection)
        job.start()
        return job

    @Slot()
    def _job_finished(self) -> None:
        job, self._job = self._job, None
        if job is not None:
            self._retired_jobs.append(job)

    def cancel_job(self) -> None:
        if self._job is not None:
            self._job.cancel()

    def shutdown(self) -> None:
        if self._job is not None:
            self._job.close()
            self._retired_jobs.append(self._job)
            self._job = None
        for job in self._retired_jobs:
            if job.is_busy():
                job.close()


# --------------------------------------------------------------------------- pages


class WelcomePage(QWizardPage):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setTitle("Welcome to LyricLoom")
        self.setSubTitle("A short setup now saves a long detour later.")
        layout = QVBoxLayout(self)
        intro = QLabel(
            "LyricLoom finds the lyrics you already have, separates the vocals and writes a .lrc "
            "with word-by-word timing next to each song. The built-in player and the karaoke "
            "window show the result; MusicBee is optional.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        size = QLabel(
            "The suggested models need about 5 GB of disk space and are downloaded once. You can "
            "start with the defaults and change every model later in Help > Models.")
        size.setWordWrap(True)
        layout.addWidget(size)
        privacy = QLabel(
            "<b>Your music stays on this computer.</b> Nothing is uploaded unless you turn on "
            "cloud transcription on the Privacy page and add an AssemblyAI key. The optional "
            "startup update check is off until you choose it.")
        privacy.setWordWrap(True)
        layout.addWidget(privacy)
        layout.addStretch(1)


class LibraryPage(QWizardPage):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setTitle("Your music folder")
        self.setSubTitle("LyricLoom scans this folder and writes the .lrc files beside the audio.")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.library = QLineEdit(str(config.library_root()))
        self.library.setPlaceholderText("Folder that contains your music")
        self.browse = QPushButton("Browse…")
        self.browse.clicked.connect(self._browse)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(self.library, 1)
        line.addWidget(self.browse)
        form.addRow("Music library", row)
        layout.addLayout(form)
        note = QLabel(
            "The folder must already exist. LyricLoom writes one .lrc next to each audio file and "
            "keeps its caches in its own data folder, never in your music folder.")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose the music library",
                                                  self.library.text() or str(Path.home()))
        if folder:
            self.library.setText(folder)

    def apply(self) -> bool:
        path, error = validate_folder("Music library", self.library.text(), must_exist=True)
        if error:
            QMessageBox.warning(self, "Music library", error)
            self.library.setFocus()
            self.library.selectAll()
            return False
        try:
            config.set_library_root(path)
        except OSError as exc:
            QMessageBox.critical(self, "Music library",
                                 f"Could not save the library folder:\n{exc.strerror or exc}")
            return False
        self.library.setText(str(path))
        return True

    def validatePage(self) -> bool:
        return self.apply()


class SystemCheckPage(_JobPage):
    ROWS = ("CPU", "Memory", "Free disk (models folder)", "GPUs", "WSL", "whisper-cli")

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setTitle("System check")
        self.setSubTitle("Detection runs with timeouts and never downloads anything.")
        layout = QVBoxLayout(self)
        self.table = QTableWidget(len(self.ROWS), 2)
        self.table.setHorizontalHeaderLabels(["Component", "Result"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.check_btn = QPushButton("Check again")
        self.check_btn.clicked.connect(self.start_check)
        row.addWidget(self.status, 1)
        row.addWidget(self.check_btn)
        layout.addLayout(row)

    def initializePage(self) -> None:
        if getattr(self.wizard(), "report", None) is None:
            self.start_check()

    def start_check(self) -> None:
        if self._job is not None:
            return
        self.check_btn.setEnabled(False)
        self.status.setText("Checking the machine…")
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.ROWS))
        for row, name in enumerate(self.ROWS):
            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, QTableWidgetItem("checking…"))
        self._start_job(_detect, on_done=self._checked, on_failed=self._check_failed,
                        on_finished=lambda: self.check_btn.setEnabled(True))

    @Slot(object)
    def _checked(self, report) -> None:
        self.wizard().report = report
        self.status.setText("Check finished.")
        values = {
            "CPU": (f"{report.cpu_cores} cores" if report.cpu_cores else
                    f"unknown ({report.cpu_error or 'no value'})"),
            "Memory": _human_size(report.ram_bytes) if report.ram_bytes else
                      f"unknown ({report.ram_error or 'no value'})",
            "Free disk (models folder)": (
                f"{_human_size(report.disk_free_bytes)} free of "
                f"{_human_size(report.disk_total_bytes)} · {report.models_dir}"
                if report.disk_free_bytes is not None else
                f"unknown ({report.disk_error or 'no value'})"),
            "GPUs": ", ".join(
                f"{gpu.name} ({gpu.vendor}, {_human_size(gpu.memory_bytes)})"
                for gpu in report.gpus) or (report.gpu_error or "none detected"),
            "WSL": self._wsl_text(report),
            "whisper-cli": (report.whisper_cli.path
                            if report.whisper_cli.present else
                            (report.whisper_cli.error or "not found")),
        }
        for row, name in enumerate(self.ROWS):
            item = QTableWidgetItem(values.get(name, ""))
            item.setToolTip(values.get(name, ""))
            self.table.setItem(row, 1, item)
        self.table.resizeColumnToContents(0)

    @staticmethod
    def _wsl_text(report) -> str:
        wsl = report.wsl
        if not wsl.installed:
            return wsl.error or "not installed"
        distros = ", ".join(f"{distro.name} (v{distro.version})" for distro in wsl.distros)
        if wsl.version2:
            return f"WSL 2 · {distros or 'no distros listed'}"
        return f"WSL installed without a version 2 distro · {distros or 'none'}"

    @Slot(str)
    def _check_failed(self, message: str) -> None:
        self.status.setText("The check failed: " + message)
        self.table.setRowCount(1)
        self.table.setItem(0, 0, QTableWidgetItem("Check"))
        self.table.setItem(0, 1, QTableWidgetItem(message))


class AccelerationPage(_JobPage):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setTitle("Acceleration")
        self.setSubTitle("Choose where separation, alignment and transcription run.")
        self._report = None
        self._environments: list = []
        self._wsl_wheel: Path | None = None
        self._wsl_script: Path | None = None
        self._busy_buttons: list[QWidget] = []

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self.recommendation = QLabel("")
        self.recommendation.setWordWrap(True)
        layout.addWidget(self.recommendation)

        cpu = QGroupBox("CPU only")
        cpu_layout = QVBoxLayout(cpu)
        self.cpu_radio = QRadioButton("CPU only — works on every machine and needs no extra setup.")
        self.cpu_radio.setChecked(True)
        cpu_layout.addWidget(self.cpu_radio)
        layout.addWidget(cpu)

        existing = QGroupBox("Use an existing WSL GPU environment")
        existing_layout = QVBoxLayout(existing)
        self.existing_note = QLabel(
            "LyricLoom checks the interpreters inside each WSL 2 distro for torch, audio-separator, "
            "the MTL packages and a working GPU. Only a passing environment can be selected.")
        self.existing_note.setWordWrap(True)
        existing_layout.addWidget(self.existing_note)
        row = QHBoxLayout()
        self.scan_btn = QPushButton("Find WSL environments")
        self.scan_btn.clicked.connect(self.scan_environments)
        self.existing_combo = QComboBox()
        self.existing_combo.currentIndexChanged.connect(self._environment_changed)
        self.use_btn = QPushButton("Use this")
        self.use_btn.setEnabled(False)
        self.use_btn.clicked.connect(self.use_environment)
        row.addWidget(self.scan_btn)
        row.addWidget(self.existing_combo, 1)
        row.addWidget(self.use_btn)
        existing_layout.addLayout(row)
        self.existing_status = QLabel("")
        self.existing_status.setWordWrap(True)
        existing_layout.addWidget(self.existing_status)
        layout.addWidget(existing)

        new_wsl = QGroupBox("Set up a new WSL GPU environment")
        new_layout = QVBoxLayout(new_wsl)
        form = QFormLayout()
        self.wsl_backend = QComboBox()
        self.wsl_backend.addItem("ROCm (AMD GPU)", "rocm")
        self.wsl_backend.addItem("CUDA (NVIDIA GPU)", "cuda")
        self.wsl_backend.addItem("CPU only inside WSL", "cpu")
        form.addRow("Backend", self.wsl_backend)
        new_layout.addLayout(form)
        self.wsl_note = QLabel(
            "LyricLoom runs the bundled WSL setup script, writes a log here and keeps every "
            "setting unchanged if the setup fails or is cancelled.")
        self.wsl_note.setWordWrap(True)
        new_layout.addWidget(self.wsl_note)
        row = QHBoxLayout()
        self.wsl_setup_btn = QPushButton("Set up WSL…")
        self.wsl_setup_btn.clicked.connect(self.start_wsl_setup)
        self.wsl_cancel_btn = QPushButton("Cancel")
        self.wsl_cancel_btn.setEnabled(False)
        self.wsl_cancel_btn.clicked.connect(self._cancel_wsl_setup)
        row.addWidget(self.wsl_setup_btn)
        row.addWidget(self.wsl_cancel_btn)
        row.addStretch(1)
        new_layout.addLayout(row)
        self.wsl_progress = QProgressBar()
        self.wsl_progress.setRange(0, 1000)
        self.wsl_progress.setValue(0)
        new_layout.addWidget(self.wsl_progress)
        self.wsl_log = QTableWidget(0, 1)
        self.wsl_log.setHorizontalHeaderLabels(["Setup log"])
        self.wsl_log.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.wsl_log.verticalHeader().setVisible(False)
        self.wsl_log.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.wsl_log.setMinimumHeight(110)
        new_layout.addWidget(self.wsl_log)
        self._wsl_log_lines: list[str] = []
        layout.addWidget(new_wsl)

        install_wsl = QGroupBox("Install WSL 2")
        install_layout = QVBoxLayout(install_wsl)
        self.install_wsl_note = QLabel(
            "WSL is missing. Windows asks for administrator rights to install it and may ask you "
            "to restart the computer. LyricLoom starts that only when you click the button.")
        self.install_wsl_note.setWordWrap(True)
        install_layout.addWidget(self.install_wsl_note)
        self.install_wsl_btn = QPushButton("Install WSL now…")
        self.install_wsl_btn.clicked.connect(self.install_wsl)
        install_layout.addWidget(self.install_wsl_btn, 0, Qt.AlignLeft)
        self.install_wsl_group = install_wsl
        layout.addWidget(install_wsl)

        transcription = QGroupBox("Faster transcription")
        transcription_layout = QVBoxLayout(transcription)
        form = QFormLayout()
        self.transcription = QComboBox()
        self.transcription.addItem("Use the bundled whisper.cpp", "")
        self.transcription.addItem("whisper.cpp BLAS (faster CPU)", "blas")
        self.transcription.addItem("whisper.cpp cuBLAS (NVIDIA GPU only)", "cublas")
        form.addRow("Transcription backend", self.transcription)
        transcription_layout.addLayout(form)
        note = QLabel(
            "The official whisper.cpp Windows builds are pinned by size and SHA-256. The selected "
            "binary is tested with --help before it is saved.")
        note.setWordWrap(True)
        transcription_layout.addWidget(note)
        row = QHBoxLayout()
        self.transcription_btn = QPushButton("Install / select")
        self.transcription_btn.clicked.connect(self.install_transcription)
        self.transcription_cancel_btn = QPushButton("Cancel")
        self.transcription_cancel_btn.setEnabled(False)
        self.transcription_cancel_btn.clicked.connect(self._cancel_transcription)
        row.addWidget(self.transcription_btn)
        row.addWidget(self.transcription_cancel_btn)
        row.addStretch(1)
        transcription_layout.addLayout(row)
        self.transcription_progress = QProgressBar()
        self.transcription_progress.setRange(0, 1000)
        self.transcription_progress.setValue(0)
        transcription_layout.addWidget(self.transcription_progress)
        layout.addWidget(transcription)
        layout.addStretch(1)

        self._busy_buttons = [self.scan_btn, self.use_btn, self.wsl_setup_btn,
                              self.install_wsl_btn, self.transcription_btn]
        self._load_bundled_wsl()

    def _load_bundled_wsl(self) -> None:
        try:
            script, wheel = setup.bundled_wsl_files()
            self._wsl_script = Path(script)
            self._wsl_wheel = Path(wheel) if wheel is not None else None
        except Exception as exc:  # noqa: BLE001 - a missing script is a normal source checkout
            self._wsl_script = None
            self._wsl_wheel = None
            self.wsl_note.setText(f"The bundled WSL setup script is unavailable ({exc}).")
        if self._wsl_wheel is None:
            self.wsl_setup_btn.setEnabled(False)
            self.wsl_note.setText(
                "This build cannot set up WSL for you because it does not include a LyricLoom "
                "wheel. Follow the manual guide instead: "
                '<a href="wsl-rocm.md">docs/wsl-rocm.md</a>.')
            self.wsl_note.setOpenExternalLinks(False)
            self.wsl_note.linkActivated.connect(self._open_wsl_docs)

    def _open_wsl_docs(self, _link: str = "") -> None:
        local = Path(config.PROJECT_ROOT) / "docs" / "wsl-rocm.md"
        if local.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(local)))
            return
        QDesktopServices.openUrl(
            QUrl(f"https://github.com/{updater.REPO}/blob/main/docs/wsl-rocm.md"))

    def initializePage(self) -> None:
        report = getattr(self.wizard(), "report", None)
        if report is not None:
            self._apply_report(report)
        elif self._job is None:
            self._start_job(_detect, on_done=self._apply_report,
                            on_failed=lambda message: self.recommendation.setText(
                                "The system check failed: " + message))

    def _apply_report(self, report) -> None:
        self._report = report
        self.wizard().report = report
        recommendation = setup.recommend(report)
        self.recommendation.setText(
            "<b>Suggested setup</b><br>"
            f"Separation and alignment: {recommendation.wsl_gpu_reason}<br>"
            f"Transcription: {recommendation.whisper_backend_reason}<br>"
            f"Model: {recommendation.whisper_model_reason}")
        if recommendation.wsl_gpu:
            self.cpu_radio.setChecked(False)
        index = self.transcription.findData(recommendation.whisper_backend)
        if index >= 0:
            self.transcription.setCurrentIndex(index)
        if recommendation.gpu_vendor != "nvidia":
            model = self.transcription.model()
            if model is not None and self.transcription.count() > 2:
                model.item(2).setEnabled(False)
        self.install_wsl_group.setVisible(not report.wsl.installed)
        if report.wsl.installed and report.wsl.version2:
            self.existing_note.setText(
                "LyricLoom checks the interpreters inside each WSL 2 distro for torch, "
                "audio-separator, the MTL packages and a working GPU. Only a passing environment "
                "can be selected.")
        elif report.wsl.installed:
            self.existing_note.setText(
                "WSL is installed but no WSL 2 distro is registered. Use “Set up a new WSL GPU "
                "environment” after installing WSL 2.")
        else:
            self.existing_note.setText("WSL is not installed, so there is no WSL environment to use.")

    # ---------- existing environments
    def _wsl2_distros(self) -> list[str]:
        report = self._report or getattr(self.wizard(), "report", None)
        if report is None:
            return []
        return [distro.name for distro in report.wsl.distros if distro.version >= 2]

    def scan_environments(self) -> None:
        if self._job is not None:
            return
        distros = self._wsl2_distros()
        if not distros:
            self.existing_status.setText("No WSL 2 distro was found. Install WSL 2 first.")
            return
        self.existing_status.setText("Checking " + ", ".join(distros) + "…")
        self.existing_combo.clear()
        self.use_btn.setEnabled(False)
        self._set_busy(True)

        def scan(worker):
            found = []
            for distro in distros:
                if worker.cancel.is_set():
                    raise WorkerCancelled
                worker.line.emit(f"Checking {distro}…")
                found.extend(setup.find_wsl_environments(distro, cancel=worker.cancel))
            return found

        self._start_job(scan, on_done=self._environments_found,
                        on_failed=self._environments_failed,
                        on_cancelled=lambda: self.existing_status.setText("Check cancelled."),
                        on_finished=lambda: self._set_busy(False))

    @Slot(object)
    def _environments_found(self, environments) -> None:
        self._environments = list(environments)
        self.existing_combo.clear()
        for environment in self._environments:
            device = environment.device_name or "no GPU"
            if environment.error:
                detail = environment.error
            elif environment.missing_imports:
                detail = "missing " + ", ".join(environment.missing_imports)
            elif not environment.gpu_available:
                detail = "no GPU available"
            else:
                detail = "ready"
            text = f"{environment.distro} · {environment.python} · {device} · {detail}"
            self.existing_combo.addItem(text, environment)
        self._environment_changed()
        if not self._environments:
            self.existing_status.setText("No interpreter was found inside the WSL distro.")
        else:
            passing = sum(1 for environment in self._environments if environment.passed)
            self.existing_status.setText(
                f"{len(self._environments)} environment(s) checked; {passing} passed.")

    @Slot(str)
    def _environments_failed(self, message: str) -> None:
        self.existing_status.setText("The WSL check failed: " + message)

    def _environment_changed(self, *_args) -> None:
        environment = self.existing_combo.currentData()
        self.use_btn.setEnabled(bool(environment is not None and environment.passed))
        if environment is not None and environment.error:
            self.use_btn.setToolTip(environment.error)
        elif environment is not None and environment.missing_imports:
            self.use_btn.setToolTip("Missing: " + ", ".join(environment.missing_imports))
        else:
            self.use_btn.setToolTip("")

    def use_environment(self) -> None:
        environment = self.existing_combo.currentData()
        if environment is None:
            return
        if setup.use_wsl_environment(environment):
            self.existing_status.setText(
                "Saved. Restart LyricLoom to run separation and alignment on the GPU.")
        else:
            self.existing_status.setText(
                "This environment did not pass, so the settings were not changed.")

    # ---------- new WSL environment
    def _wsl_distro(self) -> str:
        report = self._report or getattr(self.wizard(), "report", None)
        if report is not None:
            for distro in report.wsl.distros:
                if distro.version >= 2:
                    return distro.name
        return setup.WSL_DISTRO

    def start_wsl_setup(self) -> None:
        if self._job is not None:
            return
        if self._wsl_wheel is None:
            QMessageBox.information(
                self, "Set up WSL",
                "This build cannot set up a new WSL environment automatically. Follow "
                "docs/wsl-rocm.md instead.")
            return
        distro = self._wsl_distro()
        backend = self.wsl_backend.currentData()
        self._wsl_log_lines.clear()
        self.wsl_log.setRowCount(0)
        self.wsl_progress.setRange(0, 1000)
        self.wsl_progress.setValue(0)
        self.wsl_progress.setFormat("Starting…")
        self.wsl_cancel_btn.setEnabled(True)
        self._set_busy(True)
        self._scan_after_setup = False
        wheel = self._wsl_wheel

        def run(worker):
            return setup.run_wsl_setup(distro, backend, wheel, on_line=worker.line.emit,
                                       cancel=worker.cancel)

        self._start_job(run, on_done=self._wsl_setup_done, on_failed=self._wsl_setup_failed,
                        on_cancelled=self._wsl_setup_cancelled, on_line=self._wsl_line,
                        on_finished=self._wsl_setup_finished)

    @Slot(str)
    def _wsl_line(self, text: str) -> None:
        self._wsl_log_lines.append(text)
        row = self.wsl_log.rowCount()
        self.wsl_log.insertRow(row)
        item = QTableWidgetItem(text)
        item.setToolTip(text)
        self.wsl_log.setItem(row, 0, item)
        self.wsl_log.scrollToBottom()
        match = re.search(r"@@step\s+(\d+)\s*/\s*(\d+)", text)
        if match:
            done, total = int(match.group(1)), max(1, int(match.group(2)))
            self.wsl_progress.setRange(0, total)
            self.wsl_progress.setValue(min(done, total))
            self.wsl_progress.setFormat(f"Step {done} of {total}")

    @Slot(object)
    def _wsl_setup_done(self, result) -> None:
        if result.ok:
            self.wsl_progress.setRange(0, 1000)
            self.wsl_progress.setValue(1000)
            self.wsl_progress.setFormat("Finished")
            if result.environment is not None and result.environment.passed:
                setup.use_wsl_environment(result.environment)
                self.existing_status.setText(
                    "WSL setup finished and the environment is saved. Restart LyricLoom to use it.")
            else:
                self.existing_status.setText(
                    "WSL setup finished, but the environment is not usable as a GPU backend.")
        else:
            self.existing_status.setText("WSL setup failed: " + (result.error or "unknown error"))
            QMessageBox.warning(self, "WSL setup", result.error or "The WSL setup did not finish.")
        self._scan_after_setup = result.ok

    @Slot(str)
    def _wsl_setup_failed(self, message: str) -> None:
        self.existing_status.setText("WSL setup failed: " + message)
        QMessageBox.critical(self, "WSL setup", message)

    @Slot()
    def _wsl_setup_cancelled(self) -> None:
        self.existing_status.setText(
            "WSL setup was cancelled. No settings were changed and partial downloads are kept.")
        self.wsl_progress.setFormat("Cancelled")

    @Slot()
    def _wsl_setup_finished(self) -> None:
        self.wsl_cancel_btn.setEnabled(False)
        self._set_busy(False)
        if getattr(self, "_scan_after_setup", False):
            self._scan_after_setup = False
            self.scan_environments()

    def _cancel_wsl_setup(self) -> None:
        self.cancel_job()
        self.wsl_cancel_btn.setEnabled(False)
        self.existing_status.setText("Cancelling the WSL setup…")

    # ---------- install WSL and whisper backends
    def install_wsl(self) -> None:
        command = setup.wsl_install_command()
        answer = QMessageBox.question(
            self, "Install WSL 2",
            "Windows will ask for administrator rights to install WSL 2 and may ask you to restart "
            "the computer.\n\nStart the installation now?")
        if answer != QMessageBox.Yes:
            return
        if not config.IS_WINDOWS:
            QMessageBox.information(self, "Install WSL 2", "WSL is only available on Windows.")
            return
        try:
            _shell_execute(command)
        except Exception as exc:  # noqa: BLE001 - Windows may refuse elevation
            QMessageBox.critical(self, "Install WSL 2",
                                 f"Could not start the WSL installation:\n{exc}")

    def install_transcription(self) -> None:
        if self._job is not None:
            return
        name = self.transcription.currentData()
        if not name:
            try:
                setup.use_bundled_whisper()
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Transcription", _error_text(exc))
                return
            self.existing_status.setText("The bundled whisper.cpp is selected.")
            return
        self.transcription_progress.setRange(0, 1000)
        self.transcription_progress.setValue(0)
        self.transcription_progress.setFormat("Downloading…")
        self.transcription_cancel_btn.setEnabled(True)
        self._set_busy(True)

        def install(worker):
            return setup.install_whisper_backend(name, progress=worker.progress.emit,
                                                 cancel=worker.cancel)

        self._start_job(install, on_done=self._transcription_done,
                        on_failed=self._transcription_failed,
                        on_cancelled=self._transcription_cancelled,
                        on_progress=self._transcription_progress,
                        on_finished=self._transcription_finished)

    @Slot(int, int)
    def _transcription_progress(self, done: int, total: int) -> None:
        if total:
            self.transcription_progress.setRange(0, 1000)
            self.transcription_progress.setValue(min(1000, int(done * 1000 / total)))
            self.transcription_progress.setFormat(
                f"{runtime.human_size(done)} of {runtime.human_size(total)}")
        else:
            self.transcription_progress.setRange(0, 0)

    @Slot(object)
    def _transcription_done(self, installed) -> None:
        self.transcription_progress.setRange(0, 1000)
        self.transcription_progress.setValue(1000)
        self.transcription_progress.setFormat("Installed")
        self.existing_status.setText(f"whisper.cpp is installed at {installed}.")

    @Slot(str)
    def _transcription_failed(self, message: str) -> None:
        self.transcription_progress.setFormat("Failed")
        QMessageBox.critical(self, "Transcription", message)

    @Slot()
    def _transcription_cancelled(self) -> None:
        self.transcription_progress.setFormat("Cancelled; the previous binary is still selected.")

    @Slot()
    def _transcription_finished(self) -> None:
        self.transcription_cancel_btn.setEnabled(False)
        self._set_busy(False)

    def _cancel_transcription(self) -> None:
        self.cancel_job()
        self.transcription_cancel_btn.setEnabled(False)

    def _set_busy(self, busy: bool) -> None:
        for button in self._busy_buttons:
            button.setEnabled(not busy)
        if not busy:
            self._environment_changed()
            if self._wsl_wheel is None:
                self.wsl_setup_btn.setEnabled(False)

    def validatePage(self) -> bool:
        if self._job is not None:
            QMessageBox.information(
                self, "Acceleration",
                "A setup or download is still running. Wait for it to finish or click Cancel.")
            return False
        return True

    def shutdown(self) -> None:
        super().shutdown()
        self.wsl_cancel_btn.setEnabled(False)
        self.transcription_cancel_btn.setEnabled(False)


class ModelsPage(_JobPage):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setTitle("Models")
        self.setSubTitle("The suggested models are downloaded once and verified.")
        layout = QVBoxLayout(self)
        note = QLabel(
            "These are the suggested models for every stage. Every file is checked against a "
            "pinned size and SHA-256; a dropped download keeps its partial file and resumes when "
            "you try again. You can change models later in Help > Models.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Model", "Size", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)
        self.total = QLabel("")
        layout.addWidget(self.total)
        row = QHBoxLayout()
        self.download_btn = QPushButton("Download now")
        self.download_btn.clicked.connect(self.start_download)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_job)
        self.later_btn = QPushButton("Later")
        self.later_btn.clicked.connect(self._later)
        self.models_btn = QPushButton("Open Models window…")
        self.models_btn.clicked.connect(self.open_models_window)
        try:
            has_models_window = importlib.util.find_spec("lyricloom.app.models_window") is not None
        except (ImportError, ValueError):
            has_models_window = False
        if not has_models_window:
            self.models_btn.hide()
        row.addWidget(self.download_btn)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.later_btn)
        row.addStretch(1)
        row.addWidget(self.models_btn)
        layout.addLayout(row)
        self.progress_text = QLabel("")
        layout.addWidget(self.progress_text)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self._models_window = None
        self.refresh()

    def refresh(self) -> None:
        specs = models.default_models()
        self.table.setRowCount(len(specs))
        ready = 0
        for row, spec in enumerate(specs):
            try:
                state = models.status(spec)
            except Exception as exc:  # noqa: BLE001 - one broken file still gets a row
                state = f"error ({type(exc).__name__})"
            if state == "ready":
                ready += 1
            name = QTableWidgetItem(spec.label)
            name.setToolTip(f"{spec.id}\n{spec.description}")
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(runtime.human_size(spec.total_size)))
            self.table.setItem(row, 2, QTableWidgetItem(state.title()))
        self.table.resizeColumnToContents(1)
        self.table.resizeColumnToContents(2)
        total = sum(spec.total_size for spec in specs)
        self.total.setText(f"{ready} of {len(specs)} suggested models are ready · "
                           f"about {runtime.human_size(total)} in total")
        self.download_btn.setEnabled(self._job is None and ready < len(specs))

    def _later(self) -> None:
        self.wizard().next()

    def open_models_window(self) -> None:
        try:
            from .models_window import ModelsWindow
        except Exception as exc:  # noqa: BLE001 - the window is optional in some builds
            QMessageBox.information(self, "Models",
                                    "This build has no Models window: " + _error_text(exc))
            return
        if self._models_window is None:
            self._models_window = ModelsWindow(self)
            self._models_window.downloads_finished.connect(lambda _ok: self.refresh())
        self._models_window.show()
        self._models_window.raise_()
        self._models_window.activateWindow()

    def start_download(self) -> None:
        if self._job is not None:
            return
        specs = [spec for spec in models.default_models()
                 if models.status(spec) not in ("ready", "unverified")]
        if not specs:
            self.progress_text.setText("All suggested models are ready.")
            self.refresh()
            return
        error = _free_space_error(specs)
        if error:
            QMessageBox.warning(self, "Models", error)
            return
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.download_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        total_bytes = sum(spec.total_size for spec in specs) or 1

        def download(worker):
            done = 0
            for spec in specs:
                if worker.cancel.is_set():
                    raise WorkerCancelled
                worker.line.emit(f"Downloading {spec.label}…")
                base = done

                def report(current: int, total: int, base: int = base) -> None:
                    worker.progress.emit(min(base + current, total_bytes), total_bytes)

                models.download(spec, progress=report, cancel=worker.cancel)
                done += spec.total_size
                worker.progress.emit(min(done, total_bytes), total_bytes)
            return specs

        self._start_job(download, on_done=self._downloaded, on_failed=self._download_failed,
                        on_cancelled=self._download_cancelled, on_line=self.progress_text.setText,
                        on_progress=self._download_progress, on_finished=self._download_finished)

    @Slot(int, int)
    def _download_progress(self, done: int, total: int) -> None:
        if total:
            self.progress.setRange(0, 1000)
            self.progress.setValue(min(1000, int(done * 1000 / total)))
            self.progress.setFormat(f"{runtime.human_size(done)} of {runtime.human_size(total)}")

    @Slot(object)
    def _downloaded(self, specs) -> None:
        self.progress.setRange(0, 1000)
        self.progress.setValue(1000)
        self.progress.setFormat("Finished")
        self.progress_text.setText(f"Downloaded {len(specs)} model(s).")
        self.refresh()

    @Slot(str)
    def _download_failed(self, message: str) -> None:
        self._download_finished()
        self.progress_text.setText("The download failed.")
        QMessageBox.critical(self, "Models", message)
        self.refresh()

    @Slot()
    def _download_cancelled(self) -> None:
        self.progress_text.setText(
            "Download cancelled. Partial files are kept; Download now resumes them.")
        self.refresh()

    @Slot()
    def _download_finished(self) -> None:
        self.cancel_btn.setEnabled(False)
        self.download_btn.setEnabled(self._job is None)
        self.refresh()

    def validatePage(self) -> bool:
        if self._job is not None:
            QMessageBox.information(self, "Models",
                                    "A download is still running. Wait for it or click Cancel.")
            return False
        return True

    def shutdown(self) -> None:
        super().shutdown()
        self.cancel_btn.setEnabled(False)


class PrivacyPage(QWizardPage):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setTitle("Privacy")
        self.setSubTitle("Every network request is your choice.")
        layout = QVBoxLayout(self)
        updates = QGroupBox("Updates")
        updates_layout = QVBoxLayout(updates)
        self.check_updates = QCheckBox(
            "Check for updates when LyricLoom starts (contacts GitHub)")
        choice = updater.check_choice()
        self.check_updates.setChecked(choice is True)
        updates_layout.addWidget(self.check_updates)
        update_note = QLabel(
            "When this is on, LyricLoom sends one request to api.github.com when it starts and "
            "asks for public release metadata. The request carries your IP address and a "
            "User-Agent: LyricLoom/<version> header. Nothing about your library is sent. Off is "
            "the default; Help > Check for updates always works without this setting.")
        update_note.setWordWrap(True)
        updates_layout.addWidget(update_note)
        layout.addWidget(updates)

        cloud = QGroupBox("Cloud transcription")
        cloud_layout = QVBoxLayout(cloud)
        self.cloud = QCheckBox(
            "Allow uploading the isolated vocal to AssemblyAI for cloud transcription")
        self.cloud.setChecked(config.assemblyai_enabled())
        cloud_layout.addWidget(self.cloud)
        cloud_note = QLabel(
            "Off by default. When it is on and a song needs help, LyricLoom uploads only the "
            "16 kHz isolated vocal (not the full mix), the language code and a context prompt "
            "with the artist and title to AssemblyAI's servers. The provider's terms and privacy "
            "policy apply. Local transcription, separation and alignment always run on this "
            "computer.")
        cloud_note.setWordWrap(True)
        cloud_layout.addWidget(cloud_note)
        form = QFormLayout()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText(
            "A key is set; type a new one to replace it" if config.has_assemblyai_key()
            else "Paste your AssemblyAI API key (optional)")
        self.remove_key_btn = QPushButton("Remove stored key")
        self.remove_key_btn.setEnabled(config.has_assemblyai_key())
        self.remove_key_btn.clicked.connect(self._remove_key)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(self.key, 1)
        line.addWidget(self.remove_key_btn)
        form.addRow("AssemblyAI key", row)
        cloud_layout.addLayout(form)
        self.ask = QCheckBox("Ask before uploading each queue")
        self.ask.setChecked(config.ask_before_upload())
        cloud_layout.addWidget(self.ask)
        layout.addWidget(cloud)
        layout.addStretch(1)

    def _remove_key(self) -> None:
        try:
            config.set_assemblyai_key("")
        except (OSError, RuntimeError) as exc:
            QMessageBox.critical(self, "AssemblyAI", f"Could not remove the key:\n{exc}")
            return
        self.key.clear()
        self.key.setPlaceholderText("Paste your AssemblyAI API key (optional)")
        self.remove_key_btn.setEnabled(False)
        self.cloud.setChecked(False)

    def apply(self) -> bool:
        try:
            key = self.key.text().strip()
            if key:
                config.set_assemblyai_key(key)
                self.key.clear()
                self.key.setPlaceholderText("A key is set; type a new one to replace it")
                self.remove_key_btn.setEnabled(True)
            config.update_settings({
                "check_updates": self.check_updates.isChecked(),
                "assemblyai_enabled": self.cloud.isChecked(),
                ASK_BEFORE_UPLOAD: self.ask.isChecked(),
            })
        except OSError as exc:
            QMessageBox.critical(self, "Privacy",
                                 f"Could not save the privacy settings:\n{exc.strerror or exc}")
            return False
        except (RuntimeError, ValueError) as exc:
            QMessageBox.critical(self, "AssemblyAI", str(exc))
            return False
        return True

    def validatePage(self) -> bool:
        return self.apply()


class MusicBeePage(QWizardPage):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setTitle("MusicBee")
        self.setSubTitle("Install the Starry Karaoke plugin if you use MusicBee.")
        layout = QVBoxLayout(self)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.evidence = QLabel("")
        self.evidence.setWordWrap(True)
        layout.addWidget(self.evidence)
        row = QHBoxLayout()
        self.install_btn = QPushButton("Install / update Starry Karaoke")
        self.install_btn.clicked.connect(self.install)
        self.check_btn = QPushButton("Check again")
        self.check_btn.clicked.connect(self.refresh)
        row.addWidget(self.install_btn)
        row.addWidget(self.check_btn)
        row.addStretch(1)
        layout.addLayout(row)
        self.note = QLabel(
            "MusicBee and Starry Karaoke are separate programs. LyricLoom works without them; the "
            "plugin only displays the .lrc files LyricLoom writes. Close MusicBee before "
            "installing or updating the plugin.")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        layout.addStretch(1)

    def initializePage(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        status = musicbee.detect_musicbee()
        self.status_label.setText(status.summary)
        self.evidence.setText("Detected by: " + "; ".join(status.evidence) if status.evidence else "")
        self.install_btn.setVisible(status.detected)
        self.install_btn.setEnabled(status.detected)
        source = musicbee.bundled_plugin_dir()
        if source is None:
            self.install_btn.setEnabled(False)
            self.note.setText(
                "This build does not include the Starry Karaoke plugin files. Install the plugin "
                "from its releases page, or use the MusicBee page in a packaged build.")
        elif status.plugin_installed:
            self.install_btn.setText("Update Starry Karaoke")
        else:
            self.install_btn.setText("Install Starry Karaoke")

    def install(self) -> None:
        try:
            result = musicbee.install_plugin()
        except musicbee.MusicBeeRunning:
            QMessageBox.warning(self, "Starry Karaoke", musicbee.MUSICBEE_RUNNING_MESSAGE)
            return
        except musicbee.MusicBeeError as exc:
            QMessageBox.critical(self, "Starry Karaoke", str(exc))
            return
        self.refresh()
        if result.changed:
            self.status_label.setText(
                f"Starry Karaoke updated ({len(result.copied)} file(s) copied). Start MusicBee "
                "and choose View > Starry Karaoke.")
        else:
            self.status_label.setText("Starry Karaoke is already up to date.")


class FinishPage(QWizardPage):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setTitle("Ready")
        self.setSubTitle("LyricLoom is set up. You can change everything later in Settings.")
        layout = QVBoxLayout(self)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        layout.addWidget(self.summary)
        layout.addStretch(1)

    def initializePage(self) -> None:
        self.summary.setText(self.wizard().summary_text())


# --------------------------------------------------------------------------- wizard


class SetupAssistant(QWizard):
    """The first-run assistant.  Also opened from Help and from Settings > Acceleration."""

    def __init__(self, parent: QWidget | None = None, *, start_page: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("LyricLoom setup assistant")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setOption(QWizard.HaveHelpButton, False)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.setMinimumSize(840, 640)
        self.report = None
        self._setup_assistant = self
        self._pages: list[_JobPage] = []

        self.welcome = WelcomePage(self)
        self.library_page = LibraryPage(self)
        self.system_page = SystemCheckPage(self)
        self.acceleration_page = AccelerationPage(self)
        self.models_page = ModelsPage(self)
        self.privacy_page = PrivacyPage(self)
        self.musicbee_page = MusicBeePage(self)
        self.finish_page = FinishPage(self)
        for page_id, page in (
                (PAGE_WELCOME, self.welcome),
                (PAGE_LIBRARY, self.library_page),
                (PAGE_SYSTEM, self.system_page),
                (PAGE_ACCELERATION, self.acceleration_page),
                (PAGE_MODELS, self.models_page),
                (PAGE_PRIVACY, self.privacy_page),
                (PAGE_MUSICBEE, self.musicbee_page),
                (PAGE_FINISH, self.finish_page)):
            self.setPage(page_id, page)
            if isinstance(page, _JobPage):
                self._pages.append(page)
        if start_page is not None:
            page_id = PAGE_KEYS.get(str(start_page).lower())
            if page_id is not None:
                self.setStartId(page_id)

    def summary_text(self) -> str:
        library = config.library_root()
        if config.setting("wsl_gpu"):
            acceleration = (f"WSL {config.setting('wsl_distro') or 'auto'} · "
                            f"{config.setting('wsl_python') or 'python3'}")
        else:
            acceleration = "CPU"
        specs = models.default_models()
        ready = sum(1 for spec in specs if models.status(spec) == "ready")
        updates = "on" if config.setting("check_updates") is True else "off"
        cloud = "on" if config.assemblyai_enabled() else "off"
        plugin = musicbee.detect_musicbee()
        if plugin.plugin_installed:
            plugin_text = f"installed ({plugin.plugin_version or 'version unknown'})"
        elif plugin.detected:
            plugin_text = "MusicBee found, plugin not installed"
        else:
            plugin_text = "MusicBee not found"
        return (
            f"<b>Music folder</b><br>{library}<br><br>"
            f"<b>Acceleration</b><br>{acceleration}<br><br>"
            f"<b>Models</b><br>{ready} of {len(specs)} suggested models ready<br><br>"
            f"<b>Privacy</b><br>Startup update check: {updates}<br>"
            f"Cloud transcription: {cloud}<br><br>"
            f"<b>MusicBee</b><br>{plugin_text}")

    def accept(self) -> None:
        for page in self._pages:
            shutdown = getattr(page, "shutdown", None)
            if shutdown is not None:
                shutdown()
        for page in (self.library_page, self.privacy_page):
            if not page.apply():
                self.setCurrentPage(PAGE_LIBRARY if page is self.library_page else PAGE_PRIVACY)
                return
        try:
            config.set_setting(SETUP_COMPLETE, True)
        except OSError as exc:
            QMessageBox.critical(self, "Setup",
                                 f"Could not save the setup result:\n{exc.strerror or exc}")
            return
        super().accept()

    def reject(self) -> None:
        for page in self._pages:
            page.shutdown()
        super().reject()

    def done(self, result: int) -> None:
        for page in self._pages:
            page.shutdown()
        super().done(result)
        # The assistant is single-use: delete it explicitly after the finished signal so an old
        # dialog and its widgets are not left for the garbage collector to delete later, possibly
        # while another job's thread is running.
        self.deleteLater()


# --------------------------------------------------------------------------- helpers


def _free_space_error(specs) -> str | None:
    """The Models window's check when available; otherwise no extra check (engine verifies)."""
    try:
        from .models_window import free_space_error
    except Exception:  # noqa: BLE001 - the Models window is optional
        return None
    try:
        return free_space_error(specs)
    except Exception as exc:  # noqa: BLE001 - never block setup on a disk-stat failure
        return f"Could not check the free disk space: {exc}"


def _shell_execute(command: list[str]) -> None:
    """Start an elevated Windows process.  Only called after the user clicks the button."""
    if not command:
        raise ValueError("empty command")
    import ctypes

    verb = "runas"
    file = command[0]
    parameters = subprocess.list2cmdline(command[1:])
    result = ctypes.windll.shell32.ShellExecuteW(None, verb, file, parameters, None, 1)
    if int(result) <= 32:
        raise OSError(int(result), "ShellExecuteW could not start the elevated process")


__all__ = ["ASK_BEFORE_UPLOAD", "PAGE_KEYS", "SETUP_COMPLETE", "SetupAssistant"]
