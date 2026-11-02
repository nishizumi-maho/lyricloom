"""Settings, model-manager and update dialogs. Kept apart from the main window so the window
stays focused on the library and the editor."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QProgressDialog, QPushButton, QVBoxLayout, QWidget)

from .. import VERSION, config, runtime, updater

MODEL_ROWS = (
    ("whisper", "Whisper large-v3", "3.1 GB", "Transcribes vocals when no lyric is found."),
    ("separator", "Mel-Band RoFormer", "0.9 GB", "Separates vocals from the instrumental."),
    ("mms", "MMS forced alignment", "1.2 GB", "Word timing for non-English lyrics."),
    ("mtl", "English singing model", "66 MB", "Better word timing for English songs."),
)


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
        self.check_updates.setChecked(bool(data.get("check_updates", True)))
        bform.addRow(self.check_updates)
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
        library = Path(self.library.text().strip()).expanduser()
        vocals = Path(self.vocals.text().strip()).expanduser()
        work = Path(self.work.text().strip() or config.WORK_ROOT).expanduser()
        if not library.is_dir():
            QMessageBox.warning(self, "Library", f"The library folder does not exist:\n{library}")
            return
        if not str(vocals):
            QMessageBox.warning(self, "Vocals cache", "Choose a folder for the cached vocals.")
            return
        config.update_settings({
            "library": str(library),
            "vocals": str(vocals),
            "work": str(work),
            "japanese_script": "romaji" if self.script.currentIndex() else "japanese",
            "check_updates": self.check_updates.isChecked(),
            "wsl_gpu": self.wsl.isChecked(),
            "wsl_distro": self.distro.text().strip(),
            "wsl_python": self.wsl_python.text().strip() or "python3",
            "wsl_torch_home": self.torch_home.text().strip() or "/opt/lyricloom/models/torch",
            "wsl_hsa_override": self.hsa.text().strip(),
        })
        self.accept()


class ModelWorker(QObject):
    message = Signal(str)
    progress = Signal(int, int)
    done = Signal()
    failed = Signal(str)

    @Slot()
    def run(self):
        try:
            missing = runtime.status()
            if not missing["whisper"]:
                self.message.emit("Downloading the Whisper model (about 3.1 GB)…")
                runtime.download_whisper(self.progress.emit)
            if not missing["separator"]:
                self.message.emit("Downloading the vocal separator (about 0.9 GB)…")
                self.progress.emit(0, 0)
                runtime.download_separator()
            if not missing["mms"]:
                self.message.emit("Downloading the forced-alignment model (about 1.2 GB)…")
                self.progress.emit(0, 0)
                runtime.download_mms()
            if not missing["mtl"]:
                self.message.emit("Downloading the English singing model (about 66 MB)…")
                runtime.download_mtl(self.progress.emit)
            if not runtime._nltk_ready():
                self.message.emit("Downloading the NLTK data used by the singing model…")
                self.progress.emit(0, 0)
                runtime.download_nltk()
            self.done.emit()
        except Exception as exc:  # noqa: BLE001 - shown in the dialog, never crashes the app
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class ModelsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("LyricLoom models")
        self.setMinimumWidth(620)
        self._thread: QThread | None = None
        self._worker: ModelWorker | None = None
        layout = QVBoxLayout(self)
        intro = QLabel("Models are downloaded once and kept in the LyricLoom data folder. "
                       "They are not bundled in the installer because they total about 5 GB.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.rows: dict[str, QLabel] = {}
        form = QFormLayout()
        for key, name, size, why in MODEL_ROWS:
            label = QLabel("…")
            label.setToolTip(why)
            self.rows[key] = label
            form.addRow(f"{name} ({size})", label)
        layout.addLayout(form)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressDialog("Preparing…", "", 0, 100, self)
        self.progress.setWindowTitle("Downloading models")
        self.progress.setCancelButton(None)
        self.progress.setAutoClose(False)
        self.progress.setAutoReset(False)
        self.progress.hide()
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.open_btn = QPushButton("Open models folder")
        self.open_btn.clicked.connect(self._open_folder)
        self.download_btn = QPushButton("Download missing models")
        self.download_btn.clicked.connect(self._download)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        buttons.addWidget(self.open_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.download_btn)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        state = runtime.status()
        for key, label in self.rows.items():
            label.setText("Ready" if state.get(key) else "Missing")
            label.setStyleSheet("" if state.get(key) else "color: #c06000;")
        self.download_btn.setEnabled(not all(state.values()) or not runtime._nltk_ready())

    def _open_folder(self):
        config.MODELS.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(config.MODELS)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(config.MODELS)])

    def _download(self):
        if self._thread is not None:
            return
        self.download_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.show()
        thread = QThread(self)
        worker = ModelWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.message.connect(self.status.setText)
        worker.progress.connect(self._progress)
        worker.done.connect(self._finished)
        worker.failed.connect(self._failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._thread_done)
        self._thread, self._worker = thread, worker
        thread.start()

    def _progress(self, done: int, total: int):
        if total:
            self.progress.setRange(0, 1000)
            self.progress.setValue(min(1000, int(done * 1000 / total)))
        else:
            self.progress.setRange(0, 0)

    def _finished(self):
        self.status.setText("All requested models are ready.")
        self.refresh()

    def _failed(self, message: str):
        QMessageBox.critical(self, "Model download failed", message + "\n\nSee docs/models.md for offline installation.")

    def _thread_done(self):
        self._thread = None
        self._worker = None
        self.progress.hide()
        self.download_btn.setEnabled(True)
        self.close_btn.setEnabled(True)

    def closeEvent(self, event):
        if self._thread is not None:
            event.ignore()
            return
        super().closeEvent(event)


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

    def __init__(self, info: updater.UpdateInfo):
        super().__init__()
        self.info = info

    @Slot()
    def run(self):
        try:
            self.done.emit(updater.download(self.info, self.progress.emit))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")


def check_for_updates(parent: QWidget, silent: bool = False) -> None:
    """Check GitHub in a worker thread. `silent` is the startup path: no dialog when there is
    nothing new or the network is down."""
    thread = QThread(parent)
    worker = _UpdateCheck()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)

    def finish(info):
        thread.quit()
        if info is None:
            if not silent:
                QMessageBox.information(parent, "Updates", f"LyricLoom {VERSION} is up to date.")
            return
        if silent:
            parent.statusBar().showMessage(f"Update {info.version} is available (Help > Check for updates)", 12000)
            return
        answer = QMessageBox.question(
            parent, "Update available",
            f"LyricLoom {info.version} is available (you have {VERSION}).\n\n"
            f"{(info.notes or 'See the release page for details.')[:1800]}\n\nDownload and install now?")
        if answer == QMessageBox.Yes:
            _download_and_install(parent, info)

    def failed(message):
        thread.quit()
        if not silent:
            QMessageBox.warning(parent, "Updates", "Could not check for updates:\n" + message)

    worker.done.connect(finish)
    worker.failed.connect(failed)
    thread.finished.connect(lambda: (worker.deleteLater(), thread.deleteLater()))
    parent._update_thread = thread   # keep both alive while the request runs
    parent._update_worker = worker
    thread.start()


def _download_and_install(parent: QWidget, info: updater.UpdateInfo) -> None:
    progress = QProgressDialog(f"Downloading LyricLoom {info.version}…", "", 0, 0, parent)
    progress.setWindowTitle("Updating LyricLoom")
    progress.setCancelButton(None)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    thread = QThread(parent)
    worker = _UpdateDownload(info)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)

    def update(done, total):
        if total:
            progress.setRange(0, 1000)
            progress.setValue(min(1000, int(done * 1000 / total)))

    def finish(path):
        thread.quit()
        progress.close()
        try:
            updater.launch_installer(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(parent, "Update", "Could not start the installer:\n" + str(exc))
            return
        QApplication.quit()

    def failed(message):
        thread.quit()
        progress.close()
        QMessageBox.critical(parent, "Update failed", message)

    worker.progress.connect(update)
    worker.done.connect(finish)
    worker.failed.connect(failed)
    thread.finished.connect(lambda: (worker.deleteLater(), thread.deleteLater()))
    parent._update_dl_thread = thread
    parent._update_dl_worker = worker
    thread.start()
