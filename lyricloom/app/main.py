"""LyricLoom desktop app: library list, processing queue, player with lyrics, simple editor."""
from __future__ import annotations

import argparse
import base64
import logging
import os
import re
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field, replace
from pathlib import Path

import mutagen

from PySide6.QtCore import QByteArray, QObject, QThread, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QGuiApplication, QIcon, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QSlider, QSplitter,
                               QSystemTrayIcon, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import cache, config, runner, runtime
from .. import VERSION
from ..lrc import format_ts, parse_lrc
from ..model import LrcDoc, Segment
from ..stages.write import apply_script_preference, japanese_path, write_lyrics
from .details import TrackDetailsDialog, details_text
from .diagnostics import DiagnosticsDialog, diagnostics_text, open_local_folder, setup_app_logging
from .dialogs import (ModelsDialog, SettingsDialog, UpdateController, check_for_updates, validate_folder)
from .ipc import Server as IpcServer
from .ipc import send as ipc_send
from .karaoke import KaraokeWindow
from .model import (STAGE_LABELS, TrackRow, apply_edits, delete_line, delete_word, insert_line, insert_word,
                    load_cached_rows, merge_with_previous, read_status, scan_cached, store_result, track_progress)
from .paths import expand_audio_paths, validate_audio_file

FILTERS = ["All", "Review", "Pending", "Failed", "Other", "Done"]
STATUS_LABELS = {"cancelled": "Stopped"}
REVIEW_TINT = QColor(255, 196, 0, 70)
_TS = re.compile(r"^(\d+):(\d{1,2})(?:[.:](\d{1,3}))?$")
LOG = logging.getLogger(__name__)


def parse_ts(text: str) -> int | None:
    m = _TS.match(text.strip())
    if not m:
        return None
    return int(m.group(1)) * 60000 + int(m.group(2)) * 1000 + int((m.group(3) or "0").ljust(3, "0")[:3])


class _SortItem(QTableWidgetItem):
    """Table item with a numeric/lexical sort key so Confidence sorts as a number."""

    def __init__(self, text: str, key=None):
        super().__init__(text)
        self._key = text if key is None else key

    def __lt__(self, other):
        a = self._key
        b = getattr(other, "_key", other.text())
        try:
            return float(a) < float(b)
        except (TypeError, ValueError):
            return str(a).lower() < str(b).lower()


def queue_summary(results: list) -> str:
    """One line for the status bar, tray notification and summary dialog."""
    labels = (("done", "done"), ("review", "review"), ("skipped", "skipped"),
              ("failed", "failed"), ("cancelled", "stopped"))
    counts = {status: sum(1 for r in results if getattr(r, "status", "") == status)
              for status, _ in labels}
    parts = [f"{counts[status]} {label}" for status, label in labels if counts[status]]
    fallbacks = sum(1 for r in results if getattr(r, "fallback", ""))
    if fallbacks:
        parts.append(f"{fallbacks} fallback")
    if not parts:
        return "Queue finished: no tracks processed"
    return "Queue finished: " + ", ".join(parts)


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
                row.device, row.fallback = res.device, res.fallback
                try:
                    row.log_path = str(cache.work_dir(p) / "log.txt")
                except OSError:
                    row.log_path = ""
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
                try:
                    row.log_path = str(cache.work_dir(p) / "log.txt")
                except OSError:
                    row.log_path = ""
                self.track_done.emit(row)


