"""Settings, model-manager and update dialogs. Kept apart from the main window so the window
stays focused on the library and the editor."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QProgressDialog, QPushButton, QVBoxLayout, QWidget)

from .. import VERSION, config, gpu_runtime, runtime, setup, updater
from ..errtext import os_error_text

ASK_BEFORE_UPLOAD = "assemblyai_ask_before_upload"
_TEST_KEEP_ALIVE: list[tuple[QThread, _SetupCheck]] = []
LOG = logging.getLogger(__name__)


def validate_folder(field: str, text: str, *, must_exist: bool, create: bool = False
                    ) -> tuple[Path | None, str | None]:
    """Checks one folder field. Returns (path, None) or (None, message naming the field).

    An empty field is rejected before Path("") turns into "." (the process working directory), and
    the folder must be usable now: exist (or be creatable), be a directory and accept a write.
    """
    raw = text.strip()
    if not raw:
        return None, f"{field}: choose a folder (the field is empty)."
    if raw in (".", ".."):
        return None, f"{field}: choose a real folder, not {raw!r}."
    path = Path(raw).expanduser()
    try:
        path = path.resolve()
    except OSError as exc:
        return None, f"{field}: cannot use {path}:\n{os_error_text(exc)}"
    if path.parent == path:
        return None, f"{field}: choose a folder inside a drive, not the drive root ({path})."
    if not path.exists():
        if not create:
            return None, f"{field}: the folder does not exist:\n{path}"
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return None, f"{field}: cannot create {path}:\n{os_error_text(exc)}"
    if not path.is_dir():
        return None, f"{field}: this is a file, not a folder:\n{path}"
    probe = path / ".lyricloom-write-test"
    try:
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return None, f"{field}: the folder is not writable:\n{path}\n{os_error_text(exc)}"
    return path, None


class _SetupCheck(QObject):
    """Runs ``setup.detect`` for the Settings dialog's Test button."""

    done = Signal(object)
    failed = Signal(str)

    @Slot()
    def run(self) -> None:
        try:
            self.done.emit(setup.detect())
        except Exception as exc:  # noqa: BLE001 - shown in a message box
            self.failed.emit(f"{type(exc).__name__}: {exc}")


