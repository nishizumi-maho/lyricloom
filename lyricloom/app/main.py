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

from PySide6.QtCore import (QByteArray, QElapsedTimer, QLocale, QObject, QThread, QTimer, QUrl, Qt, Signal,
                            Slot)
from PySide6.QtGui import (QAction, QDesktopServices, QFont, QGuiApplication, QIcon, QKeySequence,
                           QUndoCommand, QUndoStack)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
                               QSplitter, QSystemTrayIcon, QTableView, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import cache, config, gpu_runtime, runner, runtime, vocal_export
from .. import models as model_catalog
from .. import VERSION, updater
from ..errtext import message_text, os_error_text
from ..lrc import format_ts, parse_lrc
from ..model import LrcDoc, Segment
from ..stages.write import apply_script_preference, japanese_path, write_lyrics
from . import model_status, theme
from .details import TrackDetailsDialog, details_text
from .diagnostics import DiagnosticsDialog, diagnostics_text, open_local_folder, setup_app_logging
from .dialogs import SettingsDialog, UpdateController, check_for_updates, validate_folder
from .ipc import Server as IpcServer
from .ipc import send as ipc_send
from .karaoke import KaraokeWindow
from .library import FILTERS, REVIEW_TINT, TrackFilterProxyModel, TrackTableModel
from .lyric_view import LyricView
from .media import default_script_path, script_candidates, vocal_source
from .model import (STAGE_LABELS, TrackRow, apply_edits, clear_review_flags, delete_line, delete_word,
                    insert_line, insert_word, load_cached_rows, mark_line_reviewed, merge_with_previous,
                    other_model_stages, read_status, review_lines, scan_cached, store_result,
                    track_progress)
from .models_window import MissingModelsDialog, ModelsWindow, PerSongModelsDialog
from .paths import expand_audio_paths, validate_audio_file
from .setup_assistant import PAGE_KEYS, SetupAssistant
from .update_ui import UpdateBar
from .widgets import SeekSlider

_TS = re.compile(r"^(\d+):(\d{1,2})(?:[.:](\d{1,3}))?$")
LOG = logging.getLogger(__name__)


def parse_ts(text: str) -> int | None:
    m = _TS.match(text.strip())
    if not m:
        return None
    return int(m.group(1)) * 60000 + int(m.group(2)) * 1000 + int((m.group(3) or "0").ljust(3, "0")[:3])


class _DocCommand(QUndoCommand):
    """One document edit, stored as before/after snapshots.

    `LrcDoc` is small and every edit function returns a new document, so snapshots are cheap and
    cannot be changed by a later edit. The line/word shown after undo and redo is stored too, so
    the list selection follows the edit instead of jumping to the top.
    """

    def __init__(self, window: "MainWindow", before: LrcDoc | None, after: LrcDoc | None, text: str,
                 undo_line: int = -1, redo_line: int = -1, undo_word: int = -1, redo_word: int = -1):
        super().__init__(text)
        self._window = window
        self._before, self._after = before, after
        self._undo_line, self._redo_line = undo_line, redo_line
        self._undo_word, self._redo_word = undo_word, redo_word

    def undo(self):
        self._window._restore_doc(self._before, self._undo_line, self._undo_word)

    def redo(self):
        self._window._restore_doc(self._after, self._redo_line, self._redo_word)


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


BUSY_INSTANCE_MESSAGE = "LyricLoom is already running but is not responding"
BUSY_RETRY_TIMEOUT_MS = 10_000
BACKGROUND_JOIN_TIMEOUT_MS = 30_000


def _join_background_jobs() -> None:
    """Joins the assistant, Models-window and Settings-dialog threads with bounded waits.

    ``aboutToQuit`` calls this (FRB-06); ``MainWindow.finish_shutdown`` calls it too, so a test or
    an embedding host that never emits ``aboutToQuit`` still stops the threads it can.
    """
    from . import dialogs, models_window, setup_assistant

    setup_assistant.join_background_jobs()
    dialogs.join_test_threads()
    models_window.join_status_checks()


def install_shutdown_joins() -> None:
    """Registers the bounded thread joins once per QApplication."""
    app = QApplication.instance()
    if app is None or getattr(app, "_lyricloom_shutdown_joins", False):
        return
    app.aboutToQuit.connect(_join_background_jobs)
    app._lyricloom_shutdown_joins = True   # type: ignore[attr-defined]


def handle_busy_instance(server, command, *, send=None, notify=None) -> bool:
    """After a failed listen: True when another live instance owns the name and we must exit.

    ``remove_stale`` only removes a name after a probe; False means a live process holds it. That
    process may simply have been busy when the first hand-over arrived, so try once more with a
    longer timeout. If it still does not answer, say so instead of opening a second window that
    would write the same settings and .lrc files.
    """
    if server.remove_stale():
        return False   # a crashed process left the name behind; this instance may listen
    sender = send or ipc_send
    try:
        reply = sender(command, timeout_ms=BUSY_RETRY_TIMEOUT_MS)
    except Exception as exc:  # noqa: BLE001 - a hand-over failure must show the busy message
        # A command that cannot be serialised (or a socket error) must not kill the second
        # instance with a traceback; the user gets the same explanation as a silent instance.
        LOG.warning("could not hand the command to the running instance: %s", exc)
        reply = None
    if reply is not None:
        return True
    if notify is None:
        QMessageBox.warning(None, config.APP_NAME, BUSY_INSTANCE_MESSAGE)
    else:
        notify(BUSY_INSTANCE_MESSAGE)
    return True


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


class _ThreadFinishedRelay(QObject):
    """Carries ``QThread.finished`` to a GUI-thread callable with the thread it belongs to.

    ``QThread.finished`` is emitted from the worker thread and PySide's ``sender()`` is None in a
    Python slot, so the thread is captured in the callback instead (FRB-11).
    """

    def __init__(self, callback, parent: QObject | None = None):
        super().__init__(parent)
        self._callback = callback

    @Slot()
    def run(self) -> None:
        self._callback()


class _ModelCheckRelay(QObject):
    """Delivers a model-status sweep to the window in the GUI thread (a lambda would not be)."""

    def __init__(self, window: "MainWindow", entries: list, parent: QObject | None = None):
        super().__init__(parent or window)
        self._window = window
        self._entries = entries

    @Slot(object)
    def done(self, states: dict) -> None:
        self._window._models_ready(self._entries, states)
        self.deleteLater()

    @Slot(str)
    def failed(self, message: str) -> None:
        self._window._models_check_failed(self._entries, message)
        self.deleteLater()


@dataclass
class QueueItem:
    """One track and the optional per-song model choices for that run."""
    path: Path
    models: dict[str, str] | None = None


@dataclass
class _PendingQueue:
    """A queue accepted by the window while the model-status check runs off the GUI thread."""
    paths: list[Path]
    redo: bool
    research: bool
    models: dict[str, str] | None
    from_backlog: bool = False
    force: bool = False   # this queue re-runs every stage, whatever the Force checkbox says


@dataclass
class _InstallRequest:
    """"Restart now"/"Install now": the verified download Setup starts with once the close ends."""
    path: Path
    info: updater.UpdateInfo | None
    silent: bool
    relaunch: bool


class QueueWorker(QObject):
    """Processes tracks one at a time.

    stop() stops after the current track; stop(now=True) sets the cancellation event that reaches
    the running worker process. pause() stops before the next track (a subprocess cannot pause).
    A track that fails with MissingModels pauses the queue, emits `missing_models` and is retried
    after the window downloads the models and resumes.
    """
    track_started = Signal(str)
    stage = Signal(str)
    track_done = Signal(object)
    device = Signal(object)   # the finished TrackResult: where the vocals were separated
    queue_error = Signal(str)
    missing_models = Signal(object)
    finished = Signal()

    def __init__(self, paths: list[Path] | list[QueueItem], force: bool, redo: bool = False,
                 research: bool = False, allow_cloud: bool | None = None):
        super().__init__()
        self._items = [p if isinstance(p, QueueItem) else QueueItem(Path(p)) for p in paths]
        self._force, self._redo = force, redo
        self._research = research
        self._allow_cloud = allow_cloud
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
        last_missing: dict[Path, frozenset[str]] = {}
        blocked: Path | None = None
        index = 0
        while index < len(self._items):
            item = self._items[index]
            p = item.path
            while self._pause.is_set() and not self._cancel.is_set() and not self._stop_after:
                time.sleep(0.05)
            if self._cancel.is_set() or self._stop_after:
                if blocked == p:
                    # The track was started and paused on missing models; stopping here must not
                    # leave its row "processing" forever (FRB-08).
                    try:
                        row = read_status(p)
                    except Exception:  # noqa: BLE001 - the row must still become terminal
                        row = TrackRow(p, p.parent.name, p.stem, "cancelled")
                    row.status, row.error = "cancelled", "Stopped while waiting for models"
                    self.track_done.emit(row)
                break
            blocked = None
            self.track_started.emit(str(p))
            moved: dict[Path, Path] = {}
            try:
                if self._redo:
                    # word timing moved aside and aligned again; lyrics, separation and
                    # transcription come from the cache when the song was done on this machine
                    moved = runner.forget_sync(p)
                    res = runner.process(p, force=True, only_stage="align",
                                         on_stage=self.stage.emit, cancel=self._cancel,
                                         models=item.models, allow_cloud=self._allow_cloud)
                elif self._research:
                    res = runner.research_lyrics(p, cancel=self._cancel,
                                                 allow_cloud=self._allow_cloud)
                else:
                    res = runner.process(p, force=self._force, on_stage=self.stage.emit,
                                         cancel=self._cancel, models=item.models,
                                         allow_cloud=self._allow_cloud)
                if res.missing and last_missing.get(p) != frozenset(s.id for s in res.missing):
                    # The stage refused to run because a model is absent. Put the previous word
                    # timing back, pause, and let the window offer the download; this track is
                    # retried once the queue resumes. A second, different missing set (e.g. the
                    # next stage) asks again instead of failing the song.
                    last_missing[p] = frozenset(s.id for s in res.missing)
                    if moved:
                        runner.restore_sync(moved)
                    self.pause()
                    blocked = p
                    self.missing_models.emit(list(res.missing))
                    continue
                if moved:
                    if res.status in ("done", "review"):
                        runner.drop_sync_backup(moved)
                    else:
                        # failed/cancelled/skipped: nothing new was written, keep the old timing
                        runner.restore_sync(moved)
                row = read_status(p)
                if res.status == "failed":
                    row.status, row.error = "failed", res.error
                elif res.status == "cancelled":
                    row.status, row.error = "cancelled", res.error or "Stopped by the user"
                row.device, row.fallback = res.device, res.fallback
                row.notes = list(res.notes)
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
            index += 1


