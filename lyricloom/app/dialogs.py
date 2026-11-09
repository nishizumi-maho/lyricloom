"""Settings, model-manager and update dialogs. Kept apart from the main window so the window
stays focused on the library and the editor."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QProgressDialog, QPushButton, QVBoxLayout, QWidget)

from .. import VERSION, config, updater


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
        return None, f"{field}: cannot use {path}:\n{exc.strerror or exc}"
    if path.parent == path:
        return None, f"{field}: choose a folder inside a drive, not the drive root ({path})."
    if not path.exists():
        if not create:
            return None, f"{field}: the folder does not exist:\n{path}"
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return None, f"{field}: cannot create {path}:\n{exc.strerror or exc}"
    if not path.is_dir():
        return None, f"{field}: this is a file, not a folder:\n{path}"
    probe = path / ".lyricloom-write-test"
    try:
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return None, f"{field}: the folder is not writable:\n{path}\n{exc.strerror or exc}"
    return path, None


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
        self.check_updates = QCheckBox("Check GitHub Releases for updates on startup")
        self.check_updates.setChecked(data.get("check_updates") is True)
        bform.addRow(self.check_updates)
        self.notify_finished = QCheckBox("Notify when a long queue finishes in the background")
        self.notify_finished.setChecked(bool(data.get("notify_queue_finished", True)))
        bform.addRow(self.notify_finished)
        layout.addWidget(behaviour)

        gpu = QGroupBox("GPU through WSL (Windows + AMD ROCm)")
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
        note = QLabel("WSL changes take effect after restarting LyricLoom. See docs/wsl-rocm.md.")
        note.setWordWrap(True)
        gform.addRow(note)
        layout.addWidget(gpu)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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
        try:
            config.update_settings({
                "library": str(values["Music library"]),
                "vocals": str(values["Vocals cache"]),
                "work": str(values["Work cache"]),
                "japanese_script": "romaji" if self.script.currentIndex() else "japanese",
                "check_updates": self.check_updates.isChecked(),
                "notify_queue_finished": self.notify_finished.isChecked(),
                "wsl_gpu": self.wsl.isChecked(),
                "wsl_distro": self.distro.text().strip(),
                "wsl_python": self.wsl_python.text().strip() or "python3",
                "wsl_torch_home": self.torch_home.text().strip() or "/opt/lyricloom/models/torch",
                "wsl_hsa_override": self.hsa.text().strip(),
            })
        except OSError as exc:
            QMessageBox.critical(
                self, "Settings",
                f"Could not save the settings to {config.SETTINGS_FILE}:\n{exc.strerror or exc}")
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

    def download(self, info: updater.UpdateInfo) -> None:
        if self._download_thread is not None:
            return
        self._cancel.clear()
        self._progress = QProgressDialog(f"Downloading LyricLoom {info.version}…", "", 0, 0, self._window)
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
                QMessageBox.information(self._window, "Updates", f"LyricLoom {VERSION} is up to date.")
            return
        if self._silent:
            self._window.statusBar().showMessage(
                f"Update {info.version} is available (Help > Check for updates)", 12000)
            return
        answer = QMessageBox.question(
            self._window, "Update available",
            f"LyricLoom {info.version} is available (you have {VERSION}).\n\n"
            f"{(info.notes or 'See the release page for details.')[:1800]}\n\nDownload and install now?")
        if answer == QMessageBox.Yes:
            self.download(info)

    @Slot(str)
    def check_failed(self, message: str) -> None:
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
        prepare = getattr(self._window, "prepare_update", None)
        if prepare is not None and not prepare(path):
            return   # the queue is still stopping; MainWindow installs it when it finishes
        try:
            updater.launch_installer(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self._window, "Update", "Could not start the installer:\n" + str(exc))
            return
        # Close the window so the normal close path stops the background threads instead of a bare
        # event-loop exit while the update/scan threads still run.
        if hasattr(self._window, "close"):
            self._window.close()
        else:
            QApplication.quit()

    @Slot(str)
    def download_failed(self, message: str) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        if self._cancel.is_set():
            return   # shutting down: the user asked for the download to stop
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
