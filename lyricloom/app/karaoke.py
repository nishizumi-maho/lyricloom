"""Standalone karaoke player: the starry-night view of one enhanced .lrc, no MusicBee needed."""
from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Callable

import mutagen

from PySide6.QtCore import QElapsedTimer, QPointF, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QKeySequence, QLinearGradient, QPainter, QRadialGradient, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QSlider, QVBoxLayout, QWidget)

from .. import config
from ..lrc import format_ts, parse_lrc
from ..model import LrcDoc, Line
from .lyric_view import LyricView
from .media import default_script_path, script_candidates, vocal_source
from .widgets import SeekSlider

def _track_label(audio: Path) -> str:
    """Artist and title from tags, or the filename when the tags are missing."""
    try:
        f = mutagen.File(str(audio), easy=True)
        tags = f.tags if f is not None else None
        get = lambda key: str(tags[key][0]).strip() if tags and key in tags and tags[key] else ""
        artist, title = get("artist"), get("title")
        if title:
            return f"{artist} — {title}" if artist else title
    except Exception:  # noqa: BLE001 - tags are a nicety; the filename always works
        pass
    return audio.stem


class _StarrySky(QWidget):
    """The backdrop: a vertical night gradient and deterministic, gently twinkling stars.

    The window's lyric view drives :meth:`advance` with the same frame delta, so the stars move at
    the animation frame rate instead of a separate 10 fps timer.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        rng = random.Random(0x51A77)
        self._stars = [(rng.random(), rng.random(), rng.uniform(0.7, 2.1),
                        rng.uniform(0.0, math.tau), rng.uniform(0.35, 1.0)) for _ in range(90)]
        self._phase = 0.0

    def advance(self, _wall_seconds: float, dt: float) -> None:
        self._phase += max(0.0, min(0.1, dt)) * 0.9
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        sky = QLinearGradient(0.0, 0.0, 0.0, float(rect.height()))
        sky.setColorAt(0.0, QColor("#040614"))
        sky.setColorAt(0.52, QColor("#0b1027"))
        sky.setColorAt(1.0, QColor("#1a1f45"))
        painter.fillRect(rect, sky)

        # Two very faint washes keep the gradient from looking like a flat background.
        painter.setPen(Qt.NoPen)
        width, height = float(rect.width()), float(rect.height())
        for cx, cy, radius, color in ((0.78, 0.16, 0.58, QColor(92, 72, 176, 42)),
                                      (0.16, 0.78, 0.48, QColor(34, 108, 160, 28))):
            glow = QRadialGradient(QPointF(width * cx, height * cy), width * radius)
            glow.setColorAt(0.0, color)
            glow.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
            painter.setBrush(glow)
            painter.drawEllipse(QPointF(width * cx, height * cy), width * radius, height * radius)

        for nx, ny, radius, offset, speed in self._stars:
            twinkle = 0.5 + 0.5 * math.sin(self._phase * speed + offset)
            alpha = int(255 * (0.28 + 0.72 * twinkle))
            painter.setBrush(QColor(205, 224, 255, alpha))
            painter.drawEllipse(QPointF(nx * width, ny * height), radius, radius)
            if radius > 1.8:
                painter.setBrush(QColor(150, 190, 255, alpha // 5))
                painter.drawEllipse(QPointF(nx * width, ny * height), radius * 3, radius * 3)
        painter.end()


class KaraokeWindow(QMainWindow):
    """Plays one track and follows its word timing. Closing the window stops the audio."""

    def __init__(self, audio: Path, lyrics: Path | None = None, *, display_name: str | None = None,
                 on_next: Callable[[], None] | None = None,
                 on_prev: Callable[[], None] | None = None,
                 start_ms: int = 0,
                 script_paths: list[tuple[str, Path]] | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.audio = Path(audio)
        self.on_next, self.on_prev = on_next, on_prev
        self._script_paths = ([(label, Path(path)) for label, path in script_paths]
                              if script_paths else script_candidates(self.audio, config.japanese_script()))
        self.lyrics_path = (Path(lyrics) if lyrics is not None
                            else default_script_path(self.audio, config.japanese_script()))
        if not any(path == self.lyrics_path for _label, path in self._script_paths):
            self._script_paths.append(("Main (.lrc)", self.lyrics_path))
        self.doc: LrcDoc | None = None
        self._display_name = display_name or _track_label(self.audio)
        self._sample_elapsed = QElapsedTimer()
        self._sample_elapsed.start()
        self._autoplay = True
        self._pending_seek: int | None = max(0, int(start_ms))
        self._pending_play = True
        self._started = False
        self._shortcuts: list[QShortcut] = []
        self._vocals_path = vocal_source(self.audio)

        self.setWindowTitle(f"{config.APP_NAME} Karaoke — {self._display_name}")
        self.resize(1100, 720)
        self.setMinimumSize(760, 520)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Karaoke player")

        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        self.audio_out.setVolume(0.85)

        self._build()
        self._load_lyrics()
        self._connect_player()
        self._install_shortcuts()
        self._set_source()
        self._ui_timer = QTimer(self, interval=50, timeout=self._tick)

    # ---------- layout ----------
    def _build(self):
        self.sky = _StarrySky()
        self.setCentralWidget(self.sky)
        layout = QVBoxLayout(self.sky)
        layout.setContentsMargins(48, 28, 48, 24)
        layout.setSpacing(10)

        self.title_label = QLabel(self._display_name)
        self.title_label.setTextFormat(Qt.PlainText)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("color: #8494c4; font-size: 11pt;")
        self.title_label.setAccessibleName("Track")
        layout.addWidget(self.title_label)

        self.lyrics = LyricView(animate_when_paused=True)
        self.lyrics.setAccessibleName("Lyric lines")
        layout.addWidget(self.lyrics, 1)
        self.lyrics.frameAdvanced.connect(self.sky.advance)

        panel = QWidget()
        panel.setObjectName("controls")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(20, 14, 20, 14)
        panel_layout.setSpacing(10)

        row = QHBoxLayout()
        self.btn_prev = QPushButton("⏮")
        self.btn_prev.setToolTip("Previous track (P)")
        self.btn_prev.setAccessibleName("Previous track")
        self.btn_prev.setVisible(self.on_prev is not None)
        self.btn_prev.clicked.connect(self._previous_track)
        self.btn_play = QPushButton("Play")
        self.btn_play.setMinimumWidth(110)
        self.btn_play.setToolTip("Play or pause (Space)")
        self.seek = SeekSlider()
        self.seek.setRange(0, 0)
        self.seek.setSingleStep(1000)
        self.seek.setPageStep(5000)
        self.seek.setToolTip("Seek (Left/Right: 5 seconds)")
        self.seek.setAccessibleName("Playback position")
        self.time_label = QLabel("00:00.00 / 00:00.00")
        self.time_label.setMinimumWidth(self.time_label.fontMetrics().horizontalAdvance("00:00.00 / 00:00.00") + 16)
        self.btn_next = QPushButton("⏭")
        self.btn_next.setToolTip("Next track (N)")
        self.btn_next.setAccessibleName("Next track")
        self.btn_next.setVisible(self.on_next is not None)
        self.btn_next.clicked.connect(self._next_track)
        row.addWidget(self.btn_prev)
        row.addWidget(self.btn_play)
        row.addWidget(self.seek, 1)
        row.addWidget(self.time_label)
        row.addWidget(self.btn_next)
        panel_layout.addLayout(row)

        row2 = QHBoxLayout()
        self.vocals = QCheckBox("Vocals only")
        self.vocals.setAccessibleName("Vocals only")
        self.vocals.setEnabled(self._vocals_path is not None)
        self.vocals.setToolTip(
            f"Play the isolated vocals cached for this track:\n{self._vocals_path}" if self._vocals_path
            else "No isolated vocals are cached for this track yet.\n"
                 "Run the song through LyricLoom once to create them.")
        row2.addWidget(self.vocals)
        self.script = QComboBox()
        self.script.setAccessibleName("Lyric script")
        self.script.setToolTip("Lyric file to show: the main .lrc follows the chosen Japanese script")
        for label, path in self._script_paths:
            self.script.addItem(f"{label}", str(path))
        self.script.setCurrentIndex(max(0, next(
            (i for i, (_label, path) in enumerate(self._script_paths) if path == self.lyrics_path), 0)))
        self.script.currentIndexChanged.connect(self._script_changed)
        self.script.setVisible(len(self._script_paths) > 1)
        row2.addWidget(QLabel("Script"))
        row2.addWidget(self.script)
        row2.addStretch(1)
        row2.addWidget(QLabel("Volume"))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(85)
        self.volume.setFixedWidth(140)
        self.volume.setToolTip("Volume (Up/Down)")
        self.volume.setAccessibleName("Volume")
        row2.addWidget(self.volume)
        panel_layout.addLayout(row2)

        panel.setStyleSheet("""
            QWidget#controls {
                background: rgba(12, 18, 42, 195);
                border: 1px solid rgba(130, 160, 255, 60);
                border-radius: 18px;
            }
            QPushButton {
                background: rgba(139, 233, 253, 30);
                border: 1px solid rgba(139, 233, 253, 125);
                border-radius: 15px;
                color: #eaf4ff;
                padding: 7px 22px;
                font-size: 12pt;
                font-weight: 600;
            }
            QPushButton:hover { background: rgba(139, 233, 253, 60); }
            QPushButton:pressed { background: rgba(139, 233, 253, 95); }
            QSlider::groove:horizontal { height: 4px; background: rgba(190, 210, 255, 45); border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #8be9fd; border-radius: 2px; }
            QSlider::handle:horizontal {
                width: 14px; margin: -6px 0; border-radius: 7px; background: #eaf4ff;
            }
            QCheckBox { color: #c9d4f5; font-size: 10pt; spacing: 8px; }
            QLabel { color: #c9d4f5; }
        """)
        layout.addWidget(panel)

        hint = "Space play/pause · ←/→ seek 5 s · ↑/↓ volume · F11 fullscreen · Esc close"
        if self.on_next is not None or self.on_prev is not None:
            hint += " · N/P track"
        self.hint = QLabel(hint)
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setStyleSheet("color: #59688f; font-size: 9pt;")
        layout.addWidget(self.hint)

        # Global shortcuts must win over a focused button or slider, so the controls never take focus.
        for widget in (self.btn_play, self.seek, self.vocals, self.volume):
            widget.setFocusPolicy(Qt.NoFocus)

    # ---------- media ----------
    def _connect_player(self):
        self.btn_play.clicked.connect(self.toggle_play)
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.seek.sliderReleased.connect(lambda: self.player.setPosition(self.seek.value()))
        self.seek.valueChanged.connect(self._seek_changed)
        self.volume.valueChanged.connect(lambda value: self.audio_out.setVolume(value / 100.0))
        self.vocals.toggled.connect(self._source_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._state_changed)
        self.player.positionChanged.connect(self._position_changed)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.errorOccurred.connect(self._media_error)

    def _set_source(self):
        vocals = self._vocals_path or vocal_source(self.audio)
        if vocals is not None:
            self._vocals_path = vocals
        source = vocals if self.vocals.isChecked() and vocals else self.audio
        self.player.setSource(QUrl.fromLocalFile(str(source)))

    def _source_changed(self):
        if self._vocals_path is None:
            return
        # setSource() reloads the file and loses the position; remember it until the new media is
        # ready instead of seeking immediately (that seek would be discarded by the loader).
        self._pending_seek = self.player.position()
        self._pending_play = self.player.playbackState() == QMediaPlayer.PlayingState
        self._set_source()

    def _media_status(self, status):
        if self._pending_seek is None or status not in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            return
        position, playing = self._pending_seek, self._pending_play
        self._pending_seek = None
        self._pending_play = False
        self.player.setPosition(position)
        if playing:
            self.player.play()

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            return
        if self.player.mediaStatus() == QMediaPlayer.EndOfMedia:
            self.player.setPosition(0)
        self.player.play()

    def _state_changed(self, state):
        self.btn_play.setText("Pause" if state == QMediaPlayer.PlayingState else "Play")
        self._sample_player()

    def _position_changed(self, _position: int):
        self._sample_player()

    def _sample_player(self):
        """Timestamp a player reading when the player is asked, not when a frame reads it."""
        sampled_at = self._sample_elapsed.nsecsElapsed() / 1_000_000.0
        position = self.player.position()
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        self.lyrics.sample(position, playing, sampled_at)

    def _duration_changed(self, duration: int):
        self.seek.setRange(0, max(0, duration))

    def _seek_changed(self, value: int):
        # A click on the groove changes the value without emitting sliderMoved; dragging is handled
        # live above, and timer updates block their signals.
        if not self.seek.isSliderDown():
            self.player.setPosition(value)

    def _media_error(self, error, message: str):
        if error != QMediaPlayer.NoError:
            self._pending_seek = None
            self._pending_play = False
            self.hint.setText(f"Playback error: {message}")
            self.hint.setStyleSheet("color: #ff8f9a; font-size: 9pt;")

    def _tick(self):
        position = int(self.player.position())
        if not self.seek.isSliderDown():
            self.seek.blockSignals(True)
            self.seek.setValue(position)
            self.seek.blockSignals(False)
        clock = f"{format_ts(position)} / {format_ts(self.player.duration())}"
        if clock != self.time_label.text():
            self.time_label.setText(clock)
        self._sample_player()

    # ---------- lyrics ----------
    @staticmethod
    def _current_line_index(lines: list[Line], t_ms: int) -> int:
        return LyricView.line_index(lines, t_ms)

    def _load_lyrics(self):
        if not self.lyrics_path.is_file():
            self.doc = None
            self._show_message("No word-synced lyrics yet",
                               f"Run “{self.audio.stem}” through LyricLoom, then open Karaoke again.")
            return
        try:
            self.doc = parse_lrc(self.lyrics_path.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            self.doc = None
            self._show_message("The lyrics file could not be read", str(exc))
            return
        if not self.doc.lines:
            self.doc = None
            self._show_message("No timed lines in the lyrics file",
                               f"{self.lyrics_path.name} has no [mm:ss] lines.")
            return
        self.lyrics.set_doc(self.doc)

    def reload_lyrics(self) -> None:
        """Re-reads the current lyric file, for example after the main window saves an edit."""
        self._refresh_scripts()
        self._load_lyrics()

    def set_animation_divisor(self, divisor: int) -> None:
        """Apply a frame-rate choice changed in Settings without reopening the window."""
        self.lyrics.set_divisor(divisor)

    def _refresh_scripts(self) -> None:
        paths = script_candidates(self.audio, config.japanese_script())
        if paths == self._script_paths:
            return
        current = self.lyrics_path
        self._script_paths = paths
        if not any(path == current for _label, path in paths):
            current = default_script_path(self.audio, config.japanese_script())
            self.lyrics_path = current
        self.script.blockSignals(True)
        self.script.clear()
        for label, path in paths:
            self.script.addItem(label, str(path))
        index = next((i for i, (_label, path) in enumerate(paths) if path == self.lyrics_path), 0)
        self.script.setCurrentIndex(max(0, index))
        self.script.blockSignals(False)
        self.script.setVisible(len(paths) > 1)

    def _script_changed(self, index: int) -> None:
        path = self.script.itemData(index)
        if path is None:
            return
        new_path = Path(path)
        if new_path == self.lyrics_path:
            return
        self.lyrics_path = new_path
        self._load_lyrics()

    def _show_message(self, headline: str, detail: str):
        self.lyrics.set_message(headline, detail)

    # ---------- keyboard ----------
    def _install_shortcuts(self):
        binds = [
            ("Space", self.toggle_play),
            ("Left", lambda: self._seek_relative(-5000)),
            ("Right", lambda: self._seek_relative(5000)),
            ("Up", lambda: self._volume_step(5)),
            ("Down", lambda: self._volume_step(-5)),
            ("F11", self._toggle_fullscreen),
            ("Esc", self._escape),
            ("N", self._next_track),
            ("P", self._previous_track),
        ]
        for key, slot in binds:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(slot)
            self._shortcuts.append(shortcut)

    def _seek_relative(self, delta_ms: int):
        position = self.player.position() + delta_ms
        duration = self.player.duration()
        if duration > 0:
            position = min(duration, position)
        self.player.setPosition(max(0, position))

    def _volume_step(self, delta: int):
        self.volume.setValue(max(0, min(100, self.volume.value() + delta)))

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _escape(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.close()

    def _next_track(self):
        if self.on_next is not None:
            self.on_next()

    def _previous_track(self):
        if self.on_prev is not None:
            self.on_prev()

    # ---------- window ----------
    def showEvent(self, event):
        super().showEvent(event)
        self._sample_player()
        self.lyrics.start()
        self._ui_timer.start()
        self.activateWindow()
        self.setFocus(Qt.OtherFocusReason)
        if self._pending_seek is not None:
            status = self.player.mediaStatus()
            if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
                self._media_status(status)
            elif status in (QMediaPlayer.NoMedia, QMediaPlayer.EndOfMedia, QMediaPlayer.InvalidMedia):
                # The backend may not start loading until play(); the pending seek is applied on
                # LoadedMedia.
                self.player.play()
            self._autoplay = False

    def hideEvent(self, event):
        self.lyrics.stop()
        self._ui_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._ui_timer.stop()
        self.lyrics.stop()
        self._pending_seek = None
        self._pending_play = False
        self.player.stop()
        super().closeEvent(event)
