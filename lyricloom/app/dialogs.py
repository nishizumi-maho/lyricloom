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
        self.check_updates = QCheckBox("Check GitHub Releases for updates at startup and every 24 hours")
        self.check_updates.setChecked(updater.check_enabled())
        bform.addRow(self.check_updates)
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
        bform.addRow("When an update is found", self.update_install)
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
                "update_install": self.update_install.currentData(),
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
            elif mode == "ask" and self._downloaded is None:
                action_text = "Install now"
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
        try:
            updater.skip_version(info.version)
        except OSError as exc:
            QMessageBox.warning(self._window, "Updates",
                                f"Could not remember the skipped version:\n{exc}")
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

    def _begin_install(self, *, silent: bool, relaunch: bool) -> bool:
        """Ask MainWindow to stop the queue, then start the installer and close the window."""
        path = self._downloaded
        if path is None:
            return False
        prepare = getattr(self._window, "prepare_update", None)
        if prepare is not None and not prepare(path, silent=silent, relaunch=relaunch):
            return False   # the queue is still stopping; MainWindow installs it when it finishes
        try:
            updater.launch_installer(path, silent=silent, relaunch=relaunch, skip_plugin=False)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self._window, "Update", "Could not start the installer:\n" + str(exc))
            return False
        self.take_downloaded_update(path)
        # Close the window so the normal close path stops the background threads instead of a bare
        # event-loop exit while the update/scan threads still run.
        if hasattr(self._window, "close"):
            self._window.close()
        else:
            QApplication.quit()
        return True

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
        automatic, self._download_automatic = self._download_automatic, False
        downloaded_info, self._download_info = self._download_info, None
        if (self._info is not None and downloaded_info is not None
                and downloaded_info.version != self._info.version):
            # A check found a different release while this download ran; never install the
            # verified file as if it belonged to the new version (it will be cleaned on restart).
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
