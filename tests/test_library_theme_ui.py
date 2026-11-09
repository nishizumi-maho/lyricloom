import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QKeySequence, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricloom.app import theme  # noqa: E402
from lyricloom.app.main import MainWindow  # noqa: E402
from lyricloom.app.model import TrackRow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(app, cond, timeout=10):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert cond()


def _track(root, artist, name):
    audio = root / artist / "Album" / name
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"x")
    return audio


def _contrast(first, second) -> float:
    def luminance(color):
        values = []
        for channel in (color.redF(), color.greenF(), color.blueF()):
            values.append(channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4)
        return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]

    a, b = luminance(first), luminance(second)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def test_the_search_filter_is_debounced_by_200_ms(app, tmp_path):
    _track(tmp_path, "Alpha", "01 - One.flac")
    _track(tmp_path, "Beta", "02 - Two.flac")
    w = MainWindow(tmp_path)
    try:
        _wait(app, lambda: w.proxy.rowCount() == 2)
        assert w._search_timer.interval() == 200

        w.search.setText("zzz")
        assert w.proxy.rowCount() == 2      # not rebuilt on the keystroke
        _wait(app, lambda: w.proxy.rowCount() == 0, timeout=2)

        w.search.setText("alpha")
        _wait(app, lambda: w.proxy.rowCount() == 1, timeout=2)
        assert w.proxy.index(0, 0).data() == "Alpha"
    finally:
        w.dirty = False
        w.close()


def test_a_finished_track_updates_only_its_row(app, tmp_path, monkeypatch):
    audio = _track(tmp_path, "Alpha", "01 - One.flac")
    _track(tmp_path, "Beta", "02 - Two.flac")
    w = MainWindow(tmp_path)
    try:
        _wait(app, lambda: w.proxy.rowCount() == 2)
        changes = []
        w.model.dataChanged.connect(lambda *args: changes.append(args))

        def forbidden(_rows):
            raise AssertionError("the table was rebuilt for one finished track")

        monkeypatch.setattr(w.model, "set_rows", forbidden)
        w._update_row(TrackRow(audio, "Alpha", "One", "done", source="demo", conf=0.9))
        assert changes and changes[0][0].row() == changes[0][1].row()
        assert w.proxy.rowCount() == 2
        row = next(r for r in w.rows if r.path == audio)
        assert row.status == "done"
    finally:
        w.dirty = False
        w.close()


def test_dark_palette_selection_is_readable(app, tmp_path):
    try:
        assert theme.apply_theme(app, "light") == "light"
        light = app.palette()
        assert light.color(QPalette.Window).lightness() > 128

        assert theme.apply_theme(app, "dark") == "dark"
        dark = app.palette()
        assert dark.color(QPalette.Window).lightness() < 128
        highlight = dark.color(QPalette.Highlight)
        highlighted_text = dark.color(QPalette.HighlightedText)
        assert _contrast(highlight, highlighted_text) >= 4.5

        audio = _track(tmp_path, "Alpha", "01 - One.flac")
        w = MainWindow(tmp_path)
        try:
            _wait(app, lambda: w.proxy.rowCount() == 1)
            w.table.selectRow(0)
            app.processEvents()
            assert w.table.selectionModel().isSelected(w.proxy.index(0, 0))
            assert w.table.palette().color(QPalette.Highlight) == highlight
            assert _contrast(w.table.palette().color(QPalette.Highlight),
                             w.table.palette().color(QPalette.HighlightedText)) >= 4.5
            assert w.rows[0].path == audio
        finally:
            w.dirty = False
            w.close()
    finally:
        theme.apply_theme(app, "light")


def test_a_model_reset_keeps_the_selected_track(app, tmp_path):
    _track(tmp_path, "Alpha", "01 - One.flac")
    second = _track(tmp_path, "Beta", "02 - Two.flac")
    w = MainWindow(tmp_path)
    try:
        _wait(app, lambda: w.proxy.rowCount() == 2)
        assert w._select_path(second)
        app.processEvents()
        selected = w._current_path()
        assert selected == second

        w._fill_table()
        app.processEvents()
        assert w._current_path() == selected
        assert w.audio == second
    finally:
        w.dirty = False
        w.close()


def test_keyboard_shortcuts_and_accessible_names(app, tmp_path):
    _track(tmp_path, "Alpha", "01 - One.flac")
    w = MainWindow(tmp_path)
    try:
        _wait(app, lambda: w.proxy.rowCount() == 1)
        assert w.act_undo.shortcut() == QKeySequence(QKeySequence.Undo)
        assert QKeySequence("Ctrl+Shift+Z") in w.act_redo.shortcuts()
        expected = [QKeySequence("Ctrl+Return"), QKeySequence("Ctrl+Shift+Return"),
                    QKeySequence("F3"), QKeySequence("Shift+F3"), QKeySequence("Space"),
                    QKeySequence("Ctrl+K"), QKeySequence(QKeySequence.Find),
                    QKeySequence(QKeySequence.Delete)]
        for action, sequence in zip((w.act_accept_line, w.act_accept_all, w.act_next_review,
                                     w.act_prev_review, w.act_play_pause, w.act_karaoke, w.act_find,
                                     w.act_delete_line), expected):
            assert action.shortcut() == sequence
        for widget in (w.search, w.filter, w.script, w.table, w.seek, w.words, w.lines, w.progress):
            assert widget.accessibleName().strip()

        w.show()
        app.processEvents()
        w._focus_search()
        assert app.focusWidget() is w.search
    finally:
        w.dirty = False
        w.close()