class MainWindow(QMainWindow):
    def __init__(self, root: Path = None, *, server: IpcServer | None = None,
                 startup: dict | None = None):
        super().__init__()
        self.root = Path(root or config.library_root())
        self._startup = startup
        self._setup_assistant: SetupAssistant | None = None
        self._first_run_scheduled = False
        self.rows: list[TrackRow] = []
        self.audio: Path | None = None
        self.doc: LrcDoc | None = None
        self.dirty = False
        self._threads: list[tuple[QThread, QObject]] = []
        self._queue: QueueWorker | None = None
        self._pending_queue: _PendingQueue | None = None
        self._preflight_running = False
        self._user_stopped_queue = False
        self._backlog_starting: tuple[list[Path], bool] | None = None
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
        self._install_request: _InstallRequest | None = None
        self._cancel_background = threading.Event()
        self._stop_at: int | None = None
        self._shown_line = -1
        self._pending_seek: int | None = None
        self._pending_play = False
        self._last_playback_error = ""
        self._paste_before: LrcDoc | None = None
        self._sample_elapsed = QElapsedTimer()
        self._sample_elapsed.start()
        self.karaoke_window: KaraokeWindow | None = None
        self._update_controller = UpdateController(self)
        self._models_window: ModelsWindow | None = None
        self._models_after_download: list[tuple[tuple, object]] = []
        self._duplicate_instance = False
        self.undo_stack = QUndoStack(self)
        app = QApplication.instance()
        if app is not None and not getattr(app, "_lyricloom_theme_watch", False):
            theme.apply_theme(app)
        install_shutdown_joins()
        self.setWindowTitle(config.APP_NAME)
        self.resize(1400, 850)
        self.setMinimumSize(640, 480)
        self._build_menu()
        self._build()
        self._restore_ui_state()
        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        self.player.durationChanged.connect(lambda d: self.seek.setRange(0, d))
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.errorOccurred.connect(self._media_error)
        self.player.positionChanged.connect(self._position_changed)
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        self.timer = QTimer(self, interval=50, timeout=self._tick)
        self.timer.start()
        self.refresh()
        self._ipc_server = server
        if self._ipc_server is None:
            self._ipc_server = IpcServer(parent=self)
        if not self._ipc_server.listen():
            # A crashed process can leave the name behind; a live but busy one answers a longer
            # retry. If it owns the name, do not open a second window.
            startup_command = startup if startup is not None else {"cmd": "activate"}
            if handle_busy_instance(self._ipc_server, startup_command):
                self._duplicate_instance = True
            elif not self._ipc_server.listen():
                LOG.warning("single-instance server %s could not listen", self._ipc_server.name)
        if self._ipc_server.is_listening:
            self._ipc_server.received.connect(self._external_message)
            self._ipc_server.set_ready()
            self._ipc_available = True
            # Only the primary instance may clean the update folder: a second process that is
            # about to hand its command over and exit must not delete the primary's download.
            # A file left there by an earlier run is never trusted.
            updater.cleanup_stale_downloads()
        else:
            self._ipc_available = False
            LOG.warning("single-instance server %s could not listen", self._ipc_server.name)
        if startup is not None:
            QTimer.singleShot(0, lambda: self._handle_external(startup))
        self._update_timer = QTimer(self, interval=updater.CHECK_INTERVAL_MS,
                                    timeout=self._periodic_update_check)
        self._update_timer.start()
        # Nothing is requested before the setup assistant finished; _setup_finished runs this
        # start-up check then.
        self._startup_check_scheduled = updater.should_check_on_startup()
        if self._startup_check_scheduled:
            QTimer.singleShot(4000, self._startup_update_check)
        QTimer.singleShot(0, self._show_pending_plugin_notice)

    def _startup_update_check(self) -> None:
        """The automatic start-up check (also run once when the setup assistant finishes)."""
        if updater.should_check_automatically():
            check_for_updates(self, silent=True)

    def _periodic_update_check(self) -> None:
        """The 24-hour re-check; a disabled or explicitly off check makes no request."""
        if updater.should_check_automatically():
            check_for_updates(self, silent=True)

    def _show_pending_plugin_notice(self) -> None:
        """Explain once that a silent update to this version left the MusicBee plugin alone."""
        if not updater.take_plugin_skip_notice():
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("MusicBee plugin not updated")
        box.setText("Starry Karaoke for MusicBee was not updated because MusicBee was open "
                    "(or LyricLoom could not check that it was closed).")
        box.setInformativeText(f"LyricLoom has been updated to {VERSION}. Close MusicBee, then "
                               "update the plugin from the setup assistant's MusicBee page.")
        open_page = box.addButton("Open the MusicBee page", QMessageBox.AcceptRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_page:
            self.open_setup_assistant("musicbee")

    def showEvent(self, event):
        """Run the first-start setup once the window is actually visible.

        Tests and embedded callers construct MainWindow without showing it; production calls
        ``show()`` in ``run()``.  Deferring the assistant to this point keeps a headless window from
        opening dialogs that nobody can see.
        """
        super().showEvent(event)
        if self._first_run_scheduled:
            return
        self._first_run_scheduled = True
        # An explicit root (tests, embedding) means the caller already chose the library; a normal
        # start uses config.library_root() and is the case the assistant is for.  Calling
        # _first_run() directly always opens it, which is also how the tests exercise the page.
        if self._startup is None and config.library_root() == self.root:
            QTimer.singleShot(0, self._first_run)

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("&File")
        act_library = QAction("Change &library…", self, shortcut=QKeySequence.Open, triggered=self.choose_library)
        act_save = QAction("&Save lyrics", self, shortcut=QKeySequence.Save, triggered=self.save)
        act_refresh = QAction("&Refresh library", self, shortcut=QKeySequence.Refresh, triggered=self.refresh)
        act_settings = QAction("&Settings…", self, shortcut=QKeySequence("Ctrl+,"), triggered=self.open_settings)
        act_quit = QAction("E&xit", self, shortcut=QKeySequence.Quit, triggered=self.close)
        for action in (act_library, act_save, act_refresh, act_settings):
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(act_quit)

        edit_menu = self.menuBar().addMenu("&Edit")
        self.act_undo = QAction("&Undo", self, shortcut=QKeySequence.Undo, triggered=self.undo_stack.undo)
        self.act_redo = QAction("&Redo", self, triggered=self.undo_stack.redo)
        self.act_redo.setShortcuts([QKeySequence(QKeySequence.Redo), QKeySequence("Ctrl+Shift+Z")])
        self.undo_stack.canUndoChanged.connect(self.act_undo.setEnabled)
        self.undo_stack.canRedoChanged.connect(self.act_redo.setEnabled)
        self.undo_stack.cleanChanged.connect(lambda clean: self._set_dirty(not clean))
        self.act_undo.setEnabled(False)
        self.act_redo.setEnabled(False)
        self.act_accept_line = QAction("&Accept line", self, shortcut=QKeySequence("Ctrl+Return"),
                                       triggered=self.accept_line)
        self.act_accept_all = QAction("Clear &review flags", self,
                                      shortcut=QKeySequence("Ctrl+Shift+Return"), triggered=self.accept_all)
        self.act_next_review = QAction("&Next review line", self, shortcut=QKeySequence("F3"),
                                       triggered=lambda: self.step_review(1))
        self.act_prev_review = QAction("&Previous review line", self, shortcut=QKeySequence("Shift+F3"),
                                       triggered=lambda: self.step_review(-1))
        self.act_delete_line = QAction("&Delete line", self, shortcut=QKeySequence.Delete,
                                       triggered=self.delete_current_line)
        self.act_delete_line.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        for action in (self.act_undo, self.act_redo):
            edit_menu.addAction(action)
        edit_menu.addSeparator()
        for action in (self.act_accept_line, self.act_accept_all, self.act_next_review, self.act_prev_review):
            edit_menu.addAction(action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_delete_line)

        playback_menu = self.menuBar().addMenu("&Playback")
        self.act_play_pause = QAction("&Play/pause", self, shortcut=QKeySequence("Space"),
                                      triggered=self.toggle_play)
        self.act_karaoke = QAction("&Karaoke", self, shortcut=QKeySequence("Ctrl+K"),
                                   triggered=self.open_karaoke)
        self.act_find = QAction("&Find in library", self, shortcut=QKeySequence.Find,
                                triggered=self._focus_search)
        playback_menu.addAction(self.act_play_pause)
        playback_menu.addAction(self.act_karaoke)
        playback_menu.addSeparator()
        playback_menu.addAction(self.act_find)

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(QAction("&Setup assistant…", self,
                                     triggered=lambda: self.open_setup_assistant()))
        help_menu.addAction(QAction("&Models…", self, triggered=lambda: self.open_models()))
        help_menu.addAction(QAction("Check for &updates…", self, triggered=lambda: check_for_updates(self)))
        help_menu.addAction(QAction("Open &data folder", self, triggered=self.open_data_folder))
        help_menu.addAction(QAction("Open &log folder", self, triggered=self.open_log_folder))
        help_menu.addSeparator()
        help_menu.addAction(QAction("&Diagnostics…", self, triggered=self.show_diagnostics))
        help_menu.addSeparator()
        help_menu.addAction(QAction("&About LyricLoom", self, triggered=self.show_about))

    def _focus_search(self):
        self.search.setFocus(Qt.ShortcutFocusReason)
        self.search.selectAll()

    def _first_run(self):
        """First start (or an upgrade from 2.0): the setup assistant, once."""
        if not config.setting("setup_complete", False):
            self.open_setup_assistant()
            return
        if config.setting("library") or self.root != Path(config.DEFAULT_LIBRARY):
            return
        QMessageBox.information(
            self, "Welcome to LyricLoom",
            "Choose the folder that contains your music. LyricLoom scans its subfolders and writes "
            "the .lrc next to each audio file.\n\n"
            "LyricLoom never downloads a model while it processes songs: it offers the suggested "
            "models next, and Help > Models manages them at any time.")
        self.choose_library()
        QTimer.singleShot(200, self._offer_models)

    def open_setup_assistant(self, start_page: str | None = None) -> SetupAssistant:
        """Opens (or re-raises) the setup assistant, optionally on one page."""
        dialog = self._setup_assistant
        if dialog is None:
            dialog = SetupAssistant(self, start_page=start_page)
            self._setup_assistant = dialog
            dialog.finished.connect(self._setup_finished)
        elif start_page is not None:
            page_id = PAGE_KEYS.get(str(start_page).lower())
            if page_id is not None:
                dialog.setCurrentPage(page_id)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def _setup_finished(self, _result: int) -> None:
        dialog, self._setup_assistant = self._setup_assistant, None
        if dialog is not None:
            dialog.deleteLater()
        new_root = config.library_root()
        if new_root != self.root:
            self.root = new_root
            self.rows = []
            self._restored_last_track = True
            self.refresh()
        self._set_script_combo(config.japanese_script())
        self._update_cloud_indicator()
        if _result == QDialog.Accepted:
            self.statusBar().showMessage("Setup complete.", 8000)
            if not self._startup_check_scheduled and updater.should_check_on_startup():
                # The owner has now seen the update choice: run the start-up check once.
                self._startup_check_scheduled = True
                self._startup_update_check()

    def _offer_models(self):
        def check():
            return runtime.status(), runtime._nltk_ready()

        self._run(FuncWorker(check), self._offer_models_checked, self._offer_models_failed)

    def _offer_models_checked(self, result) -> None:
        missing, nltk_ready = result
        if all(missing.values()) and nltk_ready:
            return
        answer = QMessageBox.question(
            self, "Download models?",
            "LyricLoom needs about 5.3 GB of models for the full pipeline:\n\n"
            "  Whisper large-v3 (3.1 GB), vocal separator (0.9 GB),\n"
            "  MMS forced alignment (1.2 GB), English singing model (66 MB).\n\n"
            "Download them now? You can also do this later from Help > Models; "
            "songs that need a missing model will ask again.")
        if answer == QMessageBox.Yes:
            self.open_models()

    def _offer_models_failed(self, message: str) -> None:
        LOG.warning("could not check the models for the first-run offer: %s", message)

    def open_settings(self):
        previous_script = config.japanese_script()
        dialog = SettingsDialog(self)
        if dialog.exec() != dialog.Accepted:
            return
        self.root = config.library_root()
        self.rows = []
        self._update_cloud_indicator()
        new_script = config.japanese_script()
        message = "Settings saved. Restart LyricLoom to apply cache/GPU changes."
        if new_script != previous_script:
            try:
                count = apply_script_preference(self.root, script=new_script, dry_run=True)
            except OSError as exc:
                self._show_io_error("Update the Japanese script", self.root, exc)
                count = 0
            if count and not self._confirm_script_rewrite(new_script, count):
                try:
                    config.set_japanese_script(previous_script)
                except OSError as exc:
                    self._show_io_error("Restore the Japanese script setting", config.SETTINGS_FILE, exc)
                new_script = previous_script
                message = "Settings saved. The Japanese script was left unchanged."
            else:
                try:
                    n = apply_script_preference(self.root, script=new_script)
                except OSError as exc:
                    self._show_io_error("Update the Japanese script", self.root, exc)
                else:
                    message = f"Japanese lyrics now in {new_script}: {n} song(s) updated"
        self._set_script_combo(new_script)
        divisor = config.smooth_animation_divisor()
        self.now.set_divisor(divisor)
        if self.karaoke_window is not None:
            self.karaoke_window.set_animation_divisor(divisor)
        self.refresh()
        self.statusBar().showMessage(message, 8000)
        if getattr(dialog, "assistant_page", None):
            self.open_setup_assistant(dialog.assistant_page)

    def _set_script_combo(self, script: str) -> None:
        self.script.blockSignals(True)
        self.script.setCurrentIndex(1 if script == "romaji" else 0)
        self.script.blockSignals(False)

    def _confirm_script_rewrite(self, script: str, count: int) -> bool:
        answer = QMessageBox.question(
            self, "Japanese script",
            f"Rewrite the main .lrc of {count} Japanese song(s) to {script}?\n\n"
            "The two script variants are kept. Each changed .lrc gets the usual .bak copy first.")
        return answer == QMessageBox.Yes

    def open_models(self, specs: list | None = None, download: bool = False,
                    on_finished=None) -> ModelsWindow:
        """Opens (or reuses) the Models window, optionally selecting and downloading models."""
        if self._models_window is None:
            self._models_window = ModelsWindow(self)
            self._models_window.downloads_finished.connect(self._models_downloads_finished)
            self._models_window.choices_changed.connect(self._models_choices_changed)
        window = self._models_window
        added = on_finished is not None
        entry = (tuple(specs or ()), on_finished)
        if added:
            self._models_after_download.append(entry)
        window.show()
        window.raise_()
        window.activateWindow()
        if specs:
            window.select_specs(specs)
            if download and not window.start_download(specs) and added:
                # The job never started (another one is running, or not enough disk space):
                # do not leave a callback that a later, unrelated job would run.
                try:
                    self._models_after_download.remove(entry)
                except ValueError:
                    pass
        return window

    def _models_downloads_finished(self, ok: bool) -> None:
        entries, self._models_after_download = self._models_after_download, []
        if not entries:
            return
        if not ok:
            for _specs, callback in entries:
                callback(False)
            return
        requested: list = []
        seen: set[str] = set()
        for specs, _callback in entries:
            for spec in specs:
                if spec.id not in seen:
                    seen.add(spec.id)
                    requested.append(spec)
        if not requested:
            for _specs, callback in entries:
                callback(True)
            return

        def check():
            return model_status.snapshot(requested)

        relay = _ModelCheckRelay(self, entries)
        self._run(FuncWorker(check), relay.done, relay.failed)

    def _models_ready(self, entries: list, states: dict[str, str]) -> None:
        for specs, callback in entries:
            callback(all(model_status.usable(states.get(spec.id)) for spec in specs))

    def _models_check_failed(self, entries: list, message: str) -> None:
        LOG.warning("could not check the models after a download: %s", message)
        for _specs, callback in entries:
            callback(False)

    def _models_choices_changed(self) -> None:
        """A new default or language choice changes the "made with other models" marker."""
        self.model.invalidate_models()
        self.proxy.invalidate()

    def _ask_missing_models(self, specs: list) -> str:
        """The preflight/mid-queue dialog. Kept separate so tests can answer without a dialog."""
        dialog = MissingModelsDialog(specs, self)
        dialog.exec()
        return dialog.choice

    def _offer_missing_models(self, specs: list, on_download=None) -> str:
        choice = self._ask_missing_models(specs)
        if choice == "download":
            self.open_models(specs, download=True, on_finished=on_download)
        elif choice == "models":
            self.open_models(specs, on_finished=on_download)
        return choice

    def _required_models(self, overrides: dict[str, str] | None = None,
                         stages: tuple[str, ...] = ("transcribe", "separate", "align")) -> list:
        """The models a queue could use: every default plus every language choice in use.

        The NLTK data and the optional singing model are not blockers: the align stage falls back to
        CTC when they are absent, so including them here would refuse a queue that can run. A Redo
        only runs the alignment stage, so it only needs the alignment model.
        """
        choices = config.model_choices()
        override = dict(overrides or {})
        specs, seen = [], set()

        def add(stage: str, lang: str | None = None) -> None:
            spec = model_catalog.resolve(stage, lang=lang, overrides=override, choices=choices)
            if spec.id not in seen:
                seen.add(spec.id)
                specs.append(spec)

        for stage in stages:
            add(stage)
        languages = choices.get("languages") if isinstance(choices.get("languages"), dict) else {}
        for lang, entry in languages.items():
            if not isinstance(entry, dict):
                continue
            for stage in stages:
                if stage in entry and stage not in override:
                    add(stage, str(lang))
        return specs

    def _preflight(self, paths: list[Path], redo: bool,
                   overrides: dict[str, str] | None = None, *, research: bool = False) -> bool | None:
        """Checks the required models off the GUI thread.

        ``False`` means another check is already running, ``True`` means no check is needed and
        ``None`` means a worker was started; ``_preflight_checked`` will start or refuse the queue.
        Model files can be several gigabytes, so ``models.status`` must never run in this slot
        (FRB-04).
        """
        if self._preflight_running:
            self.statusBar().showMessage("A model check is already running.", 5000)
            return False
        stages = ("align",) if redo or research else ("transcribe", "separate", "align")

        def check():
            specs = self._required_models(overrides, stages)
            return specs, model_status.snapshot(specs)

        self._preflight_running = True
        self.statusBar().showMessage("Checking the models…")
        self._run(FuncWorker(check), self._preflight_checked, self._preflight_failed)
        return None

    def _preflight_checked(self, result) -> None:
        self._preflight_running = False
        pending, self._pending_queue = self._pending_queue, None
        if pending is None:
            return
        specs, states = result
        missing = [spec for spec in specs if states.get(spec.id) in ("missing", "corrupt")]
        if not missing:
            self._start_queue(pending)
            return

        def downloaded(ok: bool) -> None:
            if ok:
                if pending.from_backlog:
                    self._backlog_starting = (list(pending.paths), pending.redo)

                def retry() -> None:
                    if not self.process(pending.paths, redo=pending.redo,
                                        research=pending.research, models=pending.models):
                        self._backlog_starting = None

                QTimer.singleShot(0, retry)

        self._offer_missing_models(missing, downloaded)
        self.statusBar().showMessage("The queue was not started: some models are missing.", 8000)

    def _preflight_failed(self, message: str) -> None:
        self._preflight_running = False
        self._pending_queue = None
        LOG.warning("model check failed: %s", message)
        self.statusBar().showMessage("The queue was not started: the model check failed — "
                                     + message, 12000)

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
        root = self.root

        def build():
            return diagnostics_text(root)

        self._run(FuncWorker(build), self._show_diagnostics_text, self._diagnostics_failed)

    def _show_diagnostics_text(self, text: str) -> None:
        DiagnosticsDialog(text, self).exec()

    def _diagnostics_failed(self, message: str) -> None:
        LOG.warning("could not build the diagnostics report: %s", message)
        QMessageBox.warning(self, "Diagnostics", "Could not build the report:\n" + message)

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
        self.search = QLineEdit(placeholderText="Search artist / title / status / models")
        top.addWidget(self.filter)
        top.addWidget(self.search)
        self.script.setAccessibleName("Japanese lyric script")
        self.filter.setAccessibleName("Status filter")
        self.search.setAccessibleName("Search library")
        self.search.setAccessibleDescription("Filters by artist, title or status")
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
        self.model = TrackTableModel(self.rows, self, device_text=self._device_text)
        self.proxy = TrackFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_context_menu)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setAccessibleName("Library tracks")
        self.table.setAccessibleDescription("Artist, title, status, source, confidence and notes")
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
        self.seek = SeekSlider()
        self.time_label = QLabel("00:00.00")
        self.vocals = QCheckBox("Vocals only")
        self.btn_karaoke = QPushButton("Karaoke")
        self.btn_karaoke.setToolTip("Open the full-screen karaoke player for the selected track")
        self.seek.setAccessibleName("Playback position")
        self.seek.setToolTip("Seek: click to jump, drag to scrub")
        self.vocals.setToolTip("Play the isolated vocals instead of the full mix when they exist")
        for w in (self.btn_play, self.seek, self.time_label, self.vocals, self.btn_karaoke):
            pl.addWidget(w)
        rv.addLayout(pl)
        self.now = LyricView(compact=True)
        self.now.setMinimumHeight(64)
        self.now.setAccessibleName("Current lyric line")
        rv.addWidget(self.now)
        self.lines = QListWidget()
        self.lines.setAccessibleName("Lyric lines")
        self.lines.setAccessibleDescription("Select a line to edit its words")
        rv.addWidget(self.lines, 3)
        self.words = QTableWidget(0, 3)
        self.words.setHorizontalHeaderLabels(["Word", "Start", "End"])
        self.words.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.words.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.words.setAccessibleName("Word timing")
        self.words.setAccessibleDescription("Word text, start time and end time")
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
        self.btn_delete.setToolTip("Delete the selected line (Ctrl+Z undoes it)")
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
        ed3 = QHBoxLayout()
        self.btn_accept_line = QPushButton("Accept line")
        self.btn_accept_line.setToolTip("Clear this line's review flag and save (Ctrl+Enter)")
        self.btn_accept_all = QPushButton("Accept all")
        self.btn_accept_all.setToolTip("Clear every review flag and save (Ctrl+Shift+Enter)")
        self.btn_prev_review = QPushButton("Previous review")
        self.btn_prev_review.setToolTip("Select the previous line flagged for review (Shift+F3)")
        self.btn_next_review = QPushButton("Next review")
        self.btn_next_review.setToolTip("Select the next line flagged for review (F3)")
        for w in (self.btn_accept_line, self.btn_accept_all, self.btn_prev_review, self.btn_next_review):
            ed3.addWidget(w)
        rv.addLayout(ed3)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([620, 780])
        self.splitter = split
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        self.update_bar = UpdateBar(central)
        central_layout.addWidget(self.update_bar)
        central_layout.addWidget(split, 1)
        self.setCentralWidget(central)

        self.filter.currentIndexChanged.connect(self._apply_filter)
        self._search_timer = QTimer(self, singleShot=True, interval=200, timeout=self._apply_search)
        self.search.textChanged.connect(lambda _text: self._search_timer.start())
        self.table.selectionModel().selectionChanged.connect(self._on_track_selected)
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
        self.progress.setAccessibleName("Track progress")
        self.progress.setAccessibleDescription("Progress of the current track through the processing stages")
        self.progress.setStyleSheet("QProgressBar { text-align: center; }"
                                    "QProgressBar::chunk { background-color: #2e9d4f; }")
        self.progress.hide()
        self.gpu = QLabel(self._device_text(""))
        self._gpu_tip = ("Where the heavy stages run. Separation and forced alignment can use a GPU "
                         "through ROCm inside WSL on Windows, or CUDA/ROCm on Linux; otherwise they "
                         "fall back to the CPU. Transcription uses whisper.cpp. "
                         "Updated as songs are processed.")
        self.gpu.setToolTip(self._gpu_tip)
        self.cloud = QLabel("")
        self.cloud.setToolTip("Cloud transcription is on: songs that need help may upload their "
                              "isolated vocal to AssemblyAI. Turn it off in Settings > Privacy.")
        self.cloud.hide()
        self.statusBar().addPermanentWidget(self.cloud)
        self.statusBar().addPermanentWidget(self.gpu)
        self.statusBar().addPermanentWidget(self.progress)
        self._update_cloud_indicator()
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
        self.seek.sliderReleased.connect(self._seek_released)
        self.seek.sliderMoved.connect(self._seek_moved)
        self.seek.valueChanged.connect(self._seek_changed)
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
        self.btn_accept_line.clicked.connect(self.accept_line)
        self.btn_accept_all.clicked.connect(self.accept_all)
        self.btn_prev_review.clicked.connect(lambda: self.step_review(-1))
        self.btn_next_review.clicked.connect(lambda: self.step_review(1))
        self.lines.addAction(self.act_delete_line)   # Delete only while the line list has focus
        self._set_tab_order()

    def _set_tab_order(self) -> None:
        chain = [
            self.btn_library, self.btn_settings, self.btn_key, self.script, self.filter, self.search,
            self.table, self.btn_refresh, self.btn_sel, self.btn_pending, self.btn_redo, self.btn_details,
            self.btn_stop, self.btn_stop_now, self.btn_pause, self.force, self.btn_play, self.seek,
            self.vocals, self.btn_karaoke, self.lines, self.words, *self.nudges, self.btn_line,
            self.btn_delete, self.btn_paste, self.btn_save, self.btn_add_word, self.btn_del_word,
            self.btn_add_line, self.btn_merge, self.btn_accept_line, self.btn_accept_all,
            self.btn_prev_review, self.btn_next_review,
        ]
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)

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
        thread.finished.connect(_ThreadFinishedRelay(
            lambda: self._thread_finished(thread), self).run)
        self._threads.append((thread, worker))
        thread.start()

    @Slot(object)
    def _thread_finished(self, thread: QThread) -> None:
        """Removes a finished worker's bookkeeping on the GUI thread (FRB-11)."""
        self._threads = [(t, w) for t, w in self._threads if t is not thread]

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
        cancel = self._cancel_background

        def scan():
            stats: dict = {}
            return root, scan_cached(root, stats, cancel=cancel), stats

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
            if not row.notes:
                row.notes = old.notes
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
        state = "a key is set" if config.has_assemblyai_key() else "no key set"
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
        self.statusBar().showMessage("AssemblyAI key saved" if key.strip() else "AssemblyAI key removed", 5000)

    def set_script(self, script: str):
        previous = config.japanese_script()
        if script == previous:
            return
        try:
            count = apply_script_preference(self.root, script=script, dry_run=True)
        except OSError as exc:
            self._show_io_error("Update the Japanese script", self.root, exc)
            self._set_script_combo(previous)
            return
        if count and not self._confirm_script_rewrite(script, count):
            self._set_script_combo(previous)
            return
        try:
            config.set_japanese_script(script)
            n = apply_script_preference(self.root, script=script)
        except OSError as exc:
            try:
                config.set_japanese_script(previous)
            except OSError:
                pass
            self._show_io_error("Update the Japanese script", self.root, exc)
            self._set_script_combo(previous)
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
        reason = os_error_text(exc)
        message = f"{action} failed:\n{path}\n\n{reason}"
        self.statusBar().showMessage(f"{action} failed: {reason}", 12000)
        QMessageBox.critical(self, action, message)

    def _visible_rows(self) -> list[TrackRow]:
        """The rows the user can see, in the table's current sort order."""
        rows = []
        for i in range(self.proxy.rowCount()):
            source = self.proxy.mapToSource(self.proxy.index(i, 0))
            rows.append(self.model.row_at(source.row()))
        return rows

    def _apply_filter(self) -> None:
        self.proxy.set_status_filter(FILTERS[self.filter.currentIndex()])

    def _apply_search(self) -> None:
        self.proxy.set_search_text(self.search.text())

    def _fill_table(self):
        """Shows the current row list. The model resets once per scan, not per keystroke or track."""
        current = self._current_path()
        self.model.set_rows(self.rows)
        self._apply_filter()
        self.proxy.set_search_text(self.search.text())
        if current is not None:
            self._select_path(current, prompt=False)

    def _current_path(self) -> Path | None:
        selection = self.table.selectionModel()
        if selection is not None:
            indexes = selection.selectedRows()
            if indexes:
                source = self.proxy.mapToSource(indexes[0])
                return self.model.row_at(source.row()).path
        return self.audio

    def _selected_rows(self) -> list[TrackRow]:
        selection = self.table.selectionModel()
        if selection is None:
            return []
        rows = []
        for index in selection.selectedRows():
            source = self.proxy.mapToSource(index)
            rows.append(self.model.row_at(source.row()))
        return rows

    def _update_row(self, row: TrackRow):
        for i, r in enumerate(self.rows):
            if r.path == row.path:
                self.rows[i] = row
                break
        else:
            self.rows.append(row)
        self.model.update_row(row)

    def _ensure_rows(self, paths: list[Path]) -> None:
        """Adds rows for files that are not in the current scan (e.g. --process outside the library)."""
        known = {r.path for r in self.rows}
        for path in paths:
            if path in known:
                continue
            try:
                row = read_status(path)
            except Exception as exc:  # noqa: BLE001 - a transient row must not break the window
                row = TrackRow(path, path.parent.name, path.stem, "pending",
                               error=f"could not read this file: {type(exc).__name__}: {exc}")
            self.rows.append(row)
            self.model.update_row(row)
            known.add(path)

    def _select_path(self, path: Path, *, prompt: bool = True) -> bool:
        try:
            wanted = str(Path(path).resolve())
        except (OSError, RuntimeError):
            wanted = str(path)
        for source_row, row in enumerate(self.model.rows):
            try:
                value = str(row.path.resolve())
            except (OSError, RuntimeError):
                value = str(row.path)
            if value != wanted:
                continue
            index = self.proxy.mapFromSource(self.model.index(source_row, 0))
            if not index.isValid():
                return False   # hidden by the current filter or search
            if prompt and not self._confirm_discard():
                return False
            self.table.selectRow(index.row())
            self.table.scrollTo(index, QAbstractItemView.PositionAtCenter)
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
            self._search_timer.stop()
            self._apply_search()
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
        if self._queue is not None or self._pending_queue is not None:
            self._external_backlog.append((paths, redo))
            self.statusBar().showMessage(
                f"{len(paths)} track(s) queued; they start when the current queue ends", 8000)
            return
        if not self.process(paths, redo=redo):
            self.statusBar().showMessage("Could not start the queued track(s)", 8000)

    def _ask_open_outside_library(self, path: Path) -> str:
        """Asks whether an outside folder is only shown now or becomes the saved library (FRB-10)."""
        box = QMessageBox(self)
        box.setWindowTitle("Open outside the library")
        box.setIcon(QMessageBox.Question)
        box.setText(f"{path.name} is outside your library:\n{self.root}")
        box.setInformativeText(
            "Show its folder for this session, or make that folder your saved music library?\n\n"
            "Only the saved choice is used the next time LyricLoom starts.")
        current = box.addButton("Show for this session", QMessageBox.ActionRole)
        save = box.addButton("Use this folder as my library", QMessageBox.AcceptRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(current)
        box.exec()
        if box.clickedButton() is save:
            return "library"
        if box.clickedButton() is current:
            return "session"
        return "cancel"

    def open_external(self, path: Path) -> None:
        path = Path(path).resolve()
        self._bring_to_front()
        try:
            inside = path.is_relative_to(self.root.resolve())
        except (OSError, RuntimeError, ValueError):
            inside = False
        if not inside:
            choice = self._ask_open_outside_library(path)
            if choice == "cancel":
                self.statusBar().showMessage(f"{path.name} is outside the library", 8000)
                return
            if choice == "library":
                try:
                    config.set_library_root(path.parent)
                except OSError as exc:
                    self._show_io_error("Save the library setting", config.SETTINGS_FILE, exc)
            self.root = path.parent
            self.rows = []
            self._pending_select = path
            self.refresh()
            suffix = "" if choice == "library" else " (this session only)"
            self.statusBar().showMessage(f"Showing {path.name} from {self.root}{suffix}", 8000)
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
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        source = self.proxy.mapToSource(index)
        row = self.model.row_at(source.row())
        path = row.path
        menu = QMenu(self)
        act_process = menu.addAction("Process")
        act_other_models = menu.addAction("Process with other models…")
        act_current = menu.addAction("Redo with current models")
        act_current.setEnabled(bool(other_model_stages(row)))
        act_redo = menu.addAction("Redo word timing")
        act_search = menu.addAction("Search lyrics again")
        act_details = menu.addAction("Details…")
        act_vocals = menu.addAction("Save isolated vocals…")
        # Greyed out until the song has been processed: there are no isolated vocals to save yet.
        act_vocals.setEnabled(vocal_source(path) is not None)
        menu.addSeparator()
        act_folder = menu.addAction("Open folder")
        act_copy = menu.addAction("Copy path")
        act_log = menu.addAction("Open log")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        selected = [r.path for r in self._selected_rows()]
        paths = selected if path in selected else [path]
        if chosen is act_process:
            self.process([path])
        elif chosen is act_other_models:
            self._process_with_other_models(paths)
        elif chosen is act_current:
            self._redo_with_current_models(path)
        elif chosen is act_redo:
            self._redo_paths([path])
        elif chosen is act_search:
            self.process([path], research=True)
        elif chosen is act_details:
            self.table.selectRow(index.row())
            self.show_details()
        elif chosen is act_vocals:
            self.save_isolated_vocals(paths)
        elif chosen is act_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        elif chosen is act_copy:
            QApplication.clipboard().setText(str(path))
            self.statusBar().showMessage("Path copied", 3000)
        elif chosen is act_log:
            self._open_track_log(row)

    def save_isolated_vocals(self, paths: list[Path]) -> None:
        """Writes ``<song>_vocal.flac`` for the given songs from the vocals LyricLoom already has.

        The place is the one chosen in Settings; with the automatic copies turned off, the user
        picks a folder for this one time.  A file of that name that LyricLoom did not write is
        never replaced."""
        mode = config.vocal_export_mode()
        folder: Path | None = None
        if vocal_export.target(paths[0]) is None:
            chosen = QFileDialog.getExistingDirectory(
                self, "Save the isolated vocals in", str(paths[0].parent))
            if not chosen:
                return
            mode, folder = "folder", Path(chosen)
        saved: list[Path] = []
        missing = 0
        problems: list[str] = []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for audio in paths:
                source = vocal_source(audio)
                if source is None:
                    missing += 1
                    continue
                try:
                    destination = vocal_export.target(audio, mode, folder)
                    saved.append(vocal_export.export(audio, source, destination=destination))
                except Exception as exc:  # noqa: BLE001 - one song must not stop the others
                    problems.append(f"{audio.name}: {message_text(exc)}")
                QApplication.processEvents()
        finally:
            QApplication.restoreOverrideCursor()
        parts = []
        if saved:
            where = saved[0].parent if len({p.parent for p in saved}) == 1 else "their folders"
            parts.append(f"Saved {len(saved)} vocal file(s) in {where}")
        if missing:
            parts.append(f"{missing} song(s) have no isolated vocals yet (process them first)")
        if problems:
            parts.append(f"{len(problems)} could not be saved")
        self.statusBar().showMessage("; ".join(parts) or "Nothing to save", 12000)
        if problems:
            QMessageBox.warning(self, "Save isolated vocals", "\n\n".join(problems[:8]))

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
            for i, width in enumerate(columns[:self.model.columnCount()]):
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
            "table/columns": [self.table.columnWidth(i) for i in range(self.model.columnCount())],
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

    def _process_with_other_models(self, paths: list[Path]):
        """The per-song model dialog: one combo per stage plus a language shortcut."""
        if not paths or self._queue is not None:
            return
        dialog = PerSongModelsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.process(paths, models=dialog.chosen_models())

    def _redo_with_current_models(self, path: Path):
        """Re-runs every stage with what the current choices resolve, replacing the [#models] set."""
        if self._queue is not None:
            return
        self.process([path], force=True)

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
            self._reload_lrc()
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

    def _take_backlog_marker(self, paths: list[Path], redo: bool) -> bool:
        """True when this process() call is the external batch consumed from the backlog."""
        marker, self._backlog_starting = self._backlog_starting, None
        if marker is None:
            return False
        batch_paths, batch_redo = marker
        return batch_redo == redo and list(batch_paths) == list(paths)

    def process(self, paths: list[Path], redo: bool = False, research: bool = False,
                models: dict[str, str] | None = None, force: bool = False) -> bool:
        """Accepts a queue and checks the models in a worker before starting it.

        Returns True when the request was accepted. A queued request may still be refused after
        the check (missing models) just as before, but the GUI never hashes a model itself.
        """
        if not paths or self._queue is not None or self._pending_queue is not None:
            return False
        if not self._validate_folders():
            return False
        paths = self._confirm_open_track(paths, redo)
        if not paths:
            return False
        from_backlog = self._take_backlog_marker(paths, redo)
        self._pending_queue = _PendingQueue(list(paths), redo, research, models,
                                            from_backlog=from_backlog, force=force)
        checked = self._preflight(paths, redo, models, research=research)
        pending = self._pending_queue
        if checked is True and pending is not None:
            self._pending_queue = None
            return self._start_queue(pending)
        if checked is False:
            self._pending_queue = None
            return False
        return True

    def _start_queue(self, pending: _PendingQueue) -> bool:
        if pending.from_backlog:
            for index, (batch_paths, batch_redo) in enumerate(self._external_backlog):
                if batch_redo == pending.redo and list(batch_paths) == list(pending.paths):
                    self._external_backlog.pop(index)
                    break
        self._user_stopped_queue = False
        self._queue_error = ""
        self._queue_results = []
        self._queue_started = time.monotonic()
        allow_cloud = self._cloud_choice_for_queue()
        items = [QueueItem(path, pending.models) for path in pending.paths]
        self._queue = QueueWorker(items, self.force.isChecked() or pending.force, pending.redo,
                                  pending.research, allow_cloud=allow_cloud)
        self._prog = {"done": 0, "total": len(pending.paths), "name": "", "stage": "lyrics",
                      "since": time.monotonic(), "dur": 240.0}
        q = self._queue
        q.track_started.connect(self._track_started)
        q.stage.connect(self._stage_changed)
        q.device.connect(self._device_changed)
        q.track_done.connect(self._track_finished)
        q.queue_error.connect(self._queue_error_received)
        q.missing_models.connect(self._queue_missing_models)
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
        selected = gpu_runtime.selected()
        if selected:
            return "Device: " + {"cuda": "CUDA", "directml": "DirectML"}[selected]
        return (f"Device: ROCm (WSL {config.SEPARATOR_WSL_DISTRO})"
                if config.SEPARATOR_WSL_ENABLED else "Device: CPU")

    def _update_cloud_indicator(self) -> None:
        """A permanent status-bar badge while cloud transcription is enabled (R2-29)."""
        label = getattr(self, "cloud", None)
        if label is None:
            return
        enabled = config.assemblyai_enabled()
        label.setText("Cloud transcription: on" if enabled else "")
        label.setStyleSheet("color: #8a4b00;" if enabled else "")
        label.setVisible(enabled)

    def _ask_cloud_for_queue(self) -> bool:
        """Per-queue consent. Returns True when this queue may upload."""
        box = QMessageBox(self)
        box.setWindowTitle("Cloud transcription")
        box.setIcon(QMessageBox.Question)
        box.setText("Allow uploads for this queue?")
        box.setInformativeText(
            "Cloud transcription is on. For songs that need help, LyricLoom would upload the "
            "isolated vocal (16 kHz WAV), the language code and an artist/title prompt to "
            "AssemblyAI. Local transcription still runs first.\n\n"
            "Choose “Process without cloud” to keep this queue on this computer.")
        allow = box.addButton("Allow uploads for this queue", QMessageBox.AcceptRole)
        local = box.addButton("Process without cloud", QMessageBox.RejectRole)
        box.setDefaultButton(local)
        box.exec()
        return box.clickedButton() is allow

    def _cloud_choice_for_queue(self) -> bool | None:
        """``None`` means the saved setting decides; True/False consent is fixed for this queue."""
        if not config.assemblyai_enabled():
            return None
        if not config.ask_before_upload():
            return None
        return self._ask_cloud_for_queue()

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
            self._user_stopped_queue = True
            self._queue.stop()
            self.statusBar().showMessage("Stopping after the current track …")

    def _stop_now(self):
        if self._queue:
            self._user_stopped_queue = True
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

    def _queue_missing_models(self, specs: list):
        """A track stopped on MissingModels: pause the queue, offer the download, resume on success."""
        if self._queue is None:
            return
        self._queue.pause()
        self.btn_pause.setText("Resume")
        self.btn_pause.setEnabled(True)
        names = ", ".join(spec.label for spec in specs)
        self.statusBar().showMessage(f"Queue paused: missing models ({names})", 12000)

        def downloaded(ok: bool) -> None:
            if ok and self._queue is not None:
                self._queue.resume()
                self.btn_pause.setText("Pause after this song")
                self.statusBar().showMessage("Models ready; resuming the queue …", 8000)

        self._offer_missing_models(specs, downloaded)

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

        if (self._external_backlog and self._install_request is None
                and not self._quit_after_queue and not self._user_stopped_queue
                and self._pending_queue is None):
            paths, redo = self._external_backlog[0]
            self.statusBar().showMessage(
                f"Starting the next queued batch ({len(paths)} track(s)) …", 5000)
            self._backlog_starting = (list(paths), redo)
            if self.process(paths, redo=redo):
                if self._backlog_starting is not None:
                    # A stubbed or synchronous process() start did not consume the marker.
                    self._backlog_starting = None
                    self._external_backlog.pop(0)
            else:
                # Process refused to start it; keep the batch for the next attempt instead of
                # silently dropping songs MusicBee already counted as accepted (FRB-09).
                self._backlog_starting = None
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
        if self._quit_after_queue:   # an install request, if any, starts at the end of this close
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
        self._pending_seek = None
        self._pending_play = False
        self._last_playback_error = ""
        self.now.clear()
        self._update_vocals_control(reset=True)
        self._set_source(restore=False)
        self.track_label.setText(f"{audio.parent.parent.name} — {audio.stem}")
        self._reload_lrc()

    def _reload_if_current(self, path: Path):
        if path == self.audio and not self.dirty:
            self._reload_lrc()
            self._update_vocals_control(reset=False)
        window = self.karaoke_window
        if window is not None and window.audio == path:
            # A redo or a fresh run changed the lyrics on disk while the karaoke window showed
            # the old word timing (FRB-12).
            window.reload_lyrics()

    def _reload_lrc(self):
        # Japanese songs are edited in Japanese script; saving rebuilds the romaji version from it.
        lrc = japanese_path(self.audio) if japanese_path(self.audio).exists() else self.audio.with_suffix(".lrc")
        self.doc = parse_lrc(lrc.read_text(encoding="utf-8")) if lrc.exists() else None
        self.undo_stack.clear()
        self._set_dirty(False)
        self.now.set_doc(self.doc)
        self._fill_lines()

    def _update_vocals_control(self, *, reset: bool) -> None:
        source = vocal_source(self.audio) if self.audio is not None else None
        self.vocals.blockSignals(True)
        if reset:
            self.vocals.setChecked(False)
        elif source is None:
            self.vocals.setChecked(False)
        self.vocals.setEnabled(source is not None)
        self.vocals.blockSignals(False)
        self.vocals.setToolTip(
            f"Play the isolated vocals cached for this track:\n{source}" if source is not None
            else "No isolated vocals are cached for this track yet.\n"
                 "Run the song through LyricLoom once to create them.")

    def _set_source(self, restore: bool = True):
        if not self.audio:
            return
        source = self.audio
        if self.vocals.isChecked():
            source = vocal_source(self.audio) or self.audio
        if restore:
            # setSource() reloads the file and loses the position; remember it until the new media
            # is ready instead of seeking immediately (the loader discards that seek).
            self._pending_seek = self.player.position()
            self._pending_play = self.player.playbackState() == QMediaPlayer.PlayingState
        self.player.setSource(QUrl.fromLocalFile(str(source)))

    def _media_status(self, status):
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            if self._pending_seek is None:
                return
            position, playing = self._pending_seek, self._pending_play
            self._pending_seek = None
            self._pending_play = False
            self.player.setPosition(position)
            if playing:
                self.player.play()
        elif status == QMediaPlayer.EndOfMedia:
            self._pending_seek = None
            self._pending_play = False
            self.player.setPosition(0)
            self.btn_play.setText("Play")
        elif status == QMediaPlayer.InvalidMedia:
            message = self.player.errorString() or "The media could not be loaded"
            self._report_playback_error(message)

    def _media_error(self, error, message: str):
        if error == QMediaPlayer.NoError:
            return
        self._pending_seek = None
        self._pending_play = False
        self._report_playback_error(message or self.player.errorString() or "Unknown playback error")

    def _report_playback_error(self, message: str) -> None:
        if message == self._last_playback_error:
            return
        self._last_playback_error = message
        self.statusBar().showMessage(f"Playback error: {message}", 12000)
        LOG.warning("playback error for %s: %s", self.audio, message)

    def _seek_changed(self, value: int):
        # A click on the groove changes the value without emitting sliderMoved; a drag is handled
        # by sliderMoved for live scrubbing, and the timer blocks its own updates.
        if not self.seek.isSliderDown():
            self.player.setPosition(value)

    def _seek_moved(self, value: int):
        """Drag preview: the karaoke window does the same (FRB-13)."""
        self.player.setPosition(value)

    def _seek_released(self):
        self.player.setPosition(self.seek.value())

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self._stop_at = None
            if self.player.mediaStatus() == QMediaPlayer.EndOfMedia:
                self.player.setPosition(0)
            self.player.play()

    def _position_changed(self, position: int):
        sampled_at = self._sample_elapsed.nsecsElapsed() / 1_000_000.0
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        self.now.sample(position, playing, sampled_at)

    def _playback_state_changed(self, _state):
        sampled_at = self._sample_elapsed.nsecsElapsed() / 1_000_000.0
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        self.now.sample(self.player.position(), playing, sampled_at)

    def _tick(self):
        sampled_at = self._sample_elapsed.nsecsElapsed() / 1_000_000.0
        t = self.player.position()
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        self.now.sample(t, playing, sampled_at)
        self.btn_play.setText("Pause" if playing else "Play")
        if not self.seek.isSliderDown():
            self.seek.blockSignals(True)
            self.seek.setValue(t)
            self.seek.blockSignals(False)
        self.time_label.setText(format_ts(t))
        if self._stop_at is not None and t >= self._stop_at:
            self.player.pause()
            self._stop_at = None
        if not self.doc:
            return
        idx = max((i for i, l in enumerate(self.doc.lines) if l.start_ms is not None and l.start_ms <= t), default=-1)
        if idx != self._shown_line and playing:
            self._shown_line = idx
            if idx >= 0 and not self.words.hasFocus():
                self.lines.setCurrentRow(idx)

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
        start_ms = int(self.player.position()) if audio == self.audio else 0
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        self._open_karaoke_window(audio, start_ms, rows[0] if rows else None)

    def _open_karaoke_window(self, audio: Path, start_ms: int, row: TrackRow | None) -> None:
        scripts = script_candidates(audio, config.japanese_script())
        lyrics = default_script_path(audio, config.japanese_script())
        name = " — ".join(x for x in (row.artist, row.title) if x) if row is not None else None
        if self.karaoke_window is not None:
            self.karaoke_window.close()
        self.karaoke_window = KaraokeWindow(
            audio, lyrics, display_name=name or None, start_ms=start_ms,
            script_paths=scripts, on_next=self._karaoke_next, on_prev=self._karaoke_previous)
        self.karaoke_window.show()

    def _karaoke_next(self):
        self._karaoke_step(1)

    def _karaoke_previous(self):
        self._karaoke_step(-1)

    def _karaoke_step(self, delta: int) -> None:
        rows = self._visible_rows()
        if not rows:
            return
        current = self.karaoke_window.audio if self.karaoke_window is not None else self.audio
        paths = [r.path for r in rows]
        index = paths.index(current) if current in paths else -1
        target = paths[(index + delta) % len(paths)]
        QTimer.singleShot(0, lambda path=target: self._karaoke_open_path(path))

    def _karaoke_open_path(self, path: Path) -> None:
        if not self._select_path(path):
            return
        if self.karaoke_window is not None:
            self.karaoke_window.close()
            self.karaoke_window = None
        self.open_karaoke()

    # ---------- lyrics / editor ----------
    def _fill_lines(self):
        self.lines.blockSignals(True)
        self.lines.clear()
        review = set(review_lines(self.doc))
        if self.doc:
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

    def _push_doc(self, before: LrcDoc | None, after: LrcDoc | None, label: str,
                  undo_line: int = -1, redo_line: int = -1, undo_word: int = -1, redo_word: int = -1) -> None:
        self.undo_stack.push(_DocCommand(self, before, after, label, undo_line, redo_line,
                                         undo_word, redo_word))

    def _restore_doc(self, doc: LrcDoc | None, line: int = -1, word: int = -1) -> None:
        self.doc = doc
        self.now.set_doc(self.doc)
        self._fill_lines()
        if line >= 0 and self.lines.count():
            self.lines.setCurrentRow(min(line, self.lines.count() - 1))
            if word >= 0 and self.words.rowCount():
                self.words.selectRow(min(word, self.words.rowCount() - 1))

    def _apply(self, segs: list[Segment]):
        i = self.lines.currentRow()
        if not self.doc or i < 0:
            return
        total = self.player.duration() or max((s.end_ms or 0) for l in self.doc.lines for s in l.segments) + 1000
        row = self.words.currentRow()
        before = self.doc
        after = apply_edits(before, i, segs, total)
        self._push_doc(before, after, "Edit word timing", i, i, row, row)

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

    def add_word(self, text: str | None = None):
        i = self.lines.currentRow()
        if not self.doc or i < 0:
            return
        if text is None:
            text, ok = QInputDialog.getText(self, "Add word", "Word (added after the selected one):")
            if not ok or not text.strip():
                return
        after = self.words.currentRow()
        before = self.doc
        result = insert_word(before, i, after, text, self._total())
        self._push_doc(before, result, "Add word", i, i, after, after + 1)

    def delete_current_word(self):
        i, r = self.lines.currentRow(), self.words.currentRow()
        if not self.doc or i < 0 or r < 0:
            return
        line = self.doc.lines[i]
        deleting_line = len(line.segments) <= 1
        if deleting_line:
            answer = QMessageBox.question(
                self, "Delete word",
                "This line has only one word. Deleting it removes the whole line.\n\n"
                f"{line.text}\n\nYou can undo this with Ctrl+Z. Continue?")
            if answer != QMessageBox.Yes:
                return
        before = self.doc
        result = delete_word(before, i, r)
        label = "Delete line" if deleting_line else "Delete word"
        self._push_doc(before, result, label, i, i, r, max(0, r - 1))

    def add_line(self, text: str | None = None):
        before = self.doc
        base = before if before is not None else LrcDoc({}, [])
        after_index = self.lines.currentRow() if base.lines else -1
        if text is None:
            text, ok = QInputDialog.getText(self, "Insert line", "Text of the new line (inserted after the selected one):")
            if not ok or not text.strip():
                return
        prev = base.lines[after_index] if after_index >= 0 else None
        prev_end = max([s.end_ms or 0 for s in prev.segments] + [prev.start_ms or 0]) if prev else 0
        nxt = base.lines[after_index + 1].start_ms if after_index + 1 < len(base.lines) else None
        pos = self.player.position()
        start = pos if prev_end <= pos < (nxt or 10 ** 9) else prev_end + 100
        end = (nxt - 100) if nxt and nxt - 100 > start + 200 else start + 2000
        result = insert_line(base, after_index, text, start, end, self._total())
        self._push_doc(before, result, "Insert line", after_index, after_index + 1, -1, 0)

    def merge_current_line(self):
        i = self.lines.currentRow()
        if not self.doc or i <= 0:
            return
        before = self.doc
        result = merge_with_previous(before, i)
        self._push_doc(before, result, "Merge line", i, i - 1)

    def delete_current_line(self):
        i = self.lines.currentRow()
        if not self.doc or i < 0:
            return
        line = self.doc.lines[i]
        answer = QMessageBox.question(
            self, "Delete line",
            f"Delete this line?\n\n{line.text}\n\nYou can undo this with Ctrl+Z.")
        if answer != QMessageBox.Yes:
            return
        before = self.doc
        result = delete_line(before, i)
        self._push_doc(before, result, "Delete line", i, i, -1, -1)

    def accept_line(self):
        i = self.lines.currentRow()
        if not self.doc or i < 0:
            return
        before = self.doc
        after = mark_line_reviewed(before, i)
        if after is before:
            self.statusBar().showMessage("This line is not flagged for review", 4000)
            return
        self._push_doc(before, after, "Accept line", i, i)
        if self.save():
            self.statusBar().showMessage("Line accepted", 4000)

    def accept_all(self):
        if not self.doc:
            return
        before = self.doc
        after = clear_review_flags(before)
        if after is before:
            self.statusBar().showMessage("No review flags to clear", 4000)
            return
        self._push_doc(before, after, "Clear review flags")
        if self.save():
            self.statusBar().showMessage("Review flags cleared", 4000)

    def step_review(self, delta: int):
        flagged = review_lines(self.doc)
        if not self.doc or not flagged:
            self.statusBar().showMessage("No lines are flagged for review", 4000)
            return
        current = self.lines.currentRow()
        if delta > 0:
            target = next((i for i in flagged if i > current), flagged[0])
        else:
            target = next((i for i in reversed(flagged) if i < current), flagged[-1])
        self.lines.setCurrentRow(target)
        self.lines.scrollToItem(self.lines.item(target))

    def paste_lyrics(self):
        if not self.audio:
            return
        text, ok = QInputDialog.getMultiLineText(self, "Paste lyrics", "One line per lyric line:")
        if not ok or not text.strip():
            return
        answer = QMessageBox.question(
            self, "Paste lyrics",
            "Replace the whole lyric with the pasted text and align it again?\n\n"
            "The current .lrc is kept as a .bak copy. You can undo the edit with Ctrl+Z.")
        if answer != QMessageBox.Yes:
            return
        if not self._confirm_discard():
            return
        audio = self.audio
        self._paste_before = self.doc
        self._cancel_background.clear()
        self.statusBar().showMessage("Aligning the pasted lyrics …")
        self._run(FuncWorker(lambda: runner.realign(audio, text, cancel=self._cancel_background)), self._realigned)

    def _realigned(self, res):
        before = getattr(self, "_paste_before", None)
        self._paste_before = None
        if res.status == "cancelled":
            self.statusBar().showMessage("Realign stopped", 5000)
            return
        if res.status == "failed":
            QMessageBox.warning(self, "Realign failed", res.error)
            return
        self._update_row(read_status(res.path))
        if res.path == self.audio:
            self._reload_lrc()
            if self.doc is not None:
                self._push_doc(before, self.doc, "Paste lyrics", 0, 0)
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
        self.undo_stack.setClean()
        self._set_dirty(False)
        try:
            self._update_row(read_status(self.audio))
        except OSError as exc:
            self._show_io_error("Read the saved lyrics", self.audio.with_suffix(".lrc"), exc)
        if self.karaoke_window is not None and self.karaoke_window.audio == self.audio:
            self.karaoke_window.reload_lyrics()
        self.statusBar().showMessage("Saved (previous .lrc kept as .bak)", 5000)
        return True

    def _set_dirty(self, dirty: bool):
        self.dirty = dirty
        try:
            self._refresh_title()
        except RuntimeError:   # the window can be deleted while a queued cleanChanged arrives
            pass

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

    def prepare_update(self, path: Path, *, info: updater.UpdateInfo | None = None,
                       silent: bool = True, relaunch: bool = True) -> None:
        """"Restart now"/"Install now": record the install request and start the normal close.

        Setup is not started here. The close asks about unsaved edits and a running queue, may be
        vetoed, and waits for a stopping queue; ``_install_update_on_exit`` starts Setup as its
        last step. ``silent`` is false for the interactive "Install now" flow; ``relaunch`` makes
        a silent install start LyricLoom again (the "Restart now" action).
        """
        self._install_request = _InstallRequest(Path(path), info, silent, relaunch)
        self.close()

    def _close_vetoed(self, e) -> None:
        """Keep the window open. A restart/install request ends here; an ``auto`` download stays
        armed for a later normal close."""
        e.ignore()
        if self._install_request is not None:
            self._install_request = None
            self._update_controller.install_postponed()

    def _install_update_on_exit(self) -> None:
        """Start Setup as the very last step of a close that is really happening.

        A restart/install request runs as asked; otherwise a verified ``auto`` download installs
        silently. Nothing starts while a queue runs or is being checked before it starts.
        """
        request, self._install_request = self._install_request, None
        if self._queue is not None or self._pending_queue is not None:
            if request is not None or self._update_controller.downloaded_info is not None:
                LOG.warning("a queue started while LyricLoom was closing; the update was not installed")
            return   # an install must never interrupt a queue
        info = self._update_controller.downloaded_info
        if request is not None:
            path = self._update_controller.take_downloaded_update(request.path)
            silent, relaunch = request.silent, request.relaunch
            info = request.info or info
        else:
            path = self._update_controller.take_downloaded_update(auto_only=True)
            silent, relaunch = True, False
        if path is None:
            return
        try:
            updater.launch_installer(path, silent=silent, relaunch=relaunch, skip_plugin=False,
                                     version=info.version if info is not None else "")
        except Exception as exc:  # noqa: BLE001
            LOG.error("could not start the downloaded update on exit: %s", exc)
            QMessageBox.critical(self, "Update", "Could not start the installer:\n" + str(exc))

    def _stop_threads(self):
        self._cancel_background.set()
        self._update_controller.shutdown()
        for thread, _worker in list(self._threads):
            thread.quit()
            if not thread.wait(3000):
                # Never terminate: a scan is read-only and a worker process is cancelled through
                # the queue's cancellation event. finish_shutdown joins whatever outlives the
                # window with its own, bounded wait.
                LOG.warning("background thread did not stop within 3 s; it will be joined at exit")

    def finish_shutdown(self):
        """Joins background threads after the event loop ends, so none is destroyed while running."""
        self._update_controller.wait_for_threads()
        _join_background_jobs()
        for thread, _worker in list(self._threads):
            thread.quit()
            if not thread.wait(BACKGROUND_JOIN_TIMEOUT_MS):
                # A stalled network share must not keep the process alive forever (FRB-07). There
                # is no safe way to terminate a Python thread; leave it and say so in the log.
                LOG.warning("background thread did not stop within %d s; leaving it behind",
                            BACKGROUND_JOIN_TIMEOUT_MS // 1000)

    def closeEvent(self, e):
        if not self._confirm_discard():
            self._close_vetoed(e)
            return
        if self._setup_assistant is not None:
            self._setup_assistant.reject()
            self._setup_assistant = None
        if self._queue is not None:
            choice = self._ask_queue_shutdown()
            if choice == "keep":
                self._close_vetoed(e)
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
        if self._models_window is not None:
            if not self._models_window.close():   # asks before cancelling a running download
                self._close_vetoed(e)
                return
        self._save_ui_state()
        if self._ipc_server is not None:
            self._ipc_server.close()
        self._stop_threads()
        self._install_update_on_exit()   # last: every prompt and veto above has passed
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


def startup_message(cli: CommandLine) -> dict | None:
    """The command this process hands to a running instance, with JSON-ready path strings (FRB-02)."""
    if cli.process:
        accepted, rejected = expand_audio_paths(cli.process)
        return {"cmd": "process", "paths": [str(path) for path in accepted],
                "rejected": rejected, "redo": cli.redo}
    if cli.open_file:
        opened, error = validate_audio_file(cli.open_file)
        return ({"cmd": "open", "path": str(opened)} if opened is not None
                else {"cmd": "report", "rejected": [error or f"{cli.open_file}: invalid path"]})
    return None


def apply_english_locale() -> None:
    """Formats numbers and dates in English, as the rest of the interface is.

    Qt takes its default locale from the Windows *regional format*, which is separate from the
    display language: an English Windows set to a Brazilian format would otherwise show
    "1,50" and Portuguese month names inside an English window."""
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))


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
    # Every GUI process holds this mutex until it exits, so the installer can wait for it.
    updater.hold_app_mutex()
    has_program = bool(argv) and not argv[0].startswith("-")
    cli = parse_command_line(argv[1:] if has_program else argv)
    migrated = config.migrate_legacy_settings()
    if migrated:
        # The constants were computed at import, before the migration rewrote the settings;
        # re-read them so this session uses the moved work/models folders (FRB-14).
        config.refresh_folder_constants()
    apply_english_locale()
    app = QApplication(argv if has_program else [config.APP_NAME, *argv])
    install_shutdown_joins()
    if migrated:
        QMessageBox.information(
            None, config.APP_NAME,
            f"Lyrics Boca settings and data were moved to:\n{config.APP_DATA}\n\n"
            "Your old folders were left in place only when the new location already had a copy.")
    app.setApplicationName(config.APP_NAME)
    app.setApplicationDisplayName(config.APP_NAME)
    app.setOrganizationName(config.APP_NAME)
    app.setApplicationVersion(VERSION)
    theme.apply_theme(app)
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

    startup = startup_message(cli)

    server = IpcServer()
    if not server.listen():
        # A crashed process can leave the name behind on Linux; a live but busy one gets one more
        # chance with a longer timeout. If it still owns the name, do not open a second window.
        if handle_busy_instance(server, command):
            sys.exit(0)
        if not server.listen():
            LOG.warning("single-instance server %s could not listen", server.name)
    if server.is_listening:
        server.hold()   # buffer a command that arrives while MainWindow is built
    w = MainWindow(server=server, startup=startup)
    if w._duplicate_instance:
        w.dirty = False
        w.close()
        sys.exit(0)
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