def join_test_threads(timeout_ms: int = 5000) -> None:
    """Joins acceleration-test threads that outlived the dialog, with a bounded wait (FRB-06)."""
    for thread, _worker in list(_TEST_KEEP_ALIVE):
        try:
            if thread.isRunning():
                thread.quit()
                if not thread.wait(timeout_ms):
                    LOG.warning("the acceleration test did not stop within %d ms", timeout_ms)
        except RuntimeError:
            pass


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("LyricLoom settings")
        self.setMinimumWidth(620)
        data = config.all_settings()
        layout = QVBoxLayout(self)

        paths = QGroupBox("Library and cache")
        form = QFormLayout(paths)
        self.library = QLineEdit(str(config.library_root()))
        self.library.setPlaceholderText("Folder that contains your music")
        self.library_btn = QPushButton("Browse…")
        self.library_btn.clicked.connect(lambda: self._browse(self.library))
        form.addRow("Music library", self._with_button(self.library, self.library_btn))
        self.vocals = QLineEdit(str(config.vocals_root()))
        self.vocals.setPlaceholderText("Where isolated vocals are cached")
        self.vocals_btn = QPushButton("Browse…")
        self.vocals_btn.clicked.connect(lambda: self._browse(self.vocals))
        form.addRow("Vocals cache", self._with_button(self.vocals, self.vocals_btn))
        self.vocal_export = QComboBox()
        self.vocal_export.addItem("Only in the vocals cache", "off")
        self.vocal_export.addItem("Also next to each song, as <song>_vocal.flac", "beside")
        self.vocal_export.addItem("Also in another folder, as <song>_vocal.flac", "folder")
        self.vocal_export.setCurrentIndex(
            max(0, self.vocal_export.findData(config.vocal_export_mode())))
        self.vocal_export.setToolTip(
            "A lossless copy of the isolated vocals for your own use, written when a song is "
            "separated. LyricLoom's library ignores these files; another player that scans the "
            "music folder will list them as tracks.")
        self.vocal_export.currentIndexChanged.connect(self._vocal_export_changed)
        form.addRow("Save isolated vocals", self.vocal_export)
        self.vocal_folder = QLineEdit(str(config.vocal_export_folder() or ""))
        self.vocal_folder.setPlaceholderText("Folder for the <song>_vocal.flac copies")
        self.vocal_folder_btn = QPushButton("Browse…")
        self.vocal_folder_btn.clicked.connect(lambda: self._browse(self.vocal_folder))
        form.addRow("Vocal copies folder",
                    self._with_button(self.vocal_folder, self.vocal_folder_btn))
        self._vocal_export_changed()
        self.work = QLineEdit(str(config.WORK_ROOT))
        self.work.setPlaceholderText("Scratch folder for processing caches")
        self.work_btn = QPushButton("Browse…")
        self.work_btn.clicked.connect(lambda: self._browse(self.work))
        form.addRow("Work cache", self._with_button(self.work, self.work_btn))
        self.script = QComboBox()
        self.script.addItems(["Japanese text", "Romaji"])
        self.script.setCurrentIndex(1 if config.japanese_script() == "romaji" else 0)
        form.addRow("Japanese .lrc", self.script)
        layout.addWidget(paths)

        behaviour = QGroupBox("Behaviour")
        bform = QFormLayout(behaviour)
        self.notify_finished = QCheckBox("Notify when a long queue finishes in the background")
        self.notify_finished.setChecked(bool(data.get("notify_queue_finished", True)))
        bform.addRow(self.notify_finished)
        layout.addWidget(behaviour)

        animation = QGroupBox("Animation")
        aform = QFormLayout(animation)
        self.smooth = QComboBox()
        self.smooth.addItems(["Match display (default)", "Half refresh", "Third refresh"])
        self.smooth.setCurrentIndex(config.smooth_animation_divisor() - 1)
        self.smooth.setToolTip("Lower rates are exact integer divisors of the display refresh rate")
        aform.addRow("Smooth animation", self.smooth)
        animation_note = QLabel("The karaoke view and the main lyric view animate at the display's "
                                "refresh rate; lower choices stay exact divisors so motion never judders.")
        animation_note.setWordWrap(True)
        aform.addRow(animation_note)
        layout.addWidget(animation)

        gpu = QGroupBox("GPU through WSL (advanced)")
        gform = QFormLayout(gpu)
        self.wsl = QCheckBox("Run separation and forced alignment in WSL")
        self.wsl.setChecked(bool(data.get("wsl_gpu", False)))
        gform.addRow(self.wsl)
        self.distro = QLineEdit(str(data.get("wsl_distro", "")))
        self.distro.setPlaceholderText("e.g. Ubuntu (leave empty to auto-detect)")
        gform.addRow("WSL distro", self.distro)
        self.wsl_python = QLineEdit(str(data.get("wsl_python", "/opt/lyricloom/venv/bin/python")))
        gform.addRow("Python in WSL", self.wsl_python)
        self.torch_home = QLineEdit(str(data.get("wsl_torch_home", "/opt/lyricloom/models/torch")))
        gform.addRow("TORCH_HOME in WSL", self.torch_home)
        self.hsa = QLineEdit(str(data.get("wsl_hsa_override", "")))
        self.hsa.setPlaceholderText("Only if ROCm needs it, e.g. 10.3.0 for gfx1030")
        gform.addRow("HSA_OVERRIDE_GFX_VERSION", self.hsa)
        note = QLabel("WSL changes take effect after restarting LyricLoom. See docs/wsl-rocm.md. "
                      "For a GPU on Windows without WSL, use Acceleration > Change… below.")
        note.setWordWrap(True)
        gform.addRow(note)
        layout.addWidget(gpu)

        acceleration = QGroupBox("Acceleration")
        aform = QFormLayout(acceleration)
        self.acceleration_label = QLabel(self._acceleration_text())
        self.acceleration_label.setWordWrap(True)
        aform.addRow(self.acceleration_label)
        arow = QHBoxLayout()
        self.test_btn = QPushButton("Test")
        self.test_btn.setToolTip("Check the CPU, GPUs, WSL and whisper-cli again")
        self.test_btn.clicked.connect(self._test_acceleration)
        self.change_accel_btn = QPushButton("Change…")
        self.change_accel_btn.setToolTip("Open the setup assistant on its Acceleration page")
        self.change_accel_btn.clicked.connect(self._change_acceleration)
        arow.addWidget(self.test_btn)
        arow.addWidget(self.change_accel_btn)
        arow.addStretch(1)
        aform.addRow(arow)
        layout.addWidget(acceleration)

        privacy = QGroupBox("Privacy")
        pform = QFormLayout(privacy)
        self.check_updates = QCheckBox("Check GitHub Releases for updates at startup and every 24 hours")
        self.check_updates.setChecked(updater.check_enabled())
        self.check_updates.setToolTip(
            "When on, one request to api.github.com asks for public release metadata at startup "
            "and every 24 hours. Nothing about you or your library is sent.")
        pform.addRow(self.check_updates)
        self.update_install = QComboBox()
        for label, mode in (("Install automatically when LyricLoom closes", "auto"),
                            ("Ask before installing", "ask"),
                            ("Only notify me", "notify")):
            self.update_install.addItem(label, mode)
        self.update_install.setCurrentIndex(max(0, self.update_install.findData(updater.install_mode())))
        self.update_install.setToolTip(
            "Automatic: download a verified update in the background and install it silently when "
            "LyricLoom closes. Ask: download and install only after you click Install now. Notify: "
            "only show that a new release exists.")
        pform.addRow("When an update is found", self.update_install)
        self.cloud = QCheckBox("Allow uploading the isolated vocal to AssemblyAI")
        self.cloud.setChecked(config.assemblyai_enabled())
        self.cloud.setToolTip(
            "Cloud transcription is off by default. When on, songs that need help may upload "
            "their isolated vocal to AssemblyAI.")
        pform.addRow(self.cloud)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText(
            "A key is set; type a new one to replace it" if config.has_assemblyai_key()
            else "Paste your AssemblyAI API key")
        self.remove_key_btn = QPushButton("Remove stored key")
        self.remove_key_btn.setEnabled(config.has_assemblyai_key())
        self.remove_key_btn.clicked.connect(self._remove_key)
        self._remove_key_requested = False
        pform.addRow("AssemblyAI key", self._with_button(self.key, self.remove_key_btn))
        self.ask_upload = QCheckBox("Ask before uploading each queue")
        self.ask_upload.setChecked(bool(data.get(ASK_BEFORE_UPLOAD, True)))
        pform.addRow(self.ask_upload)
        layout.addWidget(privacy)

        self.assistant_page: str | None = None
        self._test_thread: QThread | None = None
        self._test_worker: _SetupCheck | None = None
        self._test_progress: QProgressDialog | None = None

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _vocal_export_changed(self, *_args) -> None:
        folder = self.vocal_export.currentData() == "folder"
        self.vocal_folder.setEnabled(folder)
        self.vocal_folder_btn.setEnabled(folder)

    def _acceleration_text(self) -> str:
        selected = gpu_runtime.acceleration_text()
        whisper = config.whisper_cli()
        state = "found" if whisper.is_file() else "missing"
        return f"Separation/alignment: {selected}\nwhisper-cli: {whisper} ({state})"

    def _change_acceleration(self) -> None:
        self.assistant_page = "acceleration"
        self._save()

    def _remove_key(self) -> None:
        self._remove_key_requested = True
        self.key.clear()
        self.key.setPlaceholderText("The stored key will be removed when you save")
        self.remove_key_btn.setEnabled(False)

    def _test_acceleration(self) -> None:
        if self._test_thread is not None:
            return
        self._test_progress = QProgressDialog(
            "Checking CPU, GPUs, WSL and whisper-cli…", "", 0, 0, self)
        self._test_progress.setWindowTitle("Acceleration")
        self._test_progress.setCancelButton(None)
        self._test_progress.setAutoClose(False)
        self._test_progress.setAutoReset(False)
        self._test_progress.show()
        thread = QThread()
        worker = _SetupCheck()
        _TEST_KEEP_ALIVE.append((thread, worker))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._test_done, Qt.QueuedConnection)
        worker.failed.connect(self._test_failed, Qt.QueuedConnection)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._test_finished)
        self._test_thread, self._test_worker = thread, worker
        self.test_btn.setEnabled(False)
        thread.start()

    @Slot(object)
    def _test_done(self, report) -> None:
        recommendation = setup.recommend(report)
        wsl = (f"WSL 2 · {', '.join(d.name for d in report.wsl.distros)}"
               if report.wsl.version2 else (report.wsl.error or "WSL not available"))
        disk = (runtime.human_size(report.disk_free_bytes)
                if report.disk_free_bytes is not None else "unknown")
        whisper = (report.whisper_cli.path if report.whisper_cli.present
                   else (report.whisper_cli.error or "not found"))
        text = (
            f"CPU: {report.cpu_cores or 'unknown'} cores\n"
            f"Memory: {runtime.human_size(report.ram_bytes) if report.ram_bytes else 'unknown'}\n"
            f"Free disk: {disk}\n"
            f"GPU: {', '.join(gpu.name for gpu in report.gpus) or 'none detected'}\n"
            f"{wsl}\n"
            f"whisper-cli: {whisper}\n\n"
            f"Suggested: {recommendation.acceleration_reason}\n"
            f"{recommendation.whisper_backend_reason}")
        QMessageBox.information(self, "Acceleration", text)

    @Slot(str)
    def _test_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Acceleration", "The check failed:\n" + message)

    @Slot()
    def _test_finished(self) -> None:
        if self._test_progress is not None:
            self._test_progress.close()
            self._test_progress = None
        self._test_thread = None
        self._test_worker = None
        self.test_btn.setEnabled(True)
        self.acceleration_label.setText(self._acceleration_text())

    @staticmethod
    def _with_button(edit: QLineEdit, button: QPushButton) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, 1)
        row.addWidget(button)
        return box

    def _browse(self, edit: QLineEdit):
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder", edit.text() or str(Path.home()))
        if folder:
            edit.setText(folder)

    def _save(self):
        values = {}
        for field, edit, must_exist, create in (
                ("Music library", self.library, True, False),
                ("Vocals cache", self.vocals, False, True),
                ("Work cache", self.work, False, True)):
            path, error = validate_folder(field, edit.text(), must_exist=must_exist, create=create)
            if error:
                QMessageBox.warning(self, field, error)
                edit.setFocus()
                edit.selectAll()
                return
            values[field] = path
        export_mode = self.vocal_export.currentData()
        export_folder = self.vocal_folder.text().strip()
        if export_mode == "folder":
            path, error = validate_folder("Vocal copies folder", export_folder,
                                          must_exist=False, create=True)
            if error:
                QMessageBox.warning(self, "Vocal copies folder", error)
                self.vocal_folder.setFocus()
                self.vocal_folder.selectAll()
                return
            export_folder = str(path)
        # One acceleration choice is in effect at a time: turning WSL on here deselects the
        # Windows GPU runtime (it stays installed), exactly as the assistant does.
        runtime_off = ({"gpu_backend": "", "gpu_python": ""}
                       if self.wsl.isChecked() and not config.setting("wsl_gpu", False) else {})
        try:
            key = self.key.text().strip()
            if key:
                config.set_assemblyai_key(key)
                self._remove_key_requested = False
                self.key.clear()
                self.key.setPlaceholderText("A key is set; type a new one to replace it")
                self.remove_key_btn.setEnabled(True)
            elif self._remove_key_requested:
                config.set_assemblyai_key("")
                self.remove_key_btn.setEnabled(False)
            config.update_settings({
                "library": str(values["Music library"]),
                "vocals": str(values["Vocals cache"]),
                "work": str(values["Work cache"]),
                "vocal_export": export_mode,
                "vocal_export_folder": export_folder,
                "japanese_script": "romaji" if self.script.currentIndex() else "japanese",
                "check_updates": self.check_updates.isChecked(),
                "assemblyai_enabled": self.cloud.isChecked(),
                ASK_BEFORE_UPLOAD: self.ask_upload.isChecked(),
                "update_install": self.update_install.currentData(),
                "notify_queue_finished": self.notify_finished.isChecked(),
                "smooth_animation": self.smooth.currentIndex() + 1,
                "wsl_gpu": self.wsl.isChecked(),
                "wsl_distro": self.distro.text().strip(),
                "wsl_python": self.wsl_python.text().strip() or "python3",
                "wsl_torch_home": self.torch_home.text().strip() or "/opt/lyricloom/models/torch",
                "wsl_hsa_override": self.hsa.text().strip(),
                **runtime_off,
            })
        except OSError as exc:
            QMessageBox.critical(
                self, "Settings",
                f"Could not save the settings to {config.SETTINGS_FILE}:\n{os_error_text(exc)}")
            return
        except (RuntimeError, ValueError) as exc:
            QMessageBox.critical(self, "AssemblyAI", str(exc))
            return
        self.accept()


