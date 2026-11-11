"""Smooth QPainter lyric view shared by the karaoke window and the main player.

The widget owns a :class:`~lyricloom.animation.PlaybackClock`; the player window feeds it
timestamped samples of ``QMediaPlayer.position()`` and the view renders on a precise timer at the
display refresh rate (or an integer divisor chosen in Settings). Layouts and glyph paths are cached
per line and rebuilt only when the text, the size, the font or the script direction changes.
"""
from __future__ import annotations

import math
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass

from PySide6.QtCore import QElapsedTimer, QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen,
                           QTextLayout, QTextOption)
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import config
from ..animation import (LineEmphasis, PlaybackClock, ScrollPath, effective_fps, line_sweeps,
                         normalize_divisor, smootherstep, sung_weights, sweep_lit, word_fill)
from ..model import Line, LrcDoc

_FUTURE = QColor("#657199")
_PAST = QColor("#8be9fd")
_CURRENT = QColor("#eaf4ff")
_GOLD = QColor("#ffd166")
_HEAD = QColor("#fffbe6")
_GLOW = QColor(255, 186, 74, 90)
_MESSAGE = QColor("#dfe8ff")
_DETAIL = QColor("#7484ad")

_FEATHER_FACTOR = 0.45
_GROW = 0.08
_INTRO_OFFSET_FACTOR = 1.5


def is_rtl(text: str) -> bool:
    """Base direction from the first strong character, so Arabic and Hebrew lines read correctly."""
    for char in text:
        direction = unicodedata.bidirectional(char)
        if direction in ("R", "AL"):
            return True
        if direction == "L":
            return False
    return False


def _smooth(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t),
                  255)


def _utf16_len(text: str) -> int:
    """Qt text positions count UTF-16 code units, not Python code points."""
    if all(ord(char) < 0x10000 for char in text):
        return len(text)
    return len(text.encode("utf-16-le")) // 2


def _utf16_units(text: str, characters: float) -> float:
    """UTF-16 units covered by the first ``characters`` code points (the last one may be partial)."""
    whole = int(characters)
    units = float(_utf16_len(text[:whole]))
    if whole < len(text):
        units += (characters - whole) * _utf16_len(text[whole])
    return units


def _utf16_slice(text: str, start: int, length: int) -> str:
    if all(ord(char) < 0x10000 for char in text):
        return text[start:start + length]
    data = text.encode("utf-16-le")
    return data[start * 2:(start + length) * 2].decode("utf-16-le", "replace")


@dataclass
class _Row:
    path: QPainterPath
    width: float
    baseline: float
    start: int
    length: int
    text: str


@dataclass
class _LineLayout:
    rows: list[_Row]
    height: float
    width: float
    rtl: bool
    font: QFont
    metrics: QFontMetricsF


@dataclass
class _Block:
    top: float
    height: float
    index: int
    layout: _LineLayout


