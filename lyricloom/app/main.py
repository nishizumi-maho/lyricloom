"""LyricLoom desktop app: library list, processing queue, player with lyrics, simple editor."""
from __future__ import annotations

import os
import re
import sys
import threading
import time
import traceback
from dataclasses import replace
from pathlib import Path

import mutagen

from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QProgressBar, QPushButton, QSlider, QSplitter, QTableWidget,
                               QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import cache, config, runner, runtime
from .. import VERSION
from ..lrc import format_ts, parse_lrc
from ..model import LrcDoc, Segment
from ..stages.write import apply_script_preference, japanese_path, write_lyrics
from .dialogs import (ModelsDialog, SettingsDialog, UpdateController, check_for_updates, validate_folder)
from .karaoke import KaraokeWindow
from .model import (STAGE_LABELS, TrackRow, apply_edits, delete_line, delete_word, insert_line, insert_word,
                    load_cached_rows, merge_with_previous, read_status, scan_cached, track_progress)

FILTERS = ["All", "Review", "Pending", "Failed", "Other", "Done"]
STATUS_LABELS = {"cancelled": "Stopped"}
REVIEW_TINT = QColor(255, 196, 0, 70)
_TS = re.compile(r"^(\d+):(\d{1,2})(?:[.:](\d{1,3}))?$")


def parse_ts(text: str) -> int | None:
    m = _TS.match(text.strip())
    if not m:
        return None
    return int(m.group(1)) * 60000 + int(m.group(2)) * 1000 + int((m.group(3) or "0").ljust(3, "0")[:3])


class FuncWorker(QObject):
    """Runs one function off the UI thread."""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    @Slot()
    def run(self):
        try:
            self.done.emit(self._fn())
        except Exception as exc:  # noqa: BLE001 - reported in the window, never wedges the thread
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class QueueWorker(QObject):
    """Processes tracks one at a time.

    stop() stops after the current track; stop(now=True) sets the cancellation event that reaches
    the running worker process. pause() stops before the next track (a subprocess cannot pause).
    """
    track_started = Signal(str)
    stage = Signal(str)
    track_done = Signal(object)
    device = Signal(object)   # the finished TrackResult: where the vocals were separated
    queue_error = Signal(str)
    finished = Signal()

    def __init__(self, paths: list[Path], force: bool, redo: bool = False):
        super().__init__()
        self._paths, self._force, self._redo = paths, force, redo
        self._stop_after = False
        self._cancel = threading.Event()
        self._pause = threading.Event()

    def stop(self, now: bool = False):
        if now:
            self._cancel.set()
        else:
            self._stop_after = True

    def pause(self):
        self._pause.set()

    def resume(self):
        self._pause.clear()

    def is_paused(self) -> bool:
        return self._pause.is_set()

    @Slot()
    def run(self):
        try:
            self._run_tracks()
        except Exception as exc:  # noqa: BLE001 - the window must always get `finished`
            self.queue_error.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()

    def _run_tracks(self):
        for p in self._paths:
            while self._pause.is_set() and not self._cancel.is_set() and not self._stop_after:
                time.sleep(0.05)
            if self._cancel.is_set() or self._stop_after:
                break
            self.track_started.emit(str(p))
            moved: dict[Path, Path] = {}
            try:
                if self._redo:
                    # word timing moved aside and aligned again; lyrics, separation and
                    # transcription come from the cache when the song was done on this machine
                    moved = runner.forget_sync(p)
                    res = runner.process(p, force=True, only_stage="align",
                                         on_stage=self.stage.emit, cancel=self._cancel)
                    if res.status in ("failed", "cancelled"):
                        runner.restore_sync(moved)
                    else:
                        runner.drop_sync_backup(moved)
                else:
                    res = runner.process(p, force=self._force, on_stage=self.stage.emit,
                                         cancel=self._cancel)
                row = read_status(p)
                if res.status == "failed":
                    row.status, row.error = "failed", res.error
                elif res.status == "cancelled":
                    row.status, row.error = "cancelled", res.error or "Stopped by the user"
                self.device.emit(res)
                self.track_done.emit(row)
                if res.status == "cancelled":
                    break
            except Exception as exc:  # noqa: BLE001 - one bad track must not stop the queue
                if moved:
                    runner.restore_sync(moved)
                message = f"{p.name}: {type(exc).__name__}: {exc}"
                runner._log(p, "queue error\n" + traceback.format_exc())
                self.queue_error.emit(message)
                try:
                    row = read_status(p)
                except Exception:
                    row = TrackRow(p, "", p.stem, "failed")
                row.status, row.error = "failed", message
                self.track_done.emit(row)