class _UpdateCheck(QObject):
    done = Signal(object)
    failed = Signal(str)

    @Slot()
    def run(self):
        try:
            self.done.emit(updater.check())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class _UpdateDownload(QObject):
    progress = Signal(int, int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, info: updater.UpdateInfo, cancel: threading.Event):
        super().__init__()
        self.info = info
        self.cancel = cancel

    @Slot()
    def run(self):
        try:
            self.done.emit(updater.download(self.info, self.progress.emit, cancel=self.cancel))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class UpdateController(QObject):
    """Owns the update threads and receives their signals in the GUI thread.

    Workers emit from their own thread. Qt only queues a signal to a receiver that lives in the GUI
    thread and has a slot; connecting to a plain Python closure runs it in the emitting thread, which
    is how the old code touched QMessageBox/QProgressDialog from a worker.
    """

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self._silent = False
        self._threads: list[QThread] = []
        self._check_thread: QThread | None = None
        self._check_worker: _UpdateCheck | None = None
        self._download_thread: QThread | None = None
        self._download_worker: _UpdateDownload | None = None
        self._progress: QProgressDialog | None = None
        self._cancel = threading.Event()
        self._download_automatic = False
        self._download_info: updater.UpdateInfo | None = None
        self._info: updater.UpdateInfo | None = None
        self._downloaded: Path | None = None

    def _bar(self):
        return getattr(self._window, "update_bar", None)

    def _status(self, message: str, timeout: int = 12000) -> None:
        status = getattr(self._window, "statusBar", None)
        if status is not None:
            bar = status() if callable(status) else status
            if bar is not None:
                bar.showMessage(message, timeout)

    def check(self, silent: bool = False) -> None:
        if self._check_thread is not None:
            return
        thread = QThread(self)
        worker = _UpdateCheck()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        # Queued explicitly: a worker signal must never run widget code in the worker thread.
        worker.done.connect(self.check_done, Qt.QueuedConnection)
        worker.failed.connect(self.check_failed, Qt.QueuedConnection)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._check_finished)
        self._silent = silent
        self._check_thread = thread
        self._check_worker = worker   # keep it alive until the thread starts and finishes
        self._threads.append(thread)
        thread.start()

    def download(self, info: updater.UpdateInfo, *, automatic: bool = False) -> bool:
        """Start a verified download. Returns False when one is already running."""
        if self._download_thread is not None:
            return False
        self._cancel.clear()
        self._download_automatic = automatic
        self._download_info = info
        if not automatic:
            self._progress = QProgressDialog(f"Downloading LyricLoom {info.version}…", "", 0, 0,
                                             self._window)
            self._progress.setWindowTitle("Updating LyricLoom")
            self._progress.setCancelButton(None)
            self._progress.setAutoClose(False)
            self._progress.setAutoReset(False)
            self._progress.show()
        thread = QThread(self)
        worker = _UpdateDownload(info, self._cancel)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.progress, Qt.QueuedConnection)
        worker.done.connect(self.download_done, Qt.QueuedConnection)
        worker.failed.connect(self.download_failed, Qt.QueuedConnection)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._download_finished)
        self._download_thread = thread
        self._download_worker = worker
        self._threads.append(thread)
        thread.start()
        return True

    def _check_finished(self) -> None:
        self._check_thread = None
        self._check_worker = None

    def _download_finished(self) -> None:
        self._download_thread = None
        self._download_worker = None

    @Slot(object)
    def check_done(self, info) -> None:
        if info is None:
            if not self._silent:
                QMessageBox.information(self._window, "Updates",
                                        f"You have the latest version (LyricLoom {VERSION}).")
            return
        if updater.is_skipped(info.version):
            if not self._silent:
                QMessageBox.information(
                    self._window, "Updates",
                    f"LyricLoom {info.version} is available, but you chose to skip this version. "
                    "You will be offered newer versions when they are released.")
            return
        if self._info is not None and self._info.version == info.version and self._downloaded is not None:
            self._show_notice()   # already downloaded; a re-check must not fetch it again
            return
        self._info = info
        self._downloaded = None
        if self._silent:
            self._status(f"Update {info.version} is available", 12000)
        if not updater.installer_available():
            self._show_notice()
            return
        if updater.install_mode() == "auto":
            self._status(f"Downloading LyricLoom {info.version} …")
            if self.download(info, automatic=True):
                return
        self._show_notice()

    def _show_notice(self) -> None:
        """Show (or refresh) the non-modal banner for the current release."""
        info = self._info
        if info is None:
            return
        action_text = None
        mode = updater.install_mode()
        if updater.installer_available():
            if mode == "auto" and self._downloaded is not None:
                action_text = "Restart now"
            elif mode == "ask":
                action_text = "Install now"   # also after a postponed install of the download
        bar = self._bar()
        if bar is None:
            if not self._silent:
                QMessageBox.information(
                    self._window, "Update available",
                    f"LyricLoom {info.version} is available.\n\n"
                    f"{info.notes or 'See the release page for details.'}")
            return
        bar.show_update(
            info,
            action_text=action_text,
            show_tarball=not updater.installer_available() and not config.IS_WINDOWS,
            on_action=self._notice_action,
            on_later=self._notice_later,
            on_skip=self._notice_skip,
        )

    def _notice_action(self) -> None:
        """The banner's mode-specific action: install a ready download or start an ask download."""
        if self._info is None:
            return
        if self._downloaded is not None:
            if updater.install_mode() == "ask":
                self._begin_install(silent=False, relaunch=False)
            else:
                self._begin_install(silent=True, relaunch=True)
        elif updater.install_mode() == "ask":
            self._status(f"Downloading LyricLoom {self._info.version} …")
            if not self.download(self._info, automatic=False):
                QMessageBox.warning(self._window, "Updates", "An update download is already running.")

    def _notice_later(self) -> None:
        if self._downloaded is not None and updater.install_mode() == "auto":
            self._status("Update postponed; it will be installed when LyricLoom closes", 8000)
        else:
            self._status("Update postponed", 8000)

    def _notice_skip(self) -> None:
        info = self._info
        if info is None:
            return
        if self._download_thread is not None:
            self._cancel.set()   # a running download of the skipped release stops between chunks
        try:
            updater.skip_version(info.version)
        except OSError as exc:
            QMessageBox.warning(self._window, "Updates",
                                f"Could not remember the skipped version:\n{os_error_text(exc)}")
        path = self.take_downloaded_update()
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        self._status(f"LyricLoom {info.version} will not be offered again", 8000)

    def take_downloaded_update(self, path: Path | None = None, *,
                               auto_only: bool = False) -> Path | None:
        """Hand a verified download to the caller once; never returns the same file twice."""
        if self._downloaded is None:
            return None
        if auto_only and updater.install_mode() != "auto":
            return None
        if path is not None and Path(path) != self._downloaded:
            return None
        result, self._downloaded = self._downloaded, None
        return result

    @property
    def downloaded_info(self) -> updater.UpdateInfo | None:
        """The release of the verified download that is still waiting to be installed."""
        return self._info if self._downloaded is not None else None

    def install_postponed(self) -> None:
        """MainWindow's close was vetoed after "Restart now"/"Install now": offer it again."""
        self._notice_later()
        self._show_notice()

    def _begin_install(self, *, silent: bool, relaunch: bool) -> bool:
        """Hand the install request to MainWindow, which closes and starts Setup last.

        Setup is never started here: a prompt during the close can still start a queue or veto
        the close, so only MainWindow's close knows when the install may really begin.
        """
        path = self._downloaded
        prepare = getattr(self._window, "prepare_update", None)
        if path is None or prepare is None:
            return False
        prepare(path, info=self._info, silent=silent, relaunch=relaunch)
        return True

    @Slot(str)
    def check_failed(self, message: str) -> None:
        # Always logged: the automatic check shows nothing, so the log is the only trace of it.
        LOG.warning("update check failed: %s", message)
        if not self._silent:
            QMessageBox.warning(self._window, "Updates", "Could not check for updates:\n" + message)

    @Slot(int, int)
    def progress(self, done: int, total: int) -> None:
        if self._progress is None:
            return
        if total:
            self._progress.setRange(0, 1000)
            self._progress.setValue(min(1000, int(done * 1000 / total)))

    @Slot(object)
    def download_done(self, path) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        automatic, self._download_automatic = self._download_automatic, False
        downloaded_info, self._download_info = self._download_info, None
        if (self._info is not None and downloaded_info is not None
                and downloaded_info.version != self._info.version):
            # A check found a different release while this download ran; never install the
            # verified file as if it belonged to the new version (it will be cleaned on restart).
            return
        release = downloaded_info or self._info
        if release is not None and updater.is_skipped(release.version):
            # "Skip this version" was clicked while the download ran: never arm or install it.
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass   # never trusted again: the next start deletes what this process left
            return
        self._downloaded = Path(path)
        if automatic:
            self._show_notice()
            if self._info is not None:
                self._status(f"LyricLoom {self._info.version} is ready; restart to install", 12000)
            return
        self._begin_install(silent=False, relaunch=False)

    @Slot(str)
    def download_failed(self, message: str) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        automatic, self._download_automatic = self._download_automatic, False
        self._download_info = None
        if self._cancel.is_set():
            return   # shutting down: the user asked for the download to stop
        if automatic:
            self._status("Could not download the update: " + message, 12000)
            self._show_notice()   # still offer the release page and the notes
            return
        QMessageBox.critical(self._window, "Update failed", message)

    def shutdown(self) -> None:
        """Stop the update threads when the window closes. Never terminates a thread."""
        self._cancel.set()
        for thread in list(self._threads):
            if thread.isRunning():
                thread.quit()
                thread.wait(3000)

    def wait_for_threads(self) -> None:
        """Joins update threads that outlived the event loop (a blocking network call)."""
        for thread in list(self._threads):
            if thread.isRunning():
                thread.quit()
                thread.wait()


def check_for_updates(parent: QWidget, silent: bool = False) -> None:
    """Check GitHub in a worker thread. `silent` is the startup path: no dialog when there is
    nothing new or the network is down."""
    controller = getattr(parent, "_update_controller", None)
    if controller is None:
        controller = UpdateController(parent)
        parent._update_controller = controller
    controller.check(silent=silent)
