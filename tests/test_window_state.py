import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricloom import config  # noqa: E402
from lyricloom.app.main import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(app, cond, timeout=10):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert cond()


def _audio(root):
    audio = root / "Artist" / "Album" / "01 - Song.flac"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"x")
    return audio


def test_geometry_columns_and_splitter_are_restored_and_clamped(app, tmp_path):
    w = MainWindow(tmp_path)
    w.show()
    app.processEvents()
    w.resize(700, 500)
    w.move(20, 30)
    w.splitter.setSizes([300, 600])
    app.processEvents()
    w.table.setColumnWidth(0, 111)
    w._save_ui_state()
    w.dirty = False
    w.close()

    screen = QGuiApplication.primaryScreen()
    available = screen.availableGeometry()
    max_width = max(320, int(available.width() * 0.9))
    max_height = max(240, int(available.height() * 0.9))

    w2 = MainWindow(tmp_path)
    try:
        assert (w2.width(), w2.height()) == (700, 500)
        assert w2.width() <= max_width and w2.height() <= max_height
        assert available.left() <= w2.x() <= available.right()
        assert available.top() <= w2.y() <= available.bottom()
        assert w2.table.columnWidth(0) == 111
        w2.show()
        app.processEvents()
        assert len(w2.splitter.sizes()) == 2 and all(size > 0 for size in w2.splitter.sizes())
        assert isinstance(config.setting("splitter"), list)

        # A saved geometry from a bigger monitor must not leave the window off-screen.
        w2.resize(100000, 100000)
        w2.move(-100000, -100000)
        w2._clamp_to_screen()
        assert w2.width() <= max_width and w2.height() <= max_height
        assert w2.x() >= available.left() and w2.y() >= available.top()
    finally:
        w2.dirty = False
        w2.close()


def test_last_selected_track_is_restored_after_the_first_scan(app, tmp_path):
    audio = _audio(tmp_path)
    w = MainWindow(tmp_path)
    try:
        _wait(app, lambda: w.proxy.rowCount() == 1)
        w.load(audio)
        assert w.audio == audio
        w.dirty = False
        w.close()
    finally:
        w.dirty = False

    w2 = MainWindow(tmp_path)
    try:
        _wait(app, lambda: w2.audio == audio)
        assert config.setting("library/last_track") == str(audio)
    finally:
        w2.dirty = False
        w2.close()
