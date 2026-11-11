import csv
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFontDatabase, QImage, QPainter, QRegion  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from lyricloom.app.lyric_view import LyricView, is_rtl  # noqa: E402
from lyricloom.lrc import format_ts, parse_lrc  # noqa: E402
from lyricloom.model import Line, LrcDoc, Segment  # noqa: E402

FRAME_MS = 1000.0 / 144.0


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    for candidate in (r"C:\Windows\Fonts\segoeui.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(candidate).is_file():
            QFontDatabase.addApplicationFont(candidate)
            break
    return application


def _fixture_doc() -> LrcDoc:
    rows = []
    for i in range(10):
        start = 1000 + i * 2000
        rows.append(f"[{format_ts(start)}]<{format_ts(start)}>line "
                    f"<{format_ts(start + 500)}>{i} "
                    f"<{format_ts(start + 1000)}>sung<{format_ts(start + 1800)}>")
    return parse_lrc("\n".join(rows))


def _make_view(app, compact=False) -> LyricView:
    view = LyricView(compact=compact, animate_when_paused=False)
    view.resize(960, 540)
    view.set_doc(_fixture_doc())
    view.show()
    app.processEvents()
    return view


def _record(view: LyricView, *, frames: int = 20 * 144, seek_at_ms: float = 10000.0,
            seek_delta_ms: float = 4000.0):
    records = []
    for frame in range(frames):
        real_ms = frame * FRAME_MS
        position_ms = real_ms if real_ms < seek_at_ms else real_ms + seek_delta_ms
        view.sample(position_ms, True, real_ms)
        view.advance(real_ms)
        records.append({
            "frame": frame,
            "real_ms": real_ms,
            "player_ms": position_ms,
            "scroll": view.scroll_offset,
            "scale": view.current_line_scale,
            "residual": view.scroll_residual,
        })
    return records


def test_widget_frame_series_stays_within_the_scroll_path_bounds_and_records_artifacts(
        app, tmp_path):
    """Design section 7: drive the real widget at 144 frames/s through a 20 s fixture with a seek
    in the middle, then check the continuity bounds on the recorded scroll offset."""
    view = _make_view(app)
    try:
        records = _record(view)
        frame_seconds = FRAME_MS / 1000.0
        seek_start = next(i for i, row in enumerate(records) if row["real_ms"] >= 10000.0)
        settle_index = next((i for i in range(seek_start, len(records))
                             if abs(records[i]["residual"]) < 2.0), None)
        assert settle_index is not None
        settle_ms = records[settle_index]["real_ms"] - records[seek_start]["real_ms"]
        assert settle_ms <= 400.0

        # The residual spring deliberately moves faster than the path while it absorbs the seek;
        # the path's continuity bounds apply outside that short settle window.
        def bounds(sequence):
            max_step, max_jump = 0.0, 0.0
            previous_velocity = None
            for i in range(1, len(sequence)):
                step = abs(sequence[i]["scroll"] - sequence[i - 1]["scroll"])
                max_step = max(max_step, step)
                velocity = (sequence[i]["scroll"] - sequence[i - 1]["scroll"]) / frame_seconds
                if previous_velocity is not None:
                    max_jump = max(max_jump, abs(velocity - previous_velocity))
                previous_velocity = velocity
            return max_step, max_jump

        before = bounds(records[:seek_start])
        after = bounds(records[settle_index + 1:])
        max_step = max(before[0], after[0])
        max_velocity_jump = max(before[1], after[1])
        assert view.scroll_peak_velocity > 0
        # A hundredth of a pixel covers the clock's sub-millisecond sample extrapolation; the
        # continuous path itself is bounded exactly by peak_velocity * frame.
        assert max_step <= view.scroll_peak_velocity * frame_seconds + 0.01
        assert max_velocity_jump <= view.scroll_peak_acceleration * frame_seconds + 0.1
        assert abs(records[seek_start]["scroll"] - records[seek_start - 1]["scroll"]) < 1.0

        out_dir = Path(os.environ.get("LYRICLOOM_SMOOTH_DIR", tmp_path))
        out_dir.mkdir(parents=True, exist_ok=True)
        with (out_dir / "frame-series.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)

        strip = _render_line_change_strip(app, out_dir)
        assert strip.is_file() and strip.stat().st_size > 0
    finally:
        view.hide()
        view.close()


def _render_line_change_strip(app, out_dir: Path) -> Path:
    view = LyricView(animate_when_paused=False)
    view.resize(960, 360)
    view.set_doc(_fixture_doc())
    view.show()
    app.processEvents()
    frames = []
    for frame in range(int(2700 / FRAME_MS), int(3150 / FRAME_MS) + 1, 4):
        real_ms = frame * FRAME_MS
        view.sample(real_ms, True, real_ms)
        view.advance(real_ms)
        image = QImage(view.width(), view.height(), QImage.Format_ARGB32)
        image.fill(QColor("#0b1027"))
        painter = QPainter(image)
        view.render(painter, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
        painter.end()
        frames.append(image)
    if not frames:
        frames = [QImage(view.width(), view.height(), QImage.Format_ARGB32)]
    # A compact 4-column contact sheet of the line change (each frame scaled to 480x180).
    thumb_w, thumb_h, columns = 480, 180, 4
    rows = (len(frames) + columns - 1) // columns
    strip = QImage(thumb_w * columns, thumb_h * rows, QImage.Format_ARGB32)
    strip.fill(QColor("#040614"))
    painter = QPainter(strip)
    for index, image in enumerate(frames):
        scaled = image.scaled(thumb_w, thumb_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        painter.drawImage((index % columns) * thumb_w, (index // columns) * thumb_h, scaled)
    painter.end()
    path = out_dir / "line-change-strip.png"
    strip.save(str(path))
    view.hide()
    view.close()
    return path


def test_layouts_are_cached_and_rebuilt_only_when_text_size_or_script_changes(app):
    view = LyricView(animate_when_paused=False)
    view.resize(900, 500)
    view.set_doc(_fixture_doc())
    view.show()
    app.processEvents()
    view.advance(0.0)
    builds = view.layout_builds
    assert builds == 1
    for frame in range(1, 50):
        view.advance(frame * FRAME_MS)
    assert view.layout_builds == builds

    view.resize(1000, 500)
    app.processEvents()
    view.advance(2500.0)
    assert view.layout_builds == builds + 1

    view.set_doc(parse_lrc("[00:01.00]<00:01.00>different<00:02.00>"))
    view.advance(2600.0)
    assert view.layout_builds == builds + 2
    view.hide()
    view.close()


def test_resize_keeps_the_shown_scroll_and_absorbs_the_layout_change(app):
    view = _make_view(app)
    try:
        for frame in range(int(5000 / FRAME_MS)):
            real_ms = frame * FRAME_MS
            view.sample(real_ms, True, real_ms)
            view.advance(real_ms)
        shown = view.scroll_offset
        view.resize(1100, 620)
        app.processEvents()
        view.advance(5000.0 + FRAME_MS)
        assert view.scroll_offset == pytest.approx(shown, abs=0.01)
        assert abs(view.scroll_residual) > 0.1   # the spring, not a snap, carries the change
    finally:
        view.hide()
        view.close()


def test_rtl_and_line_only_lyrics_are_understood(app):
    assert is_rtl("שלום עולם")
    assert is_rtl("مرحبا")
    assert not is_rtl("hello")
    assert not is_rtl("こんにちは")

    doc = LrcDoc({}, [Line(1000, [Segment("שלום עולם", None, None)])])
    view = LyricView(animate_when_paused=False)
    view.resize(800, 300)
    view.set_doc(doc)
    view.advance(1000.0)
    view.advance(3000.0)
    assert view.lit_units(0, 1000.0) == 0.0
    assert 0.0 < view.lit_units(0, 1300.0) < len(doc.lines[0].text)
    assert view.lit_units(0, 5000.0) == pytest.approx(len(doc.lines[0].text))
    view.close()


def test_line_synced_lyrics_sweep_at_the_songs_pace_from_just_after_each_tag(app):
    """A line tag usually comes a little before the voice, and a fixed pace runs ahead of slow
    lines: the sweep starts after the tag and lasts what the song's own lines take."""
    lines = [Line(1000 + 4000 * i, [Segment("the stars are falling down tonight", None, None)])
             for i in range(6)]
    lines.append(Line(40000, [Segment("one", 40000, 40400), Segment(" more", 40400, 41000)]))
    view = LyricView(animate_when_paused=False)
    view.resize(800, 300)
    view.set_doc(LrcDoc({}, lines))
    assert view.lit_units(0, 1100.0) == 0.0                 # the tag alone lights nothing
    # the line is sung over most of the 4 s before the next one, not in 3 s and then waiting
    assert view.lit_units(0, 3500.0) < 0.8 * len(lines[0].text)
    assert view.lit_units(0, 4900.0) == pytest.approx(len(lines[0].text))
    # word-timed lines keep their own times
    assert view.lit_units(6, 40000.0) == 0.0
    assert view.lit_units(6, 40400.0) == pytest.approx(3.0)
    view.close()


def test_compact_view_stops_its_timer_while_paused(app):
    view = LyricView(compact=True)
    view.resize(600, 80)
    view.set_doc(_fixture_doc())
    view.show()
    app.processEvents()
    try:
        view.sample(3500, True, 3500)
        view.advance(3500)
        assert view.is_animating
        assert view.current_line_text() == "line 1 sung"
        assert view.current_line_scale == pytest.approx(1.08)

        view.sample(3600, False, 3600)
        assert not view.is_animating
        view.sample(5500, False, 5500)
        assert not view.is_animating
        assert view.current_line_text() == "line 2 sung"
    finally:
        view.hide()
        view.close()