class MainWindow(QMainWindow):
    def __init__(self, root: Path = None, *, server: IpcServer | None = None,
                 startup: dict | None = None):
        super().__init__()
        self.root = Path(root or config.library_root())
        self.rows: list[TrackRow] = []
        self.audio: Path | None = None
        self.doc: LrcDoc | None = None
        self.dirty = False
        self._threads: list[tuple[QThread, QObject]] = []
        self._queue: QueueWorker | None = None
        self._queue_error = ""
        self._queue_results: list = []
        self._queue_started = 0.0
        self._external_backlog: list[tuple[list[Path], bool]] = []
        self._pending_select: Path | None = None
        self._pending_last_track = config.setting("library/last_track")
        self._restored_last_track = startup is not None
        self._notice = ""
        self._tray: QSystemTrayIcon | None = None
        self._quit_after_queue = False
        self._pending_installer: Path | None = None
        self._cancel_background = threading.Event()
        self._stop_at: int | None = None
        self._shown_line = -1
        self.karaoke_window: KaraokeWindow | None = None
        self._update_controller = UpdateController(self)
        self.setWindowTitle(config.APP_NAME)
        self.resize(1400, 850)
        self.setMinimumSize(640, 480)
        self._build()
        self._build_menu()
        self._restore_ui_state()
        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        self.player.durationChanged.connect(lambda d: self.seek.setRange(0, d))
        self.timer = QTimer(self, interval=50, timeout=self._tick)
        self.timer.start()
        self.refresh()
        self._ipc_server = server
        if self._ipc_server is None:
            self._ipc_server = IpcServer(parent=self)
            if not self._ipc_server.listen():
                # The caller already tried to reach a running instance; a failed listen here is a
                # stale name (Linux) or a process that appeared in between.
                self._ipc_server.remove_stale()
                self._ipc_server.listen()
        if self._ipc_server.is_listening:
            self._ipc_server.received.connect(self._external_message)
            self._ipc_server.set_ready()
            self._ipc_available = True
        else:
            self._ipc_available = False
            LOG.warning("single-instance server %s could not listen", self._ipc_server.name)
        if startup is not None:
            QTimer.singleShot(0, lambda: self._handle_external(startup))
        else:
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
        help_menu.addAction(QAction("Open &log folder", self, triggered=self.open_log_folder))
        help_menu.addSeparator()
        help_menu.addAction(QAction("&Diagnostics…", self, triggered=self.show_diagnostics))
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

    def open_log_folder(self):
        open_local_folder(config.LOG_DIR)

    def show_diagnostics(self):
        DiagnosticsDialog(diagnostics_text(self.root), self).exec()

    def show_details(self):
        rows = self._selected_rows()
        if not rows:
            self.statusBar().showMessage("Select a track to see its details", 4000)
            return
        row = rows[0]
        log = Path(row.log_path) if row.log_path and Path(row.log_path).is_file() else None
        if log is None:
            log = self._track_log(row.path)
        device = self._device_text(row.device) if row.device else ""
        TrackDetailsDialog(details_text(row, device), log, self).exec()

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
        self.root_label.setWordWrap(True)
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
        self.search = QLineEdit(placeholderText="Search artist / title / status")
        top.addWidget(self.filter)
        top.addWidget(self.search)
        lv.addLayout(top)
        self.library_banner = QWidget()
        banner = QHBoxLayout(self.library_banner)
        banner.setContentsMargins(0, 0, 0, 0)
        self.library_banner_label = QLabel()
        self.library_banner_label.setWordWrap(True)
        self.library_banner_label.setStyleSheet("color: #8a4b00;")
        self.btn_choose_library = QPushButton("Choose another folder")
        self.btn_retry_library = QPushButton("Try again")
        banner.addWidget(self.library_banner_label, 1)
        banner.addWidget(self.btn_choose_library)
        banner.addWidget(self.btn_retry_library)
        self.library_banner.hide()
        lv.addWidget(self.library_banner)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Artist", "Title", "Status", "Source", "Conf", "Notes"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_context_menu)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        lv.addWidget(self.table)
        btns = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_sel = QPushButton("Process selected")
        self.btn_pending = QPushButton("Process pending")
        self.btn_redo = QPushButton("Redo selected")
        self.btn_redo.setToolTip("Delete the word timing of the selected songs and align them again")
        self.btn_details = QPushButton("Details…")
        self.btn_details.setToolTip("Show the last result, fallback reason and log for the selected track")
        self.btn_stop = QPushButton("Stop after this song", enabled=False)
        self.btn_stop.setToolTip("Let the current song finish, then stop the queue")
        self.btn_stop_now = QPushButton("Stop now", enabled=False)
        self.btn_stop_now.setToolTip("Kill the running worker and stop the queue immediately")
        self.btn_pause = QPushButton("Pause after this song", enabled=False)
        self.btn_pause.setToolTip("Stop before the next song; the current song finishes")
        self.force = QCheckBox("Force")
        for w in (self.btn_refresh, self.btn_sel, self.btn_pending, self.btn_redo, self.btn_details,
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
        self.splitter = split
        self.setCentralWidget(split)

        self.filter.currentIndexChanged.connect(self._fill_table)
        self.search.textChanged.connect(self._fill_table)
        self.table.itemSelectionChanged.connect(self._on_track_selected)
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_library.clicked.connect(self.choose_library)
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_key.clicked.connect(self.set_api_key)
        self.btn_choose_library.clicked.connect(self.choose_library)
        self.btn_retry_library.clicked.connect(self.refresh)
        self.btn_details.clicked.connect(self.show_details)
        self.setAcceptDrops(True)
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
        if not root.is_dir():
            # An unplugged drive must not look like a library whose files were deleted.
            if not self.rows:
                self.rows = load_cached_rows(root)
                self._fill_table()
            self._set_library_available(False, root)
            self.statusBar().showMessage(f"Library folder is unavailable: {root}", 12000)
            return
        self._set_library_available(True)
        if not self.rows:
            self.rows = load_cached_rows(root)
            self._fill_table()
        self.statusBar().showMessage(f"Checking {root} for changes …")

        def scan():
            stats: dict = {}
            return root, scan_cached(root, stats), stats

        self._run(FuncWorker(scan), self._scanned, self._scan_failed)

    def _set_library_available(self, available: bool, root: Path | None = None) -> None:
        self.library_banner.setVisible(not available)
        if not available:
            self.library_banner_label.setText(
                f"Library folder is unavailable:\n{root or self.root}\n"
                "Reconnect the drive, choose another folder, or try again.")

    def _scanned(self, result):
        root, rows, stats = result
        if root != self.root:   # the library was switched while this scan ran
            return
        previous = {r.path: r for r in self.rows}
        for row in rows:
            old = previous.get(row.path)
            if old is None:
                continue
            # Keep the last queue result visible even if the cache could not be written.
            if not row.error:
                row.error = old.error
            if not row.fallback:
                row.fallback = old.fallback
            if not row.device:
                row.device = old.device
            if not row.log_path:
                row.log_path = old.log_path
            if row.status == "pending" and old.status in ("failed", "cancelled"):
                row.status = old.status
        self.rows = rows
        self._fill_table()
        if self._pending_select is not None:
            self._select_pending()
        elif not self._restored_last_track:
            self._restored_last_track = True
            self._restore_last_track()
        message = f"{len(rows)} track" + ("" if len(rows) == 1 else "s")
        unreadable = int(stats.get("unreadable", 0))
        if unreadable:
            message += f" · {unreadable} file(s) could not be read (see the row tooltips)"
        self.statusBar().showMessage(message, 8000 if unreadable else 5000)

    def _scan_failed(self, message: str):
        self.statusBar().showMessage("Scan failed: " + message + " — the previous list was kept", 12000)

    def _restore_last_track(self) -> None:
        if not self._pending_last_track:
            return
        try:
            path = Path(self._pending_last_track)
        except (TypeError, ValueError):
            return
        self._select_path(path, prompt=False)

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
        self._restored_last_track = True
        self.refresh()

    def _show_io_error(self, action: str, path: Path, exc: OSError) -> None:
        reason = exc.strerror or str(exc)
        message = f"{action} failed:\n{path}\n\n{reason}"
        self.statusBar().showMessage(f"{action} failed: {reason}", 12000)
        QMessageBox.critical(self, action, message)

    def _visible_rows(self) -> list[TrackRow]:
        f = FILTERS[self.filter.currentIndex()].lower()
        q = self.search.text().lower()
        rows = []
        for r in self.rows:
            status = STATUS_LABELS.get(r.status, r.status)
            if (f == "all" or r.status == f) and (q in r.artist.lower() or q in r.title.lower()
                                                  or q in status.lower() or q in r.status.lower()):
                rows.append(r)
        return rows

    def _fill_table(self):
        rows = self._visible_rows()
        header = self.table.horizontalHeader()
        sort_column, sort_order = header.sortIndicatorSection(), header.sortIndicatorOrder()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            status = STATUS_LABELS.get(r.status, r.status)
            notes = "⚠ fallback" if r.fallback else ("⚠ error" if r.error else "")
            values = [r.artist, r.title, status, r.source, f"{r.conf:.2f}" if r.source else "", notes]
            keys = [r.artist.lower(), r.title.lower(), status.lower(), r.source.lower(),
                    r.conf if r.source else -1.0, notes]
            tips = []
            if r.error:
                tips.append("Error:\n" + r.error)
            if r.fallback:
                tips.append("Fallback:\n" + r.fallback)
            if r.device:
                tips.append("Device: " + self._device_text(r.device))
            if r.log_path:
                tips.append("Log: " + r.log_path)
            for j, (v, key) in enumerate(zip(values, keys)):
                item = _SortItem(v, key)
                item.setData(Qt.UserRole, str(r.path))
                if r.status == "review":
                    item.setBackground(REVIEW_TINT)
                if tips:
                    item.setToolTip("\n\n".join(tips))
                self.table.setItem(i, j, item)
        self.table.setSortingEnabled(True)
        if 0 <= sort_column < self.table.columnCount():
            self.table.sortItems(sort_column, sort_order)

    def _selected_rows(self) -> list[TrackRow]:
        paths = {self.table.item(i.row(), 0).data(Qt.UserRole) for i in self.table.selectionModel().selectedRows()}
        return [r for r in self.rows if str(r.path) in paths]

    def _update_row(self, row: TrackRow):
        for i, r in enumerate(self.rows):
            if r.path == row.path:
                self.rows[i] = row
                break
        else:
            self.rows.append(row)
        self._fill_table()

    def _ensure_rows(self, paths: list[Path]) -> None:
        """Adds rows for files that are not in the current scan (e.g. --process outside the library)."""
        known = {r.path for r in self.rows}
        added = False
        for path in paths:
            if path in known:
                continue
            try:
                row = read_status(path)
            except Exception as exc:  # noqa: BLE001 - a transient row must not break the window
                row = TrackRow(path, path.parent.name, path.stem, "pending",
                               error=f"could not read this file: {type(exc).__name__}: {exc}")
            self.rows.append(row)
            known.add(path)
            added = True
        if added:
            self._fill_table()

    def _select_path(self, path: Path, *, prompt: bool = True) -> bool:
        try:
            wanted = str(Path(path).resolve())
        except (OSError, RuntimeError):
            wanted = str(path)
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item is None:
                continue
            try:
                value = str(Path(item.data(Qt.UserRole)).resolve())
            except (OSError, RuntimeError):
                value = str(item.data(Qt.UserRole))
            if value == wanted:
                if prompt and not self._confirm_discard():
                    return False
                self.table.selectRow(i)
                return True
        return False

    def _select_pending(self) -> None:
        path, self._pending_select = self._pending_select, None
        if path is None:
            return
        self._restored_last_track = True   # an explicit command wins over the remembered track
        # A filter or search must not hide the song the user or another program asked to see.
        if self.filter.currentIndex() != 0:
            self.filter.setCurrentIndex(0)
        if self.search.text():
            self.search.clear()
        if not self._select_path(path):
            self._ensure_rows([path])
            self._select_path(path)

    # ---------- external commands and drag-and-drop ----------
    @Slot(object)
    def _external_message(self, message: dict) -> None:
        self._handle_external(message)

    def _handle_external(self, message: dict) -> None:
        command = message.get("cmd")
        if command == "process":
            rejected = list(message.get("rejected") or [])
            paths = [Path(p) for p in message.get("paths", [])]
            report = self._report_rejected(rejected) if rejected else None
            if paths:
                self.enqueue_external(paths, bool(message.get("redo")),
                                      announce=message.get("source") == "ipc")
                if report:
                    self.statusBar().showMessage(report, 15000)
            elif rejected and message.get("source") == "ipc":
                self._flash_notice(f"Ignored {len(rejected)} path(s)", detail=report)
            return
        if command == "open":
            self.open_external(Path(message["path"]))
            return
        if command == "activate":
            self._bring_to_front()
            return
        if command == "report":
            rejected = list(message.get("rejected") or [])
            self._report_rejected(rejected)
            if rejected and message.get("source") == "ipc":
                self._flash_notice(f"Ignored {len(rejected)} path(s)")

    def _report_rejected(self, rejected: list[str]) -> str | None:
        if not rejected:
            return None
        shown = "; ".join(rejected[:3])
        more = f"; and {len(rejected) - 3} more" if len(rejected) > 3 else ""
        message = f"Ignored {len(rejected)} path(s): {shown}{more}"
        self.statusBar().showMessage(message, 15000)
        LOG.warning("%s", message)
        return message

    def enqueue_external(self, paths: list[Path], redo: bool = False, *, announce: bool = False) -> None:
        paths = [Path(p) for p in paths]
        if not paths:
            return
        if announce:
            self._flash_notice(f"{len(paths)} file(s) queued from another program")
        self._ensure_rows(paths)
        if self.audio is None:
            self._pending_select = paths[0]
            self._select_pending()
        if self._queue is not None:
            self._external_backlog.append((paths, redo))
            self.statusBar().showMessage(
                f"{len(paths)} track(s) queued; they start when the current queue ends", 8000)
            return
        if not self.process(paths, redo=redo):
            self.statusBar().showMessage("Could not start the queued track(s)", 8000)

    def open_external(self, path: Path) -> None:
        path = Path(path).resolve()
        self._bring_to_front()
        try:
            inside = path.is_relative_to(self.root.resolve())
        except (OSError, RuntimeError, ValueError):
            inside = False
        if not inside:
            self.root = path.parent
            try:
                config.set_library_root(self.root)
            except OSError as exc:
                self._show_io_error("Save the library setting", config.SETTINGS_FILE, exc)
            self.rows = []
            self._pending_select = path
            self.refresh()
            self.statusBar().showMessage(f"Showing {path.name} from {self.root}", 8000)
            return
        self._ensure_rows([path])
        self._pending_select = path
        self._select_pending()
        self.statusBar().showMessage(f"Showing {path.name}", 5000)

    def _bring_to_front(self) -> None:
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def _flash_notice(self, message: str, detail: str | None = None) -> None:
        self._notice = message
        self._refresh_title()
        self.statusBar().showMessage(detail or message, 10000)
        QApplication.alert(self, 0)
        QTimer.singleShot(15000, self._clear_notice)

    def _clear_notice(self) -> None:
        self._notice = ""
        try:
            self._refresh_title()
        except RuntimeError:
            pass

    def _notify(self, title: str, message: str) -> None:
        """Tray notification plus taskbar flash for a queue that ended out of sight."""
        self.statusBar().showMessage(message, 15000)
        if not config.setting("notify_queue_finished", True):
            return
        QApplication.alert(self, 0)
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        if self._tray is None:
            icon = self.windowIcon()
            if icon.isNull():
                icon = QApplication.windowIcon()
            self._tray = QSystemTrayIcon(icon, self)
            self._tray.messageClicked.connect(self._bring_to_front)
        self._tray.show()
        self._tray.showMessage(title, message, QSystemTrayIcon.Information, 10000)
        QTimer.singleShot(12000, self._hide_tray)

    def _hide_tray(self) -> None:
        if self._tray is not None:
            try:
                self._tray.hide()
                self._tray.deleteLater()
            except RuntimeError:
                pass
            self._tray = None

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self.drop_paths(paths)

    def drop_paths(self, paths) -> None:
        accepted, rejected = expand_audio_paths(paths)
        self._report_rejected(rejected)
        if accepted:
            self.enqueue_external(accepted)

    def _table_context_menu(self, pos) -> None:
        row_index = self.table.rowAt(pos.y())
        if row_index < 0:
            return
        item = self.table.item(row_index, 0)
        if item is None:
            return
        path = Path(item.data(Qt.UserRole))
        row = next((r for r in self.rows if r.path == path), None)
        if row is None:
            return
        menu = QMenu(self)
        act_process = menu.addAction("Process")
        act_redo = menu.addAction("Redo word timing")
        act_details = menu.addAction("Details…")
        menu.addSeparator()
        act_folder = menu.addAction("Open folder")
        act_copy = menu.addAction("Copy path")
        act_log = menu.addAction("Open log")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is act_process:
            self.process([path])
        elif chosen is act_redo:
            self._redo_paths([path])
        elif chosen is act_details:
            self.table.selectRow(row_index)
            self.show_details()
        elif chosen is act_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        elif chosen is act_copy:
            QApplication.clipboard().setText(str(path))
            self.statusBar().showMessage("Path copied", 3000)
        elif chosen is act_log:
            self._open_track_log(row)

    def _track_log(self, path: Path) -> Path | None:
        try:
            return cache.work_dir(path) / "log.txt"
        except OSError:
            return None

    def _open_track_log(self, row: TrackRow) -> None:
        log = Path(row.log_path) if row.log_path else self._track_log(row.path)
        if log is not None and log.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(log)))
        else:
            QMessageBox.information(self, "Track log", "There is no log for this track yet.")

    # ---------- window state ----------
    def _restore_ui_state(self) -> None:
        geometry = config.setting("window/geometry")
        if isinstance(geometry, str) and geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
            except (TypeError, ValueError):
                pass
        state = config.setting("window/state")
        if isinstance(state, str) and state:
            try:
                self.restoreState(QByteArray.fromBase64(state.encode("ascii")))
            except (TypeError, ValueError):
                pass
        sizes = config.setting("splitter")
        if isinstance(sizes, list) and len(sizes) == 2:
            try:
                self.splitter.setSizes([max(0, int(x)) for x in sizes])
            except (TypeError, ValueError):
                pass
        columns = config.setting("table/columns")
        if isinstance(columns, list):
            for i, width in enumerate(columns[:self.table.columnCount()]):
                if i == 1:   # the title column stays stretched
                    continue
                try:
                    self.table.setColumnWidth(i, max(24, int(width)))
                except (TypeError, ValueError):
                    pass
        self._clamp_to_screen()

    def _clamp_to_screen(self) -> None:
        screen = QGuiApplication.screenAt(self.frameGeometry().center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        max_width = max(320, int(available.width() * 0.9))
        max_height = max(240, int(available.height() * 0.9))
        if self.minimumWidth() > max_width or self.minimumHeight() > max_height:
            # A very small screen or a scaled remote desktop: keep the window usable and on-screen.
            self.setMinimumSize(min(self.minimumWidth(), max_width), min(self.minimumHeight(), max_height))
        width = min(self.width(), max_width)
        height = min(self.height(), max_height)
        if (width, height) != (self.width(), self.height()):
            self.resize(width, height)
        x = min(max(self.x(), available.left()), max(available.left(), available.right() - self.width() + 1))
        y = min(max(self.y(), available.top()), max(available.top(), available.bottom() - self.height() + 1))
        self.move(x, y)

    def _save_ui_state(self) -> None:
        values = {
            "window/geometry": base64.b64encode(bytes(self.saveGeometry())).decode("ascii"),
            "window/state": base64.b64encode(bytes(self.saveState())).decode("ascii"),
            "splitter": self.splitter.sizes(),
            "table/columns": [self.table.columnWidth(i) for i in range(self.table.columnCount())],
        }
        if self.audio is not None:
            values["library/last_track"] = str(self.audio)
        try:
            config.update_settings(values)
        except OSError as exc:
            LOG.warning("could not save window state: %s", exc)

    def _refresh_title(self) -> None:
        title = config.APP_NAME
        if self._notice:
            title = f"{config.APP_NAME} — {self._notice}"
        if self.dirty:
            title += " *"
        self.setWindowTitle(title)

    # ---------- processing ----------
    def redo_selected(self):
        self._redo_paths([r.path for r in self._selected_rows()])

    def _redo_paths(self, paths: list[Path]):
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

    def process(self, paths: list[Path], redo: bool = False) -> bool:
        if not paths or self._queue is not None:
            return False
        paths = self._confirm_open_track(paths, redo)
        if not paths:
            return False
        if not self._validate_folders():
            return False
        self._queue_error = ""
        self._queue_results = []
        self._queue_started = time.monotonic()
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
        return True

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
        if device == "dml":
            return "Device: DirectML"
        if device == "cpu":
            return "Device: CPU (fallback)"
        if device == "kept":
            return "Device: vocals already cached"
        return (f"Device: ROCm (WSL {config.SEPARATOR_WSL_DISTRO})"
                if config.SEPARATOR_WSL_ENABLED else "Device: CPU")

    def _device_changed(self, res):
        """Shows where the last song was separated, so a silent CPU fallback is visible."""
        self._queue_results.append(res)
        if not res.device:
            return
        self.gpu.setText(self._device_text(res.device))
        failed = bool(res.fallback)
        self.gpu.setStyleSheet("color: #c06000;" if failed or res.device == "cpu" else "")
        self.gpu.setToolTip(
            ("Separation in WSL/ROCm failed and ran on the CPU instead:\n" + res.fallback[-1500:])
            if failed else self._gpu_tip)

    def _track_finished(self, row: TrackRow):
        if self._prog is not None:
            self._prog["done"] += 1
            self._prog["since"] = time.monotonic()
        self._update_row(row)
        store_result(self.root, row)
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
        results = self._queue_results
        elapsed = time.monotonic() - self._queue_started if self._queue_started else 0.0
        total = int(self._prog.get("total", 0)) if self._prog else 0
        long_queue = total > 1 or len(results) > 1 or elapsed >= 60
        summary = queue_summary(results)
        cancelled = bool(self._prog and self._prog.get("done", 0) < self._prog.get("total", 0))
        self._queue = None
        self._prog = None
        self._queue_results = []
        self._queue_started = 0.0
        self.prog_timer.stop()
        self.progress.hide()
        self.btn_stop.setEnabled(False)
        self.btn_stop_now.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("Pause after this song")

        if self._external_backlog and self._pending_installer is None and not self._quit_after_queue:
            paths, redo = self._external_backlog.pop(0)
            self.statusBar().showMessage(
                f"Starting the next queued batch ({len(paths)} track(s)) …", 5000)
            if not self.process(paths, redo=redo):
                self.statusBar().showMessage("Could not start the next queued batch", 8000)
            return

        if self._queue_error:
            self.statusBar().showMessage("Queue finished with an error: " + self._queue_error, 12000)
            LOG.warning("queue error: %s", self._queue_error)
            if self.isActiveWindow():
                QMessageBox.warning(self, "Queue error", self._queue_error)
            else:
                self._notify("Queue error", self._queue_error)
            self._queue_error = ""
        elif cancelled:
            self.statusBar().showMessage(summary if results else "Queue stopped", 8000)
        elif long_queue:
            self.statusBar().showMessage(summary, 10000)
            if self.isActiveWindow():
                QMessageBox.information(self, "Queue finished", summary)
            else:
                self._notify("Queue finished", summary)
        else:
            self.statusBar().showMessage(summary if results else "Queue finished", 6000)
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
        self._refresh_title()

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
        self._save_ui_state()
        if self._ipc_server is not None:
            self._ipc_server.close()
        self._stop_threads()
        super().closeEvent(e)


@dataclass
class CommandLine:
    process: list[str] = field(default_factory=list)
    open_file: str | None = None
    redo: bool = False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=config.APP_NAME,
        description="LyricLoom desktop app. With no arguments the library window opens.")
    parser.add_argument("--process", nargs="+", action="append", metavar="FILE",
                        help="queue one or more audio files (or folders) and start processing")
    parser.add_argument("--open", dest="open_file", metavar="FILE",
                        help="select one audio file in the library without processing it")
    parser.add_argument("--redo", action="store_true",
                        help="with --process, redo the word timing instead of the normal run")
    return parser