class MainWindow(QMainWindow):
    def __init__(self, root: Path = None):
        super().__init__()
        self.root = Path(root or config.library_root())
        self.rows: list[TrackRow] = []
        self.audio: Path | None = None
        self.doc: LrcDoc | None = None
        self.dirty = False
        self._threads: list[tuple[QThread, QObject]] = []
        self._queue: QueueWorker | None = None
        self._queue_error = ""
        self._quit_after_queue = False
        self._pending_installer: Path | None = None
        self._cancel_background = threading.Event()
        self._stop_at: int | None = None
        self._shown_line = -1
        self.karaoke_window: KaraokeWindow | None = None
        self._update_controller = UpdateController(self)
        self.setWindowTitle(config.APP_NAME)
        self.resize(1400, 850)
        self._build()
        self._build_menu()
        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        self.player.durationChanged.connect(lambda d: self.seek.setRange(0, d))
        self.timer = QTimer(self, interval=50, timeout=self._tick)
        self.timer.start()
        self.refresh()
        QTimer.singleShot(0, self._first_run)
        if config.setting("check_updates", True) and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            QTimer.singleShot(4000, lambda: check_for_updates(self, silent=True))

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("&File")
        act_library = QAction("Change &library…", self, triggered=self.choose_library)
        act_settings = QAction("&Settings…", self, triggered=self.open_settings)
        act_quit = QAction("E&xit", self, shortcut=QKeySequence.Quit, triggered=self.close)
        file_menu.addAction(act_library)
        file_menu.addAction(act_settings)
        file_menu.addSeparator()
        file_menu.addAction(act_quit)
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(QAction("&Download models…", self, triggered=self.open_models))
        help_menu.addAction(QAction("Check for &updates…", self, triggered=lambda: check_for_updates(self)))
        help_menu.addAction(QAction("Open &data folder", self, triggered=self.open_data_folder))
        help_menu.addSeparator()
        help_menu.addAction(QAction("&About LyricLoom", self, triggered=self.show_about))

    def _first_run(self):
        if config.setting("library") or self.root != Path(config.DEFAULT_LIBRARY):
            return
        QMessageBox.information(
            self, "Welcome to LyricLoom",
            "Choose the folder that contains your music. LyricLoom scans its subfolders and writes "
            "the .lrc next to each audio file.\n\n"
            "The first song also downloads the vocal separator (about 0.9 GB). You can manage all "
            "models later in Help > Download models.")
        self.choose_library()
        QTimer.singleShot(200, self._offer_models)

    def _offer_models(self):
        missing = runtime.status()
        if all(missing.values()) and runtime._nltk_ready():
            return
        answer = QMessageBox.question(
            self, "Download models?",
            "LyricLoom needs about 5.3 GB of models for the full pipeline:\n\n"
            "  Whisper large-v3 (3.1 GB), vocal separator (0.9 GB),\n"
            "  MMS forced alignment (1.2 GB), English singing model (66 MB).\n\n"
            "Download them now? You can also do this later from Help > Download models; "
            "songs that need a missing model will ask again.")
        if answer == QMessageBox.Yes:
            self.open_models()

    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec() == dialog.Accepted:
            self.root = config.library_root()
            self.rows = []
            self.script.blockSignals(True)
            self.script.setCurrentIndex(1 if config.japanese_script() == "romaji" else 0)
            self.script.blockSignals(False)
            self.refresh()
            self.statusBar().showMessage("Settings saved. Restart LyricLoom to apply cache/GPU changes.", 8000)

    def open_models(self):
        ModelsDialog(self).exec()

    def open_data_folder(self):
        config.APP_DATA.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            import os
            os.startfile(config.APP_DATA)  # type: ignore[attr-defined]
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(config.APP_DATA)])

    def show_about(self):
        QMessageBox.about(
            self, f"About {config.APP_NAME}",
            f"<b>{config.APP_NAME} {VERSION}</b><br><br>"
            "Word-by-word synced lyrics from official lyrics, aligned against isolated vocals.<br><br>"
            "Free software under the GNU GPL v3 or later.<br>"
            f"<a href='https://github.com/nishizumi-maho/lyricloom'>github.com/nishizumi-maho/lyricloom</a>")

    # ---------- layout ----------
    def _build(self):
        left = QWidget()
        lv = QVBoxLayout(left)
        lib = QHBoxLayout()
        self.root_label = QLabel()
        self.btn_library = QPushButton("Library…")
        self.btn_settings = QPushButton("Settings…")
        self.btn_key = QPushButton("AssemblyAI key…")
        lib.addWidget(self.root_label, 1)
        lib.addWidget(self.btn_library)
        lib.addWidget(self.btn_settings)
        lib.addWidget(self.btn_key)
        self.script = QComboBox()
        self.script.addItems(["Japanese: 日本語", "Japanese: romaji"])
        self.script.setCurrentIndex(1 if config.japanese_script() == "romaji" else 0)
        self.script.setToolTip("Script of Japanese lyrics in the .lrc MusicBee plays.\n"
                               "Both are always kept as <song>.japanese.lrc and <song>.romaji.lrc.")
        self.script.currentIndexChanged.connect(lambda i: self.set_script("romaji" if i else "japanese"))
        lib.addWidget(self.script)
        lv.addLayout(lib)
        top = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItems(FILTERS)
        self.search = QLineEdit(placeholderText="Search artist / title")
        top.addWidget(self.filter)
        top.addWidget(self.search)
        lv.addLayout(top)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Artist", "Title", "Status", "Source", "Conf"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        lv.addWidget(self.table)
        btns = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_sel = QPushButton("Process selected")
        self.btn_pending = QPushButton("Process pending")
        self.btn_redo = QPushButton("Redo selected")
        self.btn_redo.setToolTip("Delete the word timing of the selected songs and align them again")
        self.btn_stop = QPushButton("Stop after this song", enabled=False)
        self.btn_stop.setToolTip("Let the current song finish, then stop the queue")
        self.btn_stop_now = QPushButton("Stop now", enabled=False)
        self.btn_stop_now.setToolTip("Kill the running worker and stop the queue immediately")
        self.btn_pause = QPushButton("Pause after this song", enabled=False)
        self.btn_pause.setToolTip("Stop before the next song; the current song finishes")
        self.force = QCheckBox("Force")
        for w in (self.btn_refresh, self.btn_sel, self.btn_pending, self.btn_redo,
                  self.btn_stop, self.btn_stop_now, self.btn_pause, self.force):
            btns.addWidget(w)
        lv.addLayout(btns)

        right = QWidget()
        rv = QVBoxLayout(right)
        self.track_label = QLabel("No track selected")
        self.track_label.setFont(QFont(self.font().family(), 12, QFont.Bold))
        rv.addWidget(self.track_label)
        pl = QHBoxLayout()
        self.btn_play = QPushButton("Play")
        self.seek = QSlider(Qt.Horizontal)
        self.time_label = QLabel("00:00.00")
        self.vocals = QCheckBox("Vocals only")
        self.btn_karaoke = QPushButton("Karaoke")
        self.btn_karaoke.setToolTip("Open the full-screen karaoke player for the selected track")
        for w in (self.btn_play, self.seek, self.time_label, self.vocals, self.btn_karaoke):
            pl.addWidget(w)
        rv.addLayout(pl)
        self.now = QLabel("")
        self.now.setTextFormat(Qt.RichText)
        self.now.setWordWrap(True)
        self.now.setFont(QFont(self.font().family(), 18))
        self.now.setMinimumHeight(60)
        rv.addWidget(self.now)
        self.lines = QListWidget()
        rv.addWidget(self.lines, 3)
        self.words = QTableWidget(0, 3)
        self.words.setHorizontalHeaderLabels(["Word", "Start", "End"])
        self.words.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.words.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        rv.addWidget(self.words, 2)
        ed = QHBoxLayout()
        self.nudges = []
        for d in (-50, -10, 10, 50):
            b = QPushButton(f"{d:+d} ms")
            b.setToolTip("Moves the selected word's start (hold Shift: its end)")
            b.clicked.connect(lambda _=False, d=d: self.nudge(d))
            ed.addWidget(b)
            self.nudges.append(b)
        self.btn_line = QPushButton("Play line")
        self.btn_delete = QPushButton("Delete line")
        self.btn_paste = QPushButton("Paste lyrics…")
        self.btn_save = QPushButton("Save")
        for w in (self.btn_line, self.btn_delete, self.btn_paste, self.btn_save):
            ed.addWidget(w)
        rv.addLayout(ed)
        ed2 = QHBoxLayout()
        self.btn_add_word = QPushButton("Add word…")
        self.btn_del_word = QPushButton("Delete word")
        self.btn_add_line = QPushButton("Insert line…")
        self.btn_merge = QPushButton("Merge with line above")
        for w in (self.btn_add_word, self.btn_del_word, self.btn_add_line, self.btn_merge):
            ed2.addWidget(w)
        rv.addLayout(ed2)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([620, 780])
        self.setCentralWidget(split)

        self.filter.currentIndexChanged.connect(self._fill_table)
        self.search.textChanged.connect(self._fill_table)
        self.table.itemSelectionChanged.connect(self._on_track_selected)
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_library.clicked.connect(self.choose_library)
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_key.clicked.connect(self.set_api_key)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setMinimumWidth(420)
        self.progress.setStyleSheet("QProgressBar { text-align: center; }"
                                    "QProgressBar::chunk { background-color: #2e9d4f; }")
        self.progress.hide()
        self.gpu = QLabel(self._device_text(""))
        self._gpu_tip = ("Where the heavy stages run. Separation and forced alignment can use a GPU "
                         "through ROCm inside WSL on Windows, or CUDA/ROCm on Linux; otherwise they "
                         "fall back to the CPU. Transcription uses whisper.cpp. "
                         "Updated as songs are processed.")
        self.gpu.setToolTip(self._gpu_tip)
        self.statusBar().addPermanentWidget(self.gpu)
        self.statusBar().addPermanentWidget(self.progress)
        self._prog = None
        self.prog_timer = QTimer(self, interval=250, timeout=self._update_progress)
        self.btn_sel.clicked.connect(lambda: self.process([r.path for r in self._selected_rows()]))
        self.btn_pending.clicked.connect(
            lambda: self.process([r.path for r in self.rows if r.status in ("pending", "cancelled")]))
        self.btn_redo.clicked.connect(self.redo_selected)
        self.btn_stop.clicked.connect(self._stop_queue)
        self.btn_stop_now.clicked.connect(self._stop_now)
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_play.clicked.connect(self.toggle_play)
        self.seek.sliderMoved.connect(lambda v: self.player.setPosition(v))
        self.vocals.toggled.connect(self._set_source)
        self.btn_karaoke.clicked.connect(self.open_karaoke)
        self.lines.currentRowChanged.connect(self._fill_words)
        self.lines.itemDoubleClicked.connect(self._seek_to_line)
        self.words.itemChanged.connect(self._word_edited)
        self.btn_line.clicked.connect(self.play_line)
        self.btn_delete.clicked.connect(self.delete_current_line)
        # lambdas: clicked passes a bool that would otherwise land in the optional text argument
        self.btn_add_word.clicked.connect(lambda: self.add_word())
        self.btn_del_word.clicked.connect(self.delete_current_word)
        self.btn_add_line.clicked.connect(lambda: self.add_line())
        self.btn_merge.clicked.connect(self.merge_current_line)
        self.btn_paste.clicked.connect(self.paste_lyrics)
        self.btn_save.clicked.connect(self.save)

    # ---------- threads ----------
    def _run(self, worker: QObject, on_done=None, on_failed=None):
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        if on_done is not None:
            worker.done.connect(on_done)
            worker.done.connect(thread.quit)
        else:
            worker.finished.connect(thread.quit)
        if hasattr(worker, "failed"):
            if on_failed is not None:
                worker.failed.connect(on_failed)
            worker.failed.connect(thread.quit)
        thread.finished.connect(lambda: self._threads.remove((thread, worker)) if (thread, worker) in self._threads else None)
        self._threads.append((thread, worker))
        thread.start()

    # ---------- library ----------
    def refresh(self):
        """Shows the last scan of this library at once, then updates it in the background, re-reading
        only tracks whose audio or .lrc changed."""
        self.root_label.setText(str(self.root))
        root = self.root
        if not self.rows:
            self.rows = load_cached_rows(root)
            self._fill_table()
        self.statusBar().showMessage(f"Checking {root} for changes …")

        def scan():
            stats: dict = {}
            return root, scan_cached(root, stats), stats

        self._run(FuncWorker(scan), self._scanned, self._scan_failed)

    def _scanned(self, result):
        root, rows, stats = result
        if root != self.root:   # the library was switched while this scan ran
            return
        self.rows = rows
        self._fill_table()
        message = f"{len(rows)} track" + ("" if len(rows) == 1 else "s")
        unreadable = int(stats.get("unreadable", 0))
        if unreadable:
            message += f" · {unreadable} file(s) could not be read (see the row tooltips)"
        self.statusBar().showMessage(message, 8000 if unreadable else 5000)

    def _scan_failed(self, message: str):
        self.statusBar().showMessage("Scan failed: " + message + " — the previous list was kept", 12000)

    def set_api_key(self):
        state = "a key is set" if config.ASSEMBLYAI_ENABLED else "no key set: AssemblyAI is off"
        key, ok = QInputDialog.getText(
            self, "AssemblyAI key", f"Currently {state}.\nPaste a new key (leave empty to remove it):",
            QLineEdit.Password)
        if not ok:
            return
        try:
            config.set_assemblyai_key(key)
        except OSError as exc:
            self._show_io_error("Save the AssemblyAI key", config.ASSEMBLYAI_KEY_FILE, exc)
            return
        self.statusBar().showMessage("AssemblyAI key saved" if key.strip() else "AssemblyAI key removed: off", 5000)

    def set_script(self, script: str):
        try:
            config.set_japanese_script(script)
            n = apply_script_preference(self.root)
        except OSError as exc:
            self._show_io_error("Update the Japanese script", self.root, exc)
            return
        self.statusBar().showMessage(f"Japanese lyrics now in {script}: {n} song(s) updated", 6000)

    def choose_library(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose the music library", str(self.root))
        if not folder or Path(folder) == self.root or not self._confirm_discard():
            return
        path, error = validate_folder("Music library", folder, must_exist=True)
        if error:
            QMessageBox.warning(self, "Music library", error)
            return
        self.root = path
        try:
            config.set_library_root(self.root)   # the command line uses the same library
        except OSError as exc:
            self._show_io_error("Save the library setting", config.SETTINGS_FILE, exc)
            return
        self.rows = []
        self.refresh()

    def _show_io_error(self, action: str, path: Path, exc: OSError) -> None:
        reason = exc.strerror or str(exc)
        message = f"{action} failed:\n{path}\n\n{reason}"
        self.statusBar().showMessage(f"{action} failed: {reason}", 12000)
        QMessageBox.critical(self, action, message)

    def _visible_rows(self) -> list[TrackRow]:
        f = FILTERS[self.filter.currentIndex()].lower()
        q = self.search.text().lower()
        return [r for r in self.rows if (f == "all" or r.status == f) and (q in r.artist.lower() or q in r.title.lower())]

    def _fill_table(self):
        rows = self._visible_rows()
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, v in enumerate([r.artist, r.title, STATUS_LABELS.get(r.status, r.status),
                                   r.source, f"{r.conf:.2f}" if r.source else ""]):
                item = QTableWidgetItem(v)
                item.setData(Qt.UserRole, str(r.path))
                if r.status == "review":
                    item.setBackground(REVIEW_TINT)
                if r.error:
                    item.setToolTip(r.error)
                self.table.setItem(i, j, item)

    def _selected_rows(self) -> list[TrackRow]:
        paths = {self.table.item(i.row(), 0).data(Qt.UserRole) for i in self.table.selectionModel().selectedRows()}
        return [r for r in self.rows if str(r.path) in paths]

    def _update_row(self, row: TrackRow):
        self.rows = [row if r.path == row.path else r for r in self.rows]
        self._fill_table()

    # ---------- processing ----------
    def redo_selected(self):
        paths = [r.path for r in self._selected_rows()]
        if not paths or self._queue is not None:
            return
        names = "\n".join(f"  {p.stem}" for p in paths[:8]) + ("\n  …" if len(paths) > 8 else "")
        answer = QMessageBox.question(
            self, "Redo word timing",
            f"Delete the word timing of {len(paths)} song(s) and align them again?\n\n{names}\n\n"
            "The official lyric (.original.lrc) is kept.")
        if answer == QMessageBox.Yes:
            self.process(paths, redo=True)

    def _ask_open_track(self) -> str:
        box = QMessageBox(self)
        box.setWindowTitle("Unsaved edits")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"{self.audio.stem} is open with unsaved edits and is in this queue.")
        box.setInformativeText("Saving first keeps your edits; discarding lets the queue replace them. "
                               "Skipping leaves the track out of this run.")
        save = box.addButton("Save", QMessageBox.AcceptRole)
        discard = box.addButton("Discard edits", QMessageBox.DestructiveRole)
        skip = box.addButton("Skip this track", QMessageBox.ActionRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save:
            return "save"
        if clicked is discard:
            return "discard"
        if clicked is skip:
            return "skip"
        return "cancel"

    def _confirm_open_track(self, paths: list[Path], redo: bool) -> list[Path] | None:
        """The open track is in this queue and has unsaved edits: save, discard or skip it.
        Returns the paths to process, or None to cancel."""
        if not (self.dirty and self.audio is not None and self.audio in paths):
            return paths
        choice = self._ask_open_track()
        if choice == "save":
            if not self.save():
                return None
        elif choice == "discard":
            self._set_dirty(False)
        elif choice == "skip":
            paths = [p for p in paths if p != self.audio]
            if not paths:
                self.statusBar().showMessage("No tracks left to process", 5000)
                return None
        else:
            return None
        if redo and self.audio in paths:
            self.statusBar().showMessage("Redo will replace this track's word timing", 5000)
        return paths

    def _validate_folders(self) -> bool:
        checks = (
            ("Music library", str(self.root), True, False),
            ("Vocals cache", str(config.vocals_root()), False, True),
            ("Work cache", str(config.WORK_ROOT), False, True),
        )
        for field, value, must_exist, create in checks:
            _path, error = validate_folder(field, value, must_exist=must_exist, create=create)
            if error:
                QMessageBox.warning(self, field, error)
                return False
        return True

    def process(self, paths: list[Path], redo: bool = False):
        if not paths or self._queue is not None:
            return
        paths = self._confirm_open_track(paths, redo)
        if not paths:
            return
        if not self._validate_folders():
            return
        self._queue_error = ""
        self._queue = QueueWorker(paths, self.force.isChecked(), redo)
        self._prog = {"done": 0, "total": len(paths), "name": "", "stage": "lyrics",
                      "since": time.monotonic(), "dur": 240.0}
        q = self._queue
        q.track_started.connect(self._track_started)
        q.stage.connect(self._stage_changed)
        q.device.connect(self._device_changed)
        q.track_done.connect(self._track_finished)
        q.queue_error.connect(self._queue_error_received)
        q.finished.connect(self._queue_finished)
        self.btn_stop.setEnabled(True)
        self.btn_stop_now.setEnabled(True)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("Pause after this song")
        self.progress.setValue(0)
        self.progress.show()
        self.prog_timer.start()
        self._run(q)

    def _track_started(self, path: str):
        p = Path(path)
        try:
            dur = float(mutagen.File(path).info.length)
        except Exception:  # noqa: BLE001 - only used for the estimate
            dur = 240.0
        self._prog.update(name=p.name, stage="lyrics", since=time.monotonic(), dur=dur)
        row = next((r for r in self.rows if r.path == p), None)
        if row is not None:
            self._update_row(replace(row, status="processing"))

    def _stage_changed(self, stage: str):
        self._prog.update(stage=stage, since=time.monotonic())

    @staticmethod
    def _device_text(device: str) -> str:
        if device == "rocm":
            return f"Device: ROCm (WSL {config.SEPARATOR_WSL_DISTRO})"
        if device == "cuda":
            return "Device: CUDA"
        if device == "cpu":
            return "Device: CPU (fallback)"
        if device == "kept":
            return "Device: vocals already cached"
        return (f"Device: ROCm (WSL {config.SEPARATOR_WSL_DISTRO})"
                if config.SEPARATOR_WSL_ENABLED else "Device: CPU")

    def _device_changed(self, res):
        """Shows where the last song was separated, so a silent CPU fallback is visible."""
        if not res.device:
            return
        self.gpu.setText(self._device_text(res.device))
        failed = bool(res.fallback)
        self.gpu.setStyleSheet("color: #c06000;" if failed or res.device == "cpu" else "")
        self.gpu.setToolTip(
            ("Separation in WSL/ROCm failed and ran on the CPU instead:\n" + res.fallback[-1500:])
            if failed else self._gpu_tip)

    def _track_finished(self, row: TrackRow):
        self._prog["done"] += 1
        self._prog["since"] = time.monotonic()
        self._update_row(row)
        self._reload_if_current(row.path)

    def _update_progress(self):
        p = self._prog
        if not p:
            return
        inside = track_progress(p["stage"], time.monotonic() - p["since"], p["dur"])
        frac = min(1.0, (p["done"] + inside) / p["total"])
        self.progress.setValue(int(frac * 1000))
        n = min(p["done"] + 1, p["total"])
        self.progress.setFormat(f"{frac:.0%} · {n}/{p['total']} · {p['name']} · {STAGE_LABELS.get(p['stage'], p['stage'])}")

    def _stop_queue(self):
        if self._queue:
            self._queue.stop()
            self.statusBar().showMessage("Stopping after the current track …")

    def _stop_now(self):
        if self._queue:
            self._queue.stop(now=True)
            self.statusBar().showMessage("Stopping now …")

    def _toggle_pause(self):
        if not self._queue:
            return
        if self._queue.is_paused():
            self._queue.resume()
            self.btn_pause.setText("Pause after this song")
            self.statusBar().showMessage("Queue resumed", 5000)
        else:
            self._queue.pause()
            self.btn_pause.setText("Resume")
            self.statusBar().showMessage("Pausing after the current track …")

    def _queue_error_received(self, message: str):
        self._queue_error = message
        self.statusBar().showMessage("Queue error: " + message, 12000)

    def _queue_finished(self):
        cancelled = bool(self._prog and self._prog.get("done", 0) < self._prog.get("total", 0))
        self._queue = None
        self._prog = None
        self.prog_timer.stop()
        self.progress.hide()
        self.btn_stop.setEnabled(False)
        self.btn_stop_now.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("Pause after this song")
        if self._queue_error:
            self.statusBar().showMessage("Queue finished with an error: " + self._queue_error, 12000)
            QMessageBox.warning(self, "Queue error", self._queue_error)
            self._queue_error = ""
        elif cancelled:
            self.statusBar().showMessage("Queue stopped", 6000)
        else:
            self.statusBar().showMessage("Queue finished", 5000)
        if self._pending_installer is not None:
            QTimer.singleShot(0, self._install_pending_update)
        elif self._quit_after_queue:
            self._quit_after_queue = False
            QTimer.singleShot(0, self.close)

    # ---------- track / player ----------
    def _on_track_selected(self):
        rows = self._selected_rows()
        if len(rows) != 1 or rows[0].path == self.audio:
            return
        if not self._confirm_discard():
            return
        self.load(rows[0].path)

    def load(self, audio: Path):
        self.audio = audio
        self.player.stop()
        self._set_source()
        self.track_label.setText(f"{audio.parent.parent.name} — {audio.stem}")
        self._reload_lrc()

    def _reload_if_current(self, path: Path):
        if path == self.audio and not self.dirty:
            self._reload_lrc()

    def _reload_lrc(self):
        # Japanese songs are edited in Japanese script; saving rebuilds the romaji version from it.
        lrc = japanese_path(self.audio) if japanese_path(self.audio).exists() else self.audio.with_suffix(".lrc")
        self.doc = parse_lrc(lrc.read_text(encoding="utf-8")) if lrc.exists() else None
        self._set_dirty(False)
        self._fill_lines()

    def _set_source(self):
        if not self.audio:
            return
        pos = self.player.position()
        src = self.audio
        if self.vocals.isChecked():
            v = cache.work_dir(self.audio) / "vocals.wav"
            src = v if v.exists() else self.audio
        self.player.setSource(QUrl.fromLocalFile(str(src)))
        self.player.setPosition(pos)

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self._stop_at = None
            self.player.play()

    def _tick(self):
        t = self.player.position()
        self.btn_play.setText("Pause" if self.player.playbackState() == QMediaPlayer.PlayingState else "Play")
        if not self.seek.isSliderDown():
            self.seek.setValue(t)
        self.time_label.setText(format_ts(t))
        if self._stop_at is not None and t >= self._stop_at:
            self.player.pause()
            self._stop_at = None
        if not self.doc:
            return
        idx = max((i for i, l in enumerate(self.doc.lines) if l.start_ms is not None and l.start_ms <= t), default=-1)
        if idx != self._shown_line and self.player.playbackState() == QMediaPlayer.PlayingState:
            self._shown_line = idx
            if idx >= 0 and not self.words.hasFocus():
                self.lines.setCurrentRow(idx)
        if idx >= 0:
            line = self.doc.lines[idx]
            sung = "".join(s.text for s in line.segments if s.start_ms is not None and s.start_ms <= t)
            rest = line.text[len(sung):]
            esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;")
            self.now.setText(f"<b style='color:#2bb8c4'>{esc(sung)}</b>{esc(rest)}")

    def _seek_to_line(self, item: QListWidgetItem):
        line = self.doc.lines[self.lines.row(item)]
        if line.start_ms is not None:
            self.player.setPosition(line.start_ms)
            self.player.play()

    def play_line(self):
        i = self.lines.currentRow()
        if not self.doc or i < 0:
            return
        line = self.doc.lines[i]
        ends = [s.end_ms for s in line.segments if s.end_ms is not None]
        nxt = self.doc.lines[i + 1].start_ms if i + 1 < len(self.doc.lines) else None
        self._stop_at = (ends[-1] if ends else nxt) or None
        self.player.setPosition(line.start_ms or 0)
        self.player.play()

    # ---------- karaoke ----------
    def open_karaoke(self):
        rows = self._selected_rows()
        audio = rows[0].path if rows else self.audio
        if audio is None:
            QMessageBox.information(self, "Karaoke", "Select a track first.")
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        lyrics = japanese_path(audio)
        if not lyrics.exists():
            lyrics = audio.with_suffix(".lrc")
        row = rows[0] if rows else None
        name = " — ".join(x for x in (row.artist, row.title) if x) if row is not None else None
        if self.karaoke_window is not None:
            self.karaoke_window.close()
        self.karaoke_window = KaraokeWindow(audio, lyrics, display_name=name or None)
        self.karaoke_window.show()

    # ---------- lyrics / editor ----------
    def _fill_lines(self):
        self.lines.blockSignals(True)
        self.lines.clear()
        review = set()
        if self.doc:
            review = {int(x) for x in self.doc.meta.get("#review", "").split(",") if x.strip().isdigit()}
            for i, l in enumerate(self.doc.lines):
                item = QListWidgetItem(f"{format_ts(l.start_ms or 0)}   {l.text}")
                if i in review:
                    item.setBackground(REVIEW_TINT)
                self.lines.addItem(item)
        self.lines.blockSignals(False)
        self._shown_line = -1
        self._fill_words(self.lines.currentRow())

    def _fill_words(self, i: int):
        self.words.blockSignals(True)
        self.words.setRowCount(0)
        if self.doc and 0 <= i < len(self.doc.lines):
            segs = self.doc.lines[i].segments
            self.words.setRowCount(len(segs))
            for r, s in enumerate(segs):
                self.words.setItem(r, 0, QTableWidgetItem(s.text))
                self.words.setItem(r, 1, QTableWidgetItem("" if s.start_ms is None else format_ts(s.start_ms)))
                self.words.setItem(r, 2, QTableWidgetItem("" if s.end_ms is None else format_ts(s.end_ms)))
        self.words.blockSignals(False)

    def _segments_from_table(self) -> list[Segment] | None:
        segs = []
        for r in range(self.words.rowCount()):
            start, end = parse_ts(self.words.item(r, 1).text()), parse_ts(self.words.item(r, 2).text())
            if start is None or end is None:
                return None
            segs.append(Segment(self.words.item(r, 0).text(), start, end))
        return segs

    def _apply(self, segs: list[Segment]):
        i = self.lines.currentRow()
        total = self.player.duration() or max((s.end_ms or 0) for l in self.doc.lines for s in l.segments) + 1000
        self.doc = apply_edits(self.doc, i, segs, total)
        self._set_dirty(True)
        row = self.words.currentRow()
        self._fill_lines()
        self.lines.setCurrentRow(i)
        self.words.selectRow(row)

    def _word_edited(self, _item):
        segs = self._segments_from_table()
        if segs is None:
            self.statusBar().showMessage("Times must look like mm:ss.xx", 4000)
            self._fill_words(self.lines.currentRow())
            return
        self._apply(segs)

    def nudge(self, delta: int):
        r = self.words.currentRow()
        segs = self._segments_from_table()
        if r < 0 or not segs:
            return
        if QApplication.keyboardModifiers() & Qt.ShiftModifier:
            segs[r].end_ms = max(segs[r].start_ms, segs[r].end_ms + delta)
        else:
            segs[r].start_ms = max(0, segs[r].start_ms + delta)
        self._apply(segs)

    def _total(self) -> int:
        ends = [s.end_ms or 0 for l in self.doc.lines for s in l.segments] if self.doc else []
        return self.player.duration() or (max(ends, default=0) + 5000)

    def _after_edit(self, line: int, word: int = -1):
        self._set_dirty(True)
        self._fill_lines()
        self.lines.setCurrentRow(min(line, self.lines.count() - 1))
        if word >= 0:
            self.words.selectRow(min(word, self.words.rowCount() - 1))

    def add_word(self, text: str | None = None):
        i = self.lines.currentRow()
        if not self.doc or i < 0:
            return
        if text is None:
            text, ok = QInputDialog.getText(self, "Add word", "Word (added after the selected one):")
            if not ok or not text.strip():
                return
        after = self.words.currentRow()
        self.doc = insert_word(self.doc, i, after, text, self._total())
        self._after_edit(i, after + 1)

    def delete_current_word(self):
        i, r = self.lines.currentRow(), self.words.currentRow()
        if not self.doc or i < 0 or r < 0:
            return
        self.doc = delete_word(self.doc, i, r)
        self._after_edit(i, r)

    def add_line(self, text: str | None = None):
        if not self.doc:
            self.doc = LrcDoc({}, [])
        after = self.lines.currentRow() if self.doc.lines else -1
        if text is None:
            text, ok = QInputDialog.getText(self, "Insert line", "Text of the new line (inserted after the selected one):")
            if not ok or not text.strip():
                return
        prev = self.doc.lines[after] if after >= 0 else None
        prev_end = max([s.end_ms or 0 for s in prev.segments] + [prev.start_ms or 0]) if prev else 0
        nxt = self.doc.lines[after + 1].start_ms if after + 1 < len(self.doc.lines) else None
        pos = self.player.position()
        start = pos if prev_end <= pos < (nxt or 10 ** 9) else prev_end + 100
        end = (nxt - 100) if nxt and nxt - 100 > start + 200 else start + 2000
        self.doc = insert_line(self.doc, after, text, start, end, self._total())
        self._after_edit(after + 1, 0)

    def merge_current_line(self):
        i = self.lines.currentRow()
        if not self.doc or i <= 0:
            return
        self.doc = merge_with_previous(self.doc, i)
        self._after_edit(i - 1)

    def delete_current_line(self):
        i = self.lines.currentRow()
        if not self.doc or i < 0:
            return
        self.doc = delete_line(self.doc, i)
        self._set_dirty(True)
        self._fill_lines()
        self.lines.setCurrentRow(min(i, self.lines.count() - 1))

    def paste_lyrics(self):
        if not self.audio:
            return
        text, ok = QInputDialog.getMultiLineText(self, "Paste lyrics", "One line per lyric line:")
        if not ok or not text.strip():
            return
        if not self._confirm_discard():
            return
        audio = self.audio
        self._cancel_background.clear()
        self.statusBar().showMessage("Aligning the pasted lyrics …")
        self._run(FuncWorker(lambda: runner.realign(audio, text, cancel=self._cancel_background)), self._realigned)

    def _realigned(self, res):
        if res.status == "cancelled":
            self.statusBar().showMessage("Realign stopped", 5000)
            return
        if res.status == "failed":
            QMessageBox.warning(self, "Realign failed", res.error)
            return
        self._update_row(read_status(res.path))
        if res.path == self.audio:
            self._reload_lrc()
        self.statusBar().showMessage(f"Aligned: {res.status}, confidence {res.conf:.2f}", 6000)

    def save(self) -> bool:
        if not (self.audio and self.doc and self.dirty):
            return True
        try:
            write_lyrics(self.audio, self.doc)
        except OSError as exc:
            # Keep dirty so the edits are not lost; the window stays open.
            self._show_io_error("Save lyrics", self.audio.with_suffix(".lrc"), exc)
            return False
        self._set_dirty(False)
        try:
            self._update_row(read_status(self.audio))
        except OSError as exc:
            self._show_io_error("Read the saved lyrics", self.audio.with_suffix(".lrc"), exc)
        self.statusBar().showMessage("Saved (previous .lrc kept as .bak)", 5000)
        return True

    def _set_dirty(self, dirty: bool):
        self.dirty = dirty
        self.setWindowTitle(config.APP_NAME + (" *" if dirty else ""))

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        r = QMessageBox.question(self, "Unsaved edits", "Save the edits to this track first?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()      # a failed save keeps the window open
        return r != QMessageBox.Cancel

    # ---------- shutdown and updates ----------
    def _ask_queue_shutdown(self) -> str:
        """One prompt for closing and for installing an update. Returns after/now/keep."""
        box = QMessageBox(self)
        box.setWindowTitle("Queue running")
        box.setIcon(QMessageBox.Question)
        box.setText("A queue is still running.")
        box.setInformativeText("Stop after the current song, stop the running worker now, or keep working?")
        after = box.addButton("Stop after this song", QMessageBox.AcceptRole)
        now = box.addButton("Stop now", QMessageBox.DestructiveRole)
        box.addButton("Keep working", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is after:
            return "after"
        if box.clickedButton() is now:
            return "now"
        return "keep"

    def prepare_update(self, path: Path) -> bool:
        """Called in the GUI thread when an installer is ready. Uses the same shutdown path as
        closing the window; returns True only when the app may exit and start the installer now."""
        if self._queue is not None:
            choice = self._ask_queue_shutdown()
            if choice == "keep":
                self.statusBar().showMessage("Update downloaded; quit LyricLoom when the queue is done", 12000)
                return False
            self._cancel_background.set()
            self._pending_installer = path
            if choice == "now":
                self._queue.stop(now=True)
            else:
                self._queue.stop()
            self.statusBar().showMessage("The update will install when the queue stops …", 12000)
            return False
        return self._confirm_discard()

    def _install_pending_update(self):
        path, self._pending_installer = self._pending_installer, None
        if path is None or not self._confirm_discard():
            return
        try:
            from ..updater import launch_installer

            launch_installer(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Update", "Could not start the installer:\n" + str(exc))
            return
        self.close()

    def _stop_threads(self):
        self._cancel_background.set()
        self._update_controller.shutdown()
        for thread, _worker in list(self._threads):
            thread.quit()
            if not thread.wait(3000):
                # Never terminate: a scan is read-only and a worker process is cancelled through
                # the queue's cancellation event. run() joins whatever outlives the window.
                pass

    def finish_shutdown(self):
        """Joins background threads after the event loop ends, so none is destroyed while running."""
        self._update_controller.wait_for_threads()
        for thread, _worker in list(self._threads):
            thread.quit()
            thread.wait()

    def closeEvent(self, e):
        if not self._confirm_discard():
            e.ignore()
            return
        if self._queue is not None:
            choice = self._ask_queue_shutdown()
            if choice == "keep":
                e.ignore()
                return
            self._cancel_background.set()
            self._quit_after_queue = True
            if choice == "now":
                self._queue.stop(now=True)
                self.statusBar().showMessage("Stopping now; LyricLoom will close …")
            else:
                self._queue.stop()
                self.statusBar().showMessage("Stopping after the current song; LyricLoom will close …")
            e.ignore()
            return
        self._stop_threads()
        super().closeEvent(e)


def run():
    if len(sys.argv) >= 3 and sys.argv[1] == "--worker":
        from ..workers.launcher import run as run_worker

        run_worker(sys.argv[2])
        return
    config.migrate_legacy_settings()
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setApplicationDisplayName(config.APP_NAME)
    app.setOrganizationName(config.APP_NAME)
    app.setApplicationVersion(VERSION)
    icon = Path(__file__).resolve().parent.parent / "assets" / "icon.png"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    w = MainWindow()
    w.show()
    code = app.exec()
    w.finish_shutdown()
    sys.exit(code)


if __name__ == "__main__":
    run()