class LyricView(QWidget):
    """A scrolling lyric column with a soft gold sweep.

    ``compact`` draws only the current line large and the next line small beneath it (the main
    player); the karaoke window uses the full column. A compact view stops its timer while nothing
    plays, so an idle main window costs no CPU.
    """

    frameAdvanced = Signal(float, float)   # wall seconds, dt seconds

    def __init__(self, parent: QWidget | None = None, *, compact: bool = False,
                 animate_when_paused: bool | None = None, divisor: int | None = None) -> None:
        super().__init__(parent)
        self.compact = compact
        self._animate_when_paused = (not compact) if animate_when_paused is None else animate_when_paused
        self._divisor = normalize_divisor(config.smooth_animation_divisor() if divisor is None else divisor)
        self.clock = PlaybackClock()

        self._doc: LrcDoc | None = None
        self._lines: list[Line] = []
        self._starts: list[float] = []
        self._sweeps: list[tuple[float, float] | None] = []
        self._sweep_weights: list[list[float]] = []
        self._message: tuple[str, str] = ("", "")

        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._wall_seconds = 0.0
        self._last_frame_ms: float | None = None
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._on_frame)
        self._screen = None
        self._window_handle = None

        self._layout_dirty = True
        self._layout_builds = 0
        self._line_layouts: dict[tuple, _LineLayout] = {}
        self._blocks: list[_Block] = []
        self._content_width = 0.0
        self._base_px = 18.0
        self._scroll_path: ScrollPath | None = None
        self._emphasis = LineEmphasis(0)

        self._scroll = 0.0
        self._scroll_velocity = 0.0
        self._scroll_ready = False
        self._residual = 0.0
        self._residual_velocity = 0.0
        self._residual_at = 0.0
        self._anim_seconds = 0.0
        self._song_time = 0.0
        self._last_song_time: float | None = None
        self._gradients: dict[tuple[int, bool], QLinearGradient] = {}

        self.setAccessibleName("Current lyric line")
        self.setSizePolicy(QSizePolicy.Expanding,
                           QSizePolicy.Preferred if compact else QSizePolicy.Expanding)

    # ---------------------------------------------------------------- document and clock
    def set_doc(self, doc: LrcDoc | None) -> None:
        self._doc = doc
        self._lines = list(doc.lines) if doc is not None else []
        self._starts = [float(line.start_ms) if line.start_ms is not None else 1e18
                        for line in self._lines]
        self._prepare_sweeps()
        self._message = ("", "")
        self._layout_dirty = True
        self._scroll_path = None
        self._scroll_ready = False
        self._residual = self._residual_velocity = 0.0
        self._last_song_time = None
        self._emphasis.reset(len(self._lines))
        self._line_layouts.clear()
        if not self._lines and not self._animate_when_paused:
            self._timer.stop()
        else:
            self._ensure_timer()
        self.update()

    def set_message(self, headline: str, detail: str = "") -> None:
        """Show a message instead of lyrics (no lyrics, or a file that could not be read)."""
        self._doc = None
        self._lines = []
        self._starts = []
        self._prepare_sweeps()
        self._message = (headline, detail)
        self._layout_dirty = True
        self._scroll_path = None
        self._scroll_ready = False
        if self._animate_when_paused:
            self._ensure_timer()
        else:
            self._timer.stop()
        self.update()

    def clear(self) -> None:
        self.set_doc(None)

    def sample(self, position_ms: float, playing: bool, sampled_at_ms: float | None = None) -> None:
        """Feed one timestamped player reading (taken when the player was asked)."""
        if sampled_at_ms is None:
            sampled_at_ms = self.elapsed_ms()
        self.clock.sample(float(position_ms), bool(playing), float(sampled_at_ms))
        if self.clock.playing:
            self._ensure_timer()
        else:
            # A seek while paused must still show the new line, but an unchanged position must not
            # cost a repaint. A paused view with no timer (the main player) snaps to the new path.
            now = self.clock.now_ms(float(sampled_at_ms))
            if self._lines and abs(now - self._song_time) > 0.5:
                if not self._animate_when_paused:
                    self._scroll_ready = False
                self.advance(float(sampled_at_ms), 0.0)
                self.update()
            if not self._animate_when_paused:
                self._timer.stop()

    def elapsed_ms(self) -> float:
        return self._elapsed.nsecsElapsed() / 1_000_000.0

    # ---------------------------------------------------------------- frame pacing
    @property
    def divisor(self) -> int:
        return self._divisor

    def set_divisor(self, divisor: int) -> None:
        self._divisor = normalize_divisor(divisor)
        self._update_interval(force=True)

    @property
    def is_animating(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        self._ensure_timer()

    def stop(self) -> None:
        self._timer.stop()
        self._last_frame_ms = None

    def _refresh_hz(self) -> float:
        screen = self.screen()
        if screen is not None:
            try:
                hz = float(screen.refreshRate())
            except (TypeError, ValueError):
                hz = 0.0
            if hz > 0:
                return hz
        return 60.0

    def _should_tick(self) -> bool:
        if not self.isVisible():
            return False
        window = self.window()
        if window is not None and window.isMinimized():
            return False
        if not self._lines and not self._animate_when_paused:
            return False
        if not self.clock.playing and not self._animate_when_paused:
            return False
        return True

    def _ensure_timer(self) -> None:
        if not self._should_tick():
            self._timer.stop()
            return
        self._update_interval()
        if not self._timer.isActive():
            self._last_frame_ms = None
            self._timer.start()

    def _update_interval(self, force: bool = False) -> None:
        fps = effective_fps(self._divisor, self._refresh_hz(), self.clock.playing,
                            minimized=bool(self.window() and self.window().isMinimized()),
                            hidden=not self.isVisible())
        if fps <= 0 or (not self.clock.playing and not self._animate_when_paused):
            self._timer.stop()
            return
        interval = max(1, int(round(1000.0 / fps)))
        if force or self._timer.interval() != interval:
            self._timer.setInterval(interval)

    def _bind_screen(self) -> None:
        screen = self.screen()
        if screen is not self._screen:
            if self._screen is not None and hasattr(self._screen, "refreshRateChanged"):
                try:
                    self._screen.refreshRateChanged.disconnect(self._screen_refresh_changed)
                except (RuntimeError, TypeError):
                    pass
            self._screen = screen
            if screen is not None and hasattr(screen, "refreshRateChanged"):
                screen.refreshRateChanged.connect(self._screen_refresh_changed)
        handle = self.window().windowHandle() if self.window() is not None else None
        if handle is not None and handle is not self._window_handle:
            if self._window_handle is not None and hasattr(self._window_handle, "screenChanged"):
                try:
                    self._window_handle.screenChanged.disconnect(self._window_screen_changed)
                except (RuntimeError, TypeError):
                    pass
            self._window_handle = handle
            if hasattr(handle, "screenChanged"):
                handle.screenChanged.connect(self._window_screen_changed)

    def _screen_refresh_changed(self, *_args) -> None:
        self._update_interval(force=True)

    def _window_screen_changed(self, *_args) -> None:
        self._bind_screen()
        self._update_interval(force=True)

    def _on_frame(self) -> None:
        if not self._should_tick():
            self._timer.stop()
            return
        self._update_interval()
        now = self.elapsed_ms()
        dt = 0.0 if self._last_frame_ms is None else (now - self._last_frame_ms) / 1000.0
        self._last_frame_ms = now
        self.advance(now, max(0.0, min(0.1, dt)))
        self.update()
        self.frameAdvanced.emit(self._wall_seconds, max(0.0, min(0.1, dt)))

    def advance(self, frame_time_ms: float | None = None, dt: float | None = None) -> None:
        """Evaluate one frame at a monotonic time. Exposed so tests can drive a fake clock."""
        if frame_time_ms is None:
            frame_time_ms = self.elapsed_ms()
        if dt is None:
            dt = 0.0 if self._last_frame_ms is None else (frame_time_ms - self._last_frame_ms) / 1000.0
            self._last_frame_ms = frame_time_ms
        dt = max(0.0, min(0.1, float(dt)))
        self._wall_seconds += dt
        self._anim_seconds += dt
        self._song_time = self.clock.now_ms(frame_time_ms)
        if not self._lines:
            return
        layout_changed = self._ensure_layout()
        path = self._scroll_path
        if path is None:
            return
        phase = path.phase_at(self._song_time)
        previous_scroll, previous_velocity = self._scroll, self._scroll_velocity
        discontinuity = False
        if not self._scroll_ready:
            self._scroll = phase.position
            self._scroll_velocity = 0.0
            self._residual = self._residual_velocity = 0.0
            self._scroll_ready = True
        else:
            discontinuity = layout_changed or self._song_time_jump(self._song_time, dt)
            if discontinuity:
                self._residual = previous_scroll - phase.position
                self._residual_velocity = ScrollPath.clamp_residual_velocity(
                    self._residual, previous_velocity - path.velocity_at(self._song_time))
                self._residual_at = self._anim_seconds
            residual = 0.0
            if self._residual != 0.0 or self._residual_velocity != 0.0:
                residual = ScrollPath.residual_at(self._residual, self._residual_velocity,
                                                  self._anim_seconds - self._residual_at)
            if abs(residual) < 0.001 and abs(self._residual_velocity) < 0.001:
                residual = 0.0
                self._residual = self._residual_velocity = 0.0
            self._scroll = phase.position + residual
        if discontinuity:
            self._scroll_velocity = previous_velocity
        elif dt > 0.000001:
            self._scroll_velocity = (self._scroll - previous_scroll) / dt
        self._last_song_time = self._song_time
        self._emphasis.update(phase, self.current_line_index())

    def _song_time_jump(self, song_ms: float, dt: float) -> bool:
        if self._last_song_time is None:
            return False
        if song_ms < self._last_song_time - 0.001:
            return True
        if abs(song_ms - self._last_song_time) < 0.001:
            return False
        expected = self._last_song_time + dt * 1000.0
        return abs(song_ms - expected) > 30.0

    # ---------------------------------------------------------------- layout
    def _margin(self) -> float:
        return max(4.0, self.width() * (0.02 if self.compact else 0.04))

    def _compute_base_px(self) -> float:
        if self.compact:
            return max(16.0, min(34.0, self.height() * 0.40))
        return max(18.0, min(110.0, self.height() / 13.0))

    def _line_layout(self, line: Line, px: float, max_width: float) -> _LineLayout:
        rtl = is_rtl(line.text)
        key = (line.text, round(px, 2), round(max_width, 2), rtl, self.font().family())
        cached = self._line_layouts.get(key)
        if cached is not None:
            return cached
        if len(self._line_layouts) > 512:
            self._line_layouts.clear()
        font = QFont(self.font())
        font.setPixelSize(max(1, int(round(px))))
        font.setWeight(QFont.Normal)
        font.setHintingPreference(QFont.PreferNoHinting)
        metrics = QFontMetricsF(font)
        layout = QTextLayout(line.text, font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        option.setTextDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        layout.setTextOption(option)
        layout.beginLayout()
        rows: list[_Row] = []
        top = 0.0
        while True:
            text_line = layout.createLine()
            if not text_line.isValid():
                break
            text_line.setLineWidth(max_width)
            text_line.setPosition(QPointF(0.0, top))
            start, length = text_line.textStart(), text_line.textLength()
            chunk = _utf16_slice(line.text, start, length)
            width = text_line.naturalTextWidth()
            x = (max_width - width) / 2.0
            path = QPainterPath()
            path.addText(QPointF(x, 0.0), font, chunk)
            rows.append(_Row(path, width, metrics.ascent(), start, length, chunk))
            top += metrics.height()
        layout.endLayout()
        if not rows:
            rows.append(_Row(QPainterPath(), 0.0, metrics.ascent(), 0, 0, ""))
            top = metrics.height()
        result = _LineLayout(rows, top, max_width, rtl, font, metrics)
        self._line_layouts[key] = result
        return result

    def _prepare_sweeps(self) -> None:
        """Sweep windows and per-character weights for lines with a time but no word times."""
        line_only = [bool(line.text.strip()) and line.start_ms is not None
                     and all(segment.start_ms is None for segment in line.segments)
                     for line in self._lines]
        self._sweep_weights = [sung_weights(line.text) if only else [] for line, only in
                               zip(self._lines, line_only)]
        self._sweeps = line_sweeps(
            [float(line.start_ms) if line.start_ms is not None else None for line in self._lines],
            [sum(weights) for weights in self._sweep_weights], line_only)

    def _line_end(self, index: int) -> float:
        for following in range(index + 1, len(self._lines)):
            if self._lines[following].start_ms is not None:
                return float(self._lines[following].start_ms)
        line = self._lines[index]
        ends = [float(segment.end_ms) for segment in line.segments if segment.end_ms is not None]
        if ends:
            return max(ends)
        return float(line.start_ms or 0) + 4000.0

    def _ensure_layout(self) -> bool:
        if not self._layout_dirty:
            return False
        self._layout_dirty = False
        self._line_layouts.clear()
        self._gradients.clear()
        self._blocks = []
        self._scroll_path = None
        if not self._lines:
            return True
        width = max(80.0, self.width() - 2.0 * self._margin())
        self._content_width = width
        self._base_px = self._compute_base_px()
        if self.compact:
            starts = list(self._starts)
            centres = [float(i) * 100.0 for i in range(len(self._lines))]
            self._scroll_path = ScrollPath(centres, starts, 1.0, 90.0)
        else:
            top = 0.0
            gap = self._base_px * 0.6
            centres = []
            for index, line in enumerate(self._lines):
                layout = self._line_layout(line, self._base_px, width)
                self._blocks.append(_Block(top, layout.height, index, layout))
                centres.append(top + layout.height / 2.0)
                top += layout.height + gap
            self._scroll_path = ScrollPath(centres, list(self._starts), 1.0,
                                           self._base_px * _INTRO_OFFSET_FACTOR)
        self._emphasis.reset(len(self._lines))
        self._layout_builds += 1
        return True

    def resizeEvent(self, event):
        self._layout_dirty = True
        super().resizeEvent(event)

    def changeEvent(self, event):
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.PaletteChange,
                            QEvent.Type.StyleChange, QEvent.Type.WindowStateChange):
            if event.type() != QEvent.Type.WindowStateChange:
                self._layout_dirty = True
            self._ensure_timer()
        super().changeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._bind_screen()
        self._ensure_timer()
        self.update()

    def hideEvent(self, event):
        self._timer.stop()
        self._last_frame_ms = None
        super().hideEvent(event)

    # ---------------------------------------------------------------- text timing
    @staticmethod
    def line_index(lines: list[Line], t_ms: float) -> int:
        starts = [line.start_ms if line.start_ms is not None else 1e18 for line in lines]
        return bisect_right(starts, t_ms) - 1

    def current_line_index(self) -> int:
        return bisect_right(self._starts, self._song_time) - 1

    def current_line_text(self) -> str:
        index = self.current_line_index()
        return self._lines[index].text if 0 <= index < len(self._lines) else ""

    @property
    def scroll_offset(self) -> float:
        return self._scroll

    @property
    def scroll_residual(self) -> float:
        if self._scroll_path is None:
            return 0.0
        return self._scroll - self._scroll_path.position_at(self._song_time)

    @property
    def scroll_peak_velocity(self) -> float:
        return self._scroll_path.peak_velocity if self._scroll_path is not None else 0.0

    @property
    def scroll_peak_acceleration(self) -> float:
        return self._scroll_path.peak_acceleration if self._scroll_path is not None else 0.0

    @property
    def current_line_scale(self) -> float:
        # The most emphasised line: during a glide that is the incoming line, so the recorded
        # scale stays continuous when the current index flips at the line's start time.
        emphasis = max(self._emphasis.values, default=0.0)
        return 1.0 + _GROW * emphasis

    @property
    def layout_builds(self) -> int:
        return self._layout_builds

    def lit_units(self, index: int, t_ms: float) -> float:
        """How many UTF-16 units of line ``index`` are lit at ``t_ms``."""
        if not 0 <= index < len(self._lines):
            return 0.0
        line = self._lines[index]
        if not line.segments:
            return 0.0
        if all(segment.start_ms is None for segment in line.segments):
            window = self._sweeps[index] if index < len(self._sweeps) else None
            if window is None:
                return word_fill(t_ms, line.start_ms, self._line_end(index)) * _utf16_len(line.text)
            return _utf16_units(line.text, sweep_lit(self._sweep_weights[index], t_ms, window))
        lit = 0.0
        for position, segment in enumerate(line.segments):
            if not segment.text:
                continue
            if segment.start_ms is None:
                fill = 1.0 if line.start_ms is not None and t_ms >= line.start_ms else 0.0
            else:
                end = segment.end_ms
                if end is None:
                    end = (line.segments[position + 1].start_ms
                           if position + 1 < len(line.segments) else None)
                    if end is None:
                        end = self._line_end(index)
                fill = word_fill(t_ms, segment.start_ms, end)
            lit += fill * _utf16_len(segment.text)
            if fill < 1.0:
                break
        return lit

    # ---------------------------------------------------------------- painting
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        if self.width() < 2 or self.height() < 2:
            return
        if not self._lines:
            self._draw_message(painter)
            return
        if not self._scroll_ready:
            self.advance(self.elapsed_ms(), 0.0)
        if self.compact:
            self._paint_compact(painter)
        else:
            self._paint_column(painter)

    def _draw_message(self, painter: QPainter) -> None:
        headline, detail = self._message
        if not headline:
            return
        font = QFont(self.font())
        font.setPixelSize(max(14, int(self.height() * 0.16)))
        font.setHintingPreference(QFont.PreferNoHinting)
        painter.setFont(font)
        painter.setPen(_MESSAGE)
        height = self.height() * (0.55 if detail else 1.0)
        painter.drawText(QRectF(0.0, 0.0, float(self.width()), float(height)),
                         Qt.AlignCenter | Qt.TextWordWrap, headline)
        if detail:
            detail_font = QFont(font)
            detail_font.setPixelSize(max(11, int(font.pixelSize() * 0.52)))
            painter.setFont(detail_font)
            painter.setPen(_DETAIL)
            painter.drawText(QRectF(0.0, height, float(self.width()), self.height() - height),
                             Qt.AlignCenter | Qt.TextWordWrap, detail)

    def _paint_column(self, painter: QPainter) -> None:
        middle = self.height() / 2.0
        current = self.current_line_index()
        for block in self._blocks:
            center = middle + block.top + block.height / 2.0 - self._scroll
            if center < -block.height or center > self.height() + block.height:
                continue
            near = max(0.0, 1.0 - abs(center - middle) / (self.height() * 0.5))
            fade = _smooth(min(1.0, near * 2.2))
            if fade <= 0.01:
                continue
            emphasis = self._emphasis[block.index] if block.index < len(self._emphasis) else 0.0
            scale = 1.0 + _GROW * emphasis
            top = middle + block.top - self._scroll
            painter.save()
            painter.translate(self.width() / 2.0, center)
            painter.scale(scale, scale)
            painter.translate(-self.width() / 2.0, -center)
            self._draw_line(painter, block.layout, top, block.index, emphasis, fade, current)
            painter.restore()

    def _paint_compact(self, painter: QPainter) -> None:
        path = self._scroll_path
        if path is None:
            return
        current = self.current_line_index()
        phase = path.phase_at(self._song_time)
        if phase.is_transition:
            eased = smootherstep(phase.u)
            old = phase.from_index
            new = 0 if old < 0 else old + 1
        else:
            eased, old, new = 1.0, -1, current
        if new < 0 or new >= len(self._lines):
            return
        current_px = self._compute_base_px()
        next_px = max(11.0, current_px * 0.62)
        width = max(80.0, self.width() - 2.0 * self._margin())
        new_layout = self._line_layout(self._lines[new], current_px, width)
        next_layout = (self._line_layout(self._lines[new + 1], next_px, width)
                       if new + 1 < len(self._lines) else None)
        gap = max(2.0, current_px * 0.18)
        total = new_layout.height + (gap + next_layout.height if next_layout is not None else 0.0)
        top = max(0.0, (self.height() - total) / 2.0)
        next_top = top + new_layout.height + gap
        small_scale = next_px / current_px
        new_scale = small_scale + (1.0 + _GROW * eased - small_scale) * eased

        if old >= 0 and old < len(self._lines) and eased < 0.999:
            old_layout = self._line_layout(self._lines[old], current_px, width)
            old_top = top - eased * (old_layout.height + gap)
            self._draw_compact_line(painter, old_layout, old_top, old, 1.0 - eased,
                                    1.0 - eased, 1.0 + _GROW * (1.0 - eased))
        new_top = next_top + (top - next_top) * eased
        self._draw_compact_line(painter, new_layout, new_top, new, eased,
                                0.85 + 0.15 * eased, new_scale)
        if next_layout is not None:
            self._draw_compact_line(painter, next_layout, next_top, new + 1, 0.0,
                                    max(0.0, eased) * 0.85, 1.0)

    def _draw_compact_line(self, painter: QPainter, layout: _LineLayout, top: float,
                           index: int, emphasis: float, opacity: float,
                           scale: float | None = None) -> None:
        if opacity <= 0.01:
            return
        center = top + layout.height / 2.0
        if scale is None:
            scale = 1.0 + _GROW * emphasis
        painter.save()
        painter.setOpacity(opacity)
        painter.translate(self.width() / 2.0, center)
        painter.scale(scale, scale)
        painter.translate(-self.width() / 2.0, -center)
        color_current = index if emphasis >= 0.5 else index - 1
        self._draw_line(painter, layout, top, index, emphasis, 1.0, color_current)
        painter.restore()

    def _line_color(self, index: int, current: int, emphasis: float) -> QColor:
        base = _PAST if index < current else _FUTURE
        if emphasis > 0.0:
            return _mix(base, _CURRENT, emphasis)
        return base

    def _draw_line(self, painter: QPainter, layout: _LineLayout, top: float, index: int,
                   emphasis: float, fade: float, current: int) -> None:
        painter.setOpacity(fade)
        color = self._line_color(index, current, emphasis)
        for row in layout.rows:
            painter.save()
            painter.translate(0.0, top + row.baseline)
            painter.fillPath(row.path, color)
            painter.restore()
        if emphasis <= 0.01:
            return
        lit = min(self.lit_units(index, self._song_time), float(_utf16_len(self._lines[index].text)))
        if lit <= 0.0:
            return
        feather = max(1.0, layout.font.pixelSize() * _FEATHER_FACTOR)
        painter.setOpacity(fade * emphasis)
        for row in layout.rows:
            row_start, row_end = row.start, row.start + row.length
            if lit <= row_start:
                continue
            partial = None if lit >= row_end else lit - row_start
            if partial is None:
                painter.save()
                painter.translate(0.0, top + row.baseline)
                self._glow_row(painter, row.path, layout.font.pixelSize())
                painter.fillPath(row.path, _GOLD)
                painter.restore()
                continue
            prefix_width = self._prefix_width(layout, row, partial)
            x0 = (layout.width - row.width) / 2.0
            x = x0 + row.width - prefix_width if layout.rtl else x0 + prefix_width
            gradient = self._gradient(x, feather, layout.rtl)
            painter.save()
            painter.translate(0.0, top + row.baseline)
            self._glow_row(painter, row.path, layout.font.pixelSize(), gradient)
            painter.setPen(Qt.NoPen)
            painter.setBrush(gradient)
            painter.drawPath(row.path)
            painter.restore()

    @staticmethod
    def _prefix_width(layout: _LineLayout, row: _Row, units: float) -> float:
        """Width of a fractional prefix, interpolated between neighbouring glyph advances."""
        whole = max(0, min(row.length, int(math.floor(units))))
        first = _utf16_slice(row.text, 0, whole)
        width = layout.metrics.horizontalAdvance(first)
        fraction = units - whole
        if whole >= row.length or fraction <= 0.0:
            return width
        following = _utf16_slice(row.text, 0, min(row.length, whole + 1))
        return width + (layout.metrics.horizontalAdvance(following) - width) * fraction

    def _glow_row(self, painter: QPainter, path: QPainterPath, font_px: float,
                  gradient: QLinearGradient | None = None) -> None:
        pen = QPen(_GLOW)
        pen.setWidthF(max(1.0, font_px * 0.12))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        if gradient is not None:
            pen.setBrush(gradient)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.setPen(Qt.NoPen)

    def _gradient(self, boundary: float, feather: float, rtl: bool) -> QLinearGradient:
        bucket = int(round(boundary * 4.0))
        key = (bucket, rtl)
        cached = self._gradients.get(key)
        if cached is not None:
            return cached
        if len(self._gradients) > 2048:
            self._gradients.clear()
        snapped = bucket / 4.0
        if rtl:
            gradient = QLinearGradient(snapped + feather * 0.6, 0.0, snapped - feather * 5.0, 0.0)
        else:
            gradient = QLinearGradient(snapped - feather * 5.0, 0.0, snapped + feather * 0.6, 0.0)
        span = feather * 5.6
        gradient.setColorAt(0.0, _GOLD)
        gradient.setColorAt((feather * 4.0) / span, _HEAD)
        gradient.setColorAt(1.0, QColor(_HEAD.red(), _HEAD.green(), _HEAD.blue(), 0))
        self._gradients[key] = gradient
        return gradient
