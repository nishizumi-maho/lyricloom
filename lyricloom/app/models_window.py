"""The Models window: one row per model, per-language choices and verified downloads.

The engine owns the catalog and every check (``lyricloom.models``); this module only draws it and
runs the long calls in a worker.  Downloads are sequential, cancellable and resumable, and the
worker's signals are queued to the window so no widget is touched from a worker thread.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QProgressBar, QPushButton, QTabWidget,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import config, downloads, models, runtime

STAGE_TITLES = {
    "transcribe": "Transcription",
    "separate": "Vocal separation",
    "align": "Alignment",
    "singing": "Singing model",
}
LANGUAGES = [
    ("en", "English"),
    ("ja", "Japanese"),
    ("pt", "Portuguese"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("it", "Italian"),
    ("ko", "Korean"),
    ("zh", "Chinese"),
    ("ru", "Russian"),
]
LANGUAGE_NAMES = dict(LANGUAGES)
_LANGUAGE_CODE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$", re.IGNORECASE)
STATUS_LABELS = {"ready": "Ready", "missing": "Missing", "corrupt": "Corrupt",
                 "unverified": "Unverified"}


def _find_spec(model_id: str) -> models.ModelSpec | None:
    return models.find(model_id)


def used_for(spec: models.ModelSpec) -> list[str]:
    """``choices_for`` plus "default" for the catalog default when no explicit choice replaces it."""
    used = models.choices_for(spec)
    if spec.default and "default" not in used:
        default_map = config.model_choices().get("default")
        configured = default_map.get(spec.stage) if isinstance(default_map, dict) else None
        if not configured or configured == spec.id:
            used.insert(0, "default")
    return used


def _download_tasks(tasks: list["ModelTask"]) -> list[models.ModelSpec]:
    return [task.spec for task in tasks if task.kind in ("download", "repair")]


def free_space_error(specs: list[models.ModelSpec], root: Path | None = None) -> str | None:
    """A user-facing message when the models folder cannot hold the requested downloads.

    A resumed ``.part`` file is taken into account.  Nothing is created or written here.
    """
    root = Path(root or config.MODELS)
    required = 0
    for spec in specs:
        for file in spec.files:
            dest = spec.dest(file, root)
            part = dest.with_name(dest.name + ".part")
            try:
                have = part.stat().st_size if part.exists() else 0
            except OSError:
                have = 0
            required += max(0, int(file.size) - have)
    if not required:
        return None
    probe = root
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError as exc:
        return (f"Could not check the free disk space for the models folder:\n{root}\n\n"
                f"{exc.strerror or exc}")
    if free >= required:
        return None
    return (f"Not enough free disk space for this download.\n\nModels folder: {root}\n"
            f"Needed: {runtime.human_size(required)}\nFree: {runtime.human_size(free)}\n\n"
            "Free some space (or choose another models folder in Settings) and try again.")


@dataclass(frozen=True)
class ModelTask:
    kind: str                     # download | repair | verify
    spec: models.ModelSpec


class ModelTaskWorker(QObject):
    """Runs model downloads, repairs and verifications one at a time off the GUI thread."""

    message = Signal(str)
    progress = Signal(str, int, int)   # model id, bytes done, bytes total
    task_done = Signal(str, bool, str)  # model id, ok, summary
    cancelled = Signal()
    finished = Signal(bool)            # every requested task succeeded

    def __init__(self, tasks: list[ModelTask]):
        super().__init__()
        self._tasks = list(tasks)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    @Slot()
    def run(self) -> None:
        ok_all = True
        for task in self._tasks:
            if self._cancel.is_set():
                break
            spec = task.spec
            if task.kind == "verify":
                self.message.emit(f"Verifying {spec.label}…")
            else:
                verb = "Repairing" if task.kind == "repair" else "Downloading"
                self.message.emit(f"{verb} {spec.label} ({runtime.human_size(spec.total_size)})…")
                self.progress.emit(spec.id, 0, 0)

            def report(done: int, total: int, model_id: str = spec.id) -> None:
                self.progress.emit(model_id, done, total)

            try:
                if task.kind == "verify":
                    state = models.verify(spec)
                    ok = state == "ready"
                    self.task_done.emit(spec.id, ok, f"Verification: {state}")
                    ok_all = ok_all and ok
                elif task.kind == "repair":
                    models.repair(spec, progress=report, cancel=self._cancel)
                    self.task_done.emit(spec.id, True, "Repaired")
                else:
                    models.download(spec, progress=report, cancel=self._cancel)
                    self.task_done.emit(spec.id, True, "Downloaded")
            except downloads.DownloadCancelled:
                self.cancelled.emit()
                ok_all = False
                break
            except Exception as exc:  # noqa: BLE001 - shown in the window, never kills the thread
                ok_all = False
                self.task_done.emit(spec.id, False, f"{type(exc).__name__}: {exc}")
        if self._cancel.is_set():
            self.cancelled.emit()
        self.finished.emit(ok_all and not self._cancel.is_set())


class AddCustomModelDialog(QDialog):
    """Asks for the stage and a local file, or a separator registry name."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Add a custom model")
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.stage = QComboBox()
        for stage in models.STAGES:
            self.stage.addItem(STAGE_TITLES.get(stage, stage), stage)
        form.addRow("Stage", self.stage)
        self.source = QLineEdit()
        self.source.setPlaceholderText("A model file, or (for separation) a registry model name")
        self.browse = QPushButton("Browse…")
        self.browse.clicked.connect(self._browse)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(self.source, 1)
        line.addWidget(self.browse)
        form.addRow("Model", row)
        self.label = QLineEdit()
        self.label.setPlaceholderText("Optional name shown in the list")
        form.addRow("Label", self.label)
        layout.addLayout(form)
        note = QLabel(
            "A file is copied into LyricLoom's settings as a registration; the file itself is never "
            "moved, changed or deleted. For vocal separation you may instead type a model name from "
            "audio-separator's registry (for example UVR-MDX-NET-Voc-FT); LyricLoom downloads it when "
            "you add it.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self):
        stage = self.stage.currentData()
        filters = {"transcribe": "whisper.cpp models (*.bin)",
                   "separate": "Separator models (*.ckpt *.onnx *.pth)",
                   "align": "Alignment checkpoints (*.pt *.pth)",
                   "singing": "Singing model (checkpoint_MTL)"}.get(stage, "All files (*)")
        path, _selected = QFileDialog.getOpenFileName(self, "Choose a model file", "", filters)
        if path:
            self.source.setText(path)

    def accept(self):
        source = self.source.text().strip()
        if not source:
            QMessageBox.warning(self, "Add a custom model", "Choose a model file or enter a name.")
            self.source.setFocus()
            return
        super().accept()

    def values(self) -> tuple[str, str, str]:
        return self.stage.currentData(), self.source.text().strip(), self.label.text().strip()


class MissingModelsDialog(QDialog):
    """Lists missing/corrupt models with their total size; Download now / Open Models / Cancel."""

    def __init__(self, specs: list[models.ModelSpec], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Models needed")
        self.setMinimumWidth(620)
        self.choice = "cancel"
        self.specs = list(specs)
        layout = QVBoxLayout(self)
        text = QLabel("Some models the queued songs need are missing or corrupt. "
                      "The queue will not start until they are downloaded.")
        text.setWordWrap(True)
        layout.addWidget(text)
        listing = QTreeWidget()
        listing.setRootIsDecorated(False)
        listing.setColumnCount(3)
        listing.setHeaderLabels(["Model", "Status", "Size"])
        listing.setSelectionMode(QAbstractItemView.NoSelection)
        for spec in self.specs:
            item = QTreeWidgetItem([spec.label, STATUS_LABELS.get(models.status(spec), "Missing"),
                                    runtime.human_size(spec.total_size)])
            item.setToolTip(0, f"{spec.id} — {spec.description}")
            listing.addTopLevelItem(item)
        listing.resizeColumnToContents(0)
        layout.addWidget(listing, 1)
        total = sum(spec.total_size for spec in self.specs)
        layout.addWidget(QLabel(f"Total download: {runtime.human_size(total)}"))
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.download_btn = QPushButton("Download now")
        self.download_btn.setDefault(True)
        self.download_btn.clicked.connect(lambda: self._choose("download"))
        self.models_btn = QPushButton("Open Models…")
        self.models_btn.clicked.connect(lambda: self._choose("models"))
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(lambda: self._choose("cancel"))
        for button in (self.download_btn, self.models_btn, self.cancel_btn):
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def _choose(self, choice: str):
        self.choice = choice
        self.accept() if choice != "cancel" else self.reject()


def language_codes() -> list[str]:
    """The fixed list plus codes the user added and languages that already have a choice."""
    codes = [code for code, _name in LANGUAGES]
    stored = config.setting("model_language_codes", [])
    if isinstance(stored, list):
        for code in stored:
            if isinstance(code, str) and _LANGUAGE_CODE.fullmatch(code) and code not in codes:
                codes.append(code)
    choices = config.model_choices()
    languages = choices.get("languages") if isinstance(choices.get("languages"), dict) else {}
    for code in languages:
        if isinstance(code, str) and _LANGUAGE_CODE.fullmatch(code) and code not in codes:
            codes.append(code)
    return codes


def stage_model_combo(stage: str, selected: str | None = None) -> QComboBox:
    """A combo of the selectable models for one stage (NLTK data is not selectable)."""
    combo = QComboBox()
    for spec in models.all_specs():
        if spec.stage != stage or spec.id == "singing-nltk-data":
            continue
        combo.addItem(f"{spec.label} ({spec.id})", spec.id)
    index = combo.findData(selected)
    combo.setCurrentIndex(index if index >= 0 else 0)
    return combo


class PerSongModelsDialog(QDialog):
    """'Process with other models…': one combo per stage and an optional language shortcut."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Process with other models")
        self.setMinimumWidth(640)
        layout = QVBoxLayout(self)
        note = QLabel("These choices apply to this queue only. The .lrc records them in its "
                      "#models tag, so the library can show the song was made with other models.")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.language = QComboBox()
        self.language.addItem("Detect (use the song's language choices)", "")
        for code in language_codes():
            self.language.addItem(f"{code} — {LANGUAGE_NAMES.get(code, 'Other')}", code)
        self.language.currentIndexChanged.connect(self._language_selected)
        form.addRow("Language", self.language)
        self.stage_combos: dict[str, QComboBox] = {}
        for stage in models.STAGES:
            combo = stage_model_combo(stage, config.resolve_model(stage).id)
            self.stage_combos[stage] = combo
            form.addRow(STAGE_TITLES.get(stage, stage), combo)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _language_selected(self, *_args) -> None:
        code = self.language.currentData()
        for stage, combo in self.stage_combos.items():
            try:
                spec = models.resolve(stage, lang=str(code) if code else None)
            except LookupError:
                continue
            index = combo.findData(spec.id)
            if index >= 0:
                combo.setCurrentIndex(index)

    def chosen_models(self) -> dict[str, str]:
        return {stage: str(combo.currentData()) for stage, combo in self.stage_combos.items()
                if combo.currentData()}


class ModelsWindow(QDialog):
    """The model manager.  Non-modal; one window per MainWindow."""

    downloads_finished = Signal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("LyricLoom models")
        self.setMinimumSize(980, 640)
        self._thread: QThread | None = None
        self._worker: ModelTaskWorker | None = None
        self._tasks: list[ModelTask] = []
        self._progress_pct: dict[str, int] = {}
        self._errors: list[str] = []
        self._last_success = False
        self._cancelled_job = False
        self._close_when_finished = False
        self._loading_language = False
        self._items: dict[str, QTreeWidgetItem] = {}
        self._model_tab_buttons: list[QPushButton] = []
        self._language_combos: dict[str, QComboBox] = {}

        layout = QVBoxLayout(self)
        intro = QLabel("Models are downloaded once and kept in the models folder. Every file is "
                       "checked against its pinned size and SHA-256; a dropped download resumes "
                       "where it stopped.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_models_tab(), "Models")
        self.tabs.addTab(self._build_language_tab(), "Language overrides")
        layout.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        footer.addWidget(self.status_label, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setMinimumWidth(260)
        self.progress.hide()
        self.open_btn = QPushButton("Open models folder")
        self.open_btn.clicked.connect(self.open_folder)
        footer.addWidget(self.progress)
        footer.addWidget(self.open_btn)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        footer.addWidget(self.close_btn)
        layout.addLayout(footer)
        self.refresh()

    # ------------------------------------------------------------------ construction
    def _build_models_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Model", "Size", "Status", "Used for", "License"])
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self.use_as_default())
        layout.addWidget(self.tree, 1)

        row1 = QHBoxLayout()
        self.download_btn = QPushButton("Download")
        self.download_btn.clicked.connect(self.download_selected)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_job)
        self.verify_btn = QPushButton("Verify")
        self.verify_btn.clicked.connect(self.verify_selected)
        self.repair_btn = QPushButton("Repair")
        self.repair_btn.clicked.connect(self.repair_selected)
        self.default_btn = QPushButton("Use as default")
        self.default_btn.clicked.connect(self.use_as_default)
        self.language_btn = QPushButton("Use for a language…")
        self.language_btn.clicked.connect(self.use_for_language)
        for button in (self.download_btn, self.cancel_btn, self.verify_btn, self.repair_btn,
                       self.default_btn, self.language_btn):
            row1.addWidget(button)
            self._model_tab_buttons.append(button)
        row1.addStretch(1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.add_btn = QPushButton("Add custom model…")
        self.add_btn.clicked.connect(self.add_custom_model)
        self.remove_btn = QPushButton("Remove custom model")
        self.remove_btn.clicked.connect(self.remove_custom_model)
        row2.addWidget(self.add_btn)
        row2.addWidget(self.remove_btn)
        row2.addStretch(1)
        layout.addLayout(row2)
        return page

    def _build_language_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(
            "A language choice is used when the song's language tag matches it. “(default)” means "
            "the default choice for that stage; changing a box writes the choice immediately.")
        note.setWordWrap(True)
        layout.addWidget(note)
        top = QHBoxLayout()
        top.addWidget(QLabel("Language"))
        self.language_combo = QComboBox()
        self.language_combo.currentIndexChanged.connect(self._load_language_choices)
        top.addWidget(self.language_combo, 1)
        self.add_language_btn = QPushButton("Add language code…")
        self.add_language_btn.clicked.connect(self.add_language_code)
        top.addWidget(self.add_language_btn)
        layout.addLayout(top)

        group = QGroupBox("Model per stage")
        grid = QGridLayout(group)
        for row, stage in enumerate(models.STAGES):
            grid.addWidget(QLabel(STAGE_TITLES.get(stage, stage)), row, 0)
            combo = QComboBox()
            combo.currentIndexChanged.connect(lambda _index, name=stage: self._language_changed(name))
            self._language_combos[stage] = combo
            grid.addWidget(combo, row, 1)
        grid.setColumnStretch(1, 1)
        layout.addWidget(group)
        layout.addStretch(1)
        self._reload_language_codes()
        return page

    # ------------------------------------------------------------------ model rows
    def refresh(self) -> None:
        """Rebuilds the model rows from the catalog and the current custom registrations."""
        selected = self.selected_spec()
        selected_id = selected.id if selected is not None else ""
        self._items.clear()
        self.tree.clear()
        specs = models.all_specs()
        for stage in models.STAGES:
            parent = QTreeWidgetItem([STAGE_TITLES.get(stage, stage), "", "", "", ""])
            parent.setFirstColumnSpanned(True)
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            self.tree.addTopLevelItem(parent)
            stage_specs = [spec for spec in specs if spec.stage == stage]
            stage_specs.sort(key=lambda spec: (not spec.default, spec.label.lower()))
            for spec in stage_specs:
                item = QTreeWidgetItem([spec.label, runtime.human_size(spec.total_size),
                                        self._status_text(spec),
                                        ", ".join(used_for(spec)) or "—",
                                        spec.license])
                item.setData(0, Qt.UserRole, spec.id)
                item.setToolTip(0, f"{spec.id}\n{spec.description}")
                self._style_status(item, spec)
                parent.addChild(item)
                self._items[spec.id] = item
            parent.setExpanded(True)
        self.tree.resizeColumnToContents(0)
        self.tree.resizeColumnToContents(1)
        self.tree.resizeColumnToContents(2)
        if selected_id in self._items:
            self.tree.setCurrentItem(self._items[selected_id])
        self._load_language_choices()
        self._selection_changed()

    def _status_text(self, spec: models.ModelSpec) -> str:
        if spec.id in self._progress_pct:
            return f"Downloading {self._progress_pct[spec.id]}%"
        try:
            state = models.status(spec)
        except Exception as exc:  # noqa: BLE001 - one unreadable model must still show its row
            return f"Error: {type(exc).__name__}"
        return STATUS_LABELS.get(state, state.title())

    def _style_status(self, item: QTreeWidgetItem, spec: models.ModelSpec) -> None:
        text = item.text(2)
        if text.startswith("Downloading"):
            item.setForeground(2, QColor("#2f7f8f"))
        elif text in ("Missing", "Corrupt") or text.startswith("Error"):
            item.setForeground(2, QColor("#c06000"))
        elif text == "Unverified":
            item.setForeground(2, QColor("#777777"))

    def _selection_changed(self) -> None:
        spec = self.selected_spec()
        busy = self._thread is not None
        status = self._status_text(spec) if spec is not None else ""
        downloadable = spec is not None and not spec.custom and status in ("Missing", "Corrupt")
        self.download_btn.setEnabled(downloadable and not busy)
        self.repair_btn.setEnabled(spec is not None and not spec.custom
                                   and status in ("Missing", "Corrupt", "Unverified")
                                   and not busy)
        self.verify_btn.setEnabled(spec is not None and not busy)
        selectable = (spec is not None and spec.id != "singing-nltk-data")
        self.default_btn.setEnabled(selectable and not busy)
        self.language_btn.setEnabled(selectable and not busy)
        self.remove_btn.setEnabled(spec is not None and spec.custom and not busy)
        self.remove_btn.setToolTip("Only forgets the registration; the file is never deleted."
                                   if spec is not None and spec.custom else "")
        if spec is not None:
            self.status_label.setText(
                f"{spec.label} · {spec.id} · {runtime.human_size(spec.total_size)} · {status}")

    def selected_spec(self) -> models.ModelSpec | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        model_id = item.data(0, Qt.UserRole)
        if not model_id:
            return None
        return _find_spec(str(model_id))

    def select_specs(self, specs: list[models.ModelSpec]) -> None:
        for spec in specs:
            item = self._items.get(spec.id)
            if item is not None:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                return

    # ------------------------------------------------------------------ jobs
    def download_selected(self) -> bool:
        spec = self.selected_spec()
        if spec is None:
            return False
        return self.start_download([spec])

    def repair_selected(self) -> bool:
        spec = self.selected_spec()
        if spec is None:
            return False
        return self.start_repair([spec])

    def verify_selected(self) -> bool:
        spec = self.selected_spec()
        if spec is None:
            return False
        return self.start_verify([spec])

    def start_download(self, specs: list[models.ModelSpec]) -> bool:
        tasks = [ModelTask("download", spec) for spec in specs]
        return self.start_tasks(tasks)

    def start_repair(self, specs: list[models.ModelSpec]) -> bool:
        tasks = [ModelTask("repair", spec) for spec in specs]
        return self.start_tasks(tasks)

    def start_verify(self, specs: list[models.ModelSpec]) -> bool:
        tasks = [ModelTask("verify", spec) for spec in specs]
        return self.start_tasks(tasks)

    def start_tasks(self, tasks: list[ModelTask]) -> bool:
        if not tasks:
            return False
        if self._thread is not None:
            self.status_label.setText("A model job is already running; finish or cancel it first.")
            return False
        error = free_space_error(_download_tasks(tasks))
        if error:
            QMessageBox.warning(self, "Models", error)
            return False
        self._tasks = list(tasks)
        self._errors = []
        self._progress_pct.clear()
        self._last_success = False
        self._cancelled_job = False
        self._close_when_finished = False
        self._set_busy(True)
        self.progress.setRange(0, 0)
        self.progress.setFormat("Starting…")
        self.progress.show()
        thread = QThread(self)
        worker = ModelTaskWorker(self._tasks)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.message.connect(self._message, Qt.QueuedConnection)
        worker.progress.connect(self._progress, Qt.QueuedConnection)
        worker.task_done.connect(self._task_done, Qt.QueuedConnection)
        worker.cancelled.connect(self._cancelled, Qt.QueuedConnection)
        worker.finished.connect(self._finished, Qt.QueuedConnection)
        worker.finished.connect(thread.quit)
        thread.finished.connect(self._thread_finished)
        self._thread, self._worker = thread, worker
        thread.start()
        return True

    def cancel_job(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.status_label.setText("Cancelling the download; the partial file is kept for a "
                                      "later resume…")

    def _set_busy(self, busy: bool) -> None:
        self.download_btn.setEnabled(not busy)
        self.repair_btn.setEnabled(not busy)
        self.verify_btn.setEnabled(not busy)
        self.default_btn.setEnabled(not busy)
        self.language_btn.setEnabled(not busy)
        self.add_btn.setEnabled(not busy)
        self.remove_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        self.close_btn.setEnabled(True)   # closing asks before it cancels a running job
        if busy:
            for button in self._model_tab_buttons:
                button.setEnabled(button is self.cancel_btn)
        else:
            self._selection_changed()

    @Slot(str)
    def _message(self, text: str) -> None:
        self.status_label.setText(text)

    @Slot(str, int, int)
    def _progress(self, model_id: str, done: int, total: int) -> None:
        if total:
            pct = min(100, int(done * 100 / total))
            self._progress_pct[model_id] = pct
            self.progress.setRange(0, 1000)
            self.progress.setValue(min(1000, int(done * 1000 / total)))
            self.progress.setFormat(f"Downloading {pct}% — {runtime.human_size(done)} of "
                                    f"{runtime.human_size(total)}")
        else:
            self._progress_pct[model_id] = 0
            self.progress.setRange(0, 0)
            self.progress.setFormat("Downloading…")
        item = self._items.get(model_id)
        if item is not None:
            item.setText(2, f"Downloading {self._progress_pct.get(model_id, 0)}%")

    @Slot(str, bool, str)
    def _task_done(self, model_id: str, ok: bool, message: str) -> None:
        self._progress_pct.pop(model_id, None)
        spec = _find_spec(model_id)
        self._last_success = self._last_success or ok
        if not ok:
            label = spec.label if spec is not None else model_id
            self._errors.append(f"{label}: {message}")
            self.status_label.setText(f"{label}: {message}")
        item = self._items.get(model_id)
        if item is not None and spec is not None:
            item.setText(2, self._status_text(spec))
            self._style_status(item, spec)

    @Slot()
    def _cancelled(self) -> None:
        self._cancelled_job = True
        self.status_label.setText("Download cancelled; the partial file is kept for a later resume.")

    @Slot(bool)
    def _finished(self, ok: bool) -> None:
        self._last_success = ok

    @Slot()
    def _thread_finished(self) -> None:
        ok = self._last_success and not self._cancelled_job and not self._errors
        self._thread = None
        self._worker = None
        self._tasks = []
        self.progress.hide()
        self._progress_pct.clear()
        self._set_busy(False)
        self.refresh()
        if ok:
            self.status_label.setText("All requested models are ready.")
        elif self._errors:
            self.status_label.setText("Some models could not be downloaded.")
            QMessageBox.warning(self, "Models", "\n\n".join(self._errors[:8]))
        self.downloads_finished.emit(ok)
        if self._close_when_finished:
            self._close_when_finished = False
            self.close()

    # ------------------------------------------------------------------ actions
    def use_as_default(self) -> bool:
        spec = self.selected_spec()
        if spec is None:
            return False
        try:
            models.use(spec.stage, spec.id)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Models", f"Could not save the choice:\n{exc}")
            return False
        self.refresh()
        self.status_label.setText(f"{spec.label} is now the default for "
                                  f"{STAGE_TITLES.get(spec.stage, spec.stage)}.")
        return True

    def use_for_language(self) -> bool:
        spec = self.selected_spec()
        if spec is None:
            return False
        lang, ok = QInputDialog.getItem(self, "Use for a language",
                                        f"Use {spec.label} for which language?",
                                        self._language_labels(), 0, False)
        if not ok or not lang:
            return False
        return self.apply_language_choice(spec, self.language_code(lang))

    def apply_language_choice(self, spec: models.ModelSpec, lang: str) -> bool:
        """Writes one language choice (the method the dialog and the tests call)."""
        if not lang:
            return False
        try:
            models.use(spec.stage, spec.id, lang=lang)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Models", f"Could not save the choice:\n{exc}")
            return False
        self.refresh()
        self.status_label.setText(f"{spec.label} is now used for {lang} "
                                  f"({STAGE_TITLES.get(spec.stage, spec.stage)}).")
        return True

    def add_custom_model(self) -> bool:
        dialog = AddCustomModelDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return False
        stage, source, label = dialog.values()
        try:
            spec = models.add(stage, source, label=label or None)
        except Exception as exc:  # noqa: BLE001 - invalid files and network errors are shown
            QMessageBox.warning(self, "Add a custom model", f"Could not add the model:\n{exc}")
            return False
        self.refresh()
        item = self._items.get(spec.id)
        if item is not None:
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)
        self.status_label.setText(f"Added {spec.label}. It is a registration only; the file stays "
                                  f"where it is.")
        return True

    def remove_custom_model(self) -> bool:
        spec = self.selected_spec()
        if spec is None or not spec.custom:
            return False
        answer = QMessageBox.question(
            self, "Remove custom model",
            f"Remove the registration of “{spec.label}”?\n\n"
            "The model file itself is not deleted, and any choice that used it falls back to the "
            "catalog default.")
        if answer != QMessageBox.Yes:
            return False
        try:
            models.remove(spec.id)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Models", f"Could not remove the model:\n{exc}")
            return False
        self.refresh()
        self.status_label.setText("The registration was removed; the file was left in place.")
        return True

    def open_folder(self) -> None:
        folder = config.MODELS
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "Models", f"Could not create the models folder:\n{folder}\n\n"
                                                f"{exc.strerror or exc}")
            return
        if sys.platform == "win32":
            os.startfile(folder)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    # ------------------------------------------------------------------ language overrides
    def _language_labels(self) -> list[str]:
        codes = self._language_codes()
        return [f"{code} — {LANGUAGE_NAMES.get(code, 'Other')}" for code in codes]

    @staticmethod
    def language_code(label: str) -> str:
        return label.split(" — ", 1)[0].strip()

    def _language_codes(self) -> list[str]:
        return language_codes()

    def _reload_language_codes(self) -> None:
        current = self.language_combo.currentData() if self.language_combo.count() else "en"
        self._loading_language = True
        try:
            self.language_combo.clear()
            for code in self._language_codes():
                self.language_combo.addItem(f"{code} — {LANGUAGE_NAMES.get(code, 'Other')}", code)
            index = self.language_combo.findData(current)
            self.language_combo.setCurrentIndex(max(0, index))
        finally:
            self._loading_language = False
        self._load_language_choices()

    def add_language_code(self) -> bool:
        code, ok = QInputDialog.getText(
            self, "Add language code",
            "Language code used in the lyrics tag (for example nl, sv or pt-BR):")
        if not ok:
            return False
        code = code.strip().lower()
        if not _LANGUAGE_CODE.fullmatch(code):
            QMessageBox.warning(self, "Add language code",
                                f"“{code}” is not a language code. Use a short code such as ja, "
                                "pt or pt-BR.")
            return False
        stored = config.setting("model_language_codes", [])
        stored = list(stored) if isinstance(stored, list) else []
        if code not in stored:
            stored.append(code)
            try:
                config.set_setting("model_language_codes", stored)
            except OSError as exc:
                QMessageBox.warning(self, "Add language code",
                                    f"Could not save the language code:\n{exc}")
                return False
        self._reload_language_codes()
        index = self.language_combo.findData(code)
        if index >= 0:
            self.language_combo.setCurrentIndex(index)
        return True

    def _load_language_choices(self, *_args) -> None:
        if self._loading_language:
            return
        lang = self.language_combo.currentData()
        if not lang:
            return
        choices = config.model_choices()
        entry = (choices.get("languages") or {}).get(lang, {}) if isinstance(
            choices.get("languages"), dict) else {}
        specs = models.all_specs()
        self._loading_language = True
        try:
            for stage, combo in self._language_combos.items():
                combo.clear()
                combo.addItem("(default)", None)
                for spec in specs:
                    if spec.stage != stage or spec.id == "singing-nltk-data":
                        continue
                    combo.addItem(f"{spec.label} ({spec.id})", spec.id)
                chosen = entry.get(stage) if isinstance(entry, dict) else None
                index = combo.findData(chosen)
                combo.setCurrentIndex(index if index >= 0 else 0)
                try:
                    default = config.resolve_model(stage, lang=lang)
                    combo.setToolTip("(default) uses: " + default.label)
                except LookupError:
                    pass
        finally:
            self._loading_language = False

    def _language_changed(self, stage: str) -> None:
        if self._loading_language:
            return
        lang = self.language_combo.currentData()
        if not lang:
            return
        model_id = self._language_combos[stage].currentData()
        try:
            if model_id:
                models.use(stage, str(model_id), lang=lang)
            else:
                models.clear(stage, lang=lang)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Language override", f"Could not save the choice:\n{exc}")
            self._load_language_choices()
            return
        self._reload_used_for()

    def _reload_used_for(self) -> None:
        for model_id, item in self._items.items():
            spec = _find_spec(model_id)
            if spec is not None:
                item.setText(3, ", ".join(used_for(spec)) or "—")

    # ------------------------------------------------------------------ closing
    def closeEvent(self, event) -> None:
        if self._thread is not None:
            answer = QMessageBox.question(
                self, "Cancel the download?",
                "A model download is still running. Cancel it and close the window?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self._close_when_finished = True
            self.cancel_job()
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self) -> None:
        # Esc must not hide the window while the worker still runs; the close prompt asks first.
        if self._thread is not None:
            self.close()
            return
        super().reject()