def parse_command_line(argv: list[str]) -> CommandLine:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.redo and not args.process:
        parser.error("--redo is only valid together with --process")
    if args.open_file and (args.process or args.redo):
        parser.error("--open cannot be combined with --process or --redo")
    process = [path for group in (args.process or []) for path in group]
    return CommandLine(process=process, open_file=args.open_file, redo=bool(args.redo))


def run(argv: list[str] | None = None):
    argv = list(sys.argv if argv is None else argv)
    if len(argv) >= 2 and argv[0] == "--worker":
        from ..workers.launcher import run as run_worker

        run_worker(argv[1])
        return
    if len(argv) >= 3 and argv[1] == "--worker":
        from ..workers.launcher import run as run_worker

        run_worker(argv[2])
        return
    has_program = bool(argv) and not argv[0].startswith("-")
    cli = parse_command_line(argv[1:] if has_program else argv)
    config.migrate_legacy_settings()
    app = QApplication(argv if has_program else [config.APP_NAME, *argv])
    app.setApplicationName(config.APP_NAME)
    app.setApplicationDisplayName(config.APP_NAME)
    app.setOrganizationName(config.APP_NAME)
    app.setApplicationVersion(VERSION)
    icon = Path(__file__).resolve().parent.parent / "assets" / "icon.png"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    setup_app_logging()

    # A running instance owns the window. Hand over the command and exit without creating one;
    # a process request from MusicBee must not steal focus.
    if cli.process:
        command = {"cmd": "process", "paths": cli.process, "redo": cli.redo}
    elif cli.open_file:
        command = {"cmd": "open", "path": cli.open_file}
    else:
        command = {"cmd": "activate"}
    if ipc_send(command) is not None:
        sys.exit(0)

    startup = None
    if cli.process:
        accepted, rejected = expand_audio_paths(cli.process)
        startup = {"cmd": "process", "paths": accepted, "rejected": rejected, "redo": cli.redo}
    elif cli.open_file:
        opened, error = validate_audio_file(cli.open_file)
        startup = ({"cmd": "open", "path": opened} if opened is not None
                   else {"cmd": "report", "rejected": [error or f"{cli.open_file}: invalid path"]})

    server = IpcServer()
    if not server.listen():
        # A crashed process can leave the name behind on Linux; only remove it after nobody
        # answered above.
        server.remove_stale()
        if not server.listen():
            LOG.warning("single-instance server %s could not listen", server.name)
    if server.is_listening:
        server.hold()   # buffer a command that arrives while MainWindow is built
    w = MainWindow(server=server, startup=startup)
    if not w._ipc_available:
        # Another process won the start race after our first attempt: forward and use its window.
        if ipc_send(command) is not None:
            w.dirty = False
            w.close()
            sys.exit(0)
    w.show()
    code = app.exec()
    w.finish_shutdown()
    sys.exit(code)


if __name__ == "__main__":
    run()
