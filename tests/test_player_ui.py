import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricloom import cache  # noqa: E402
from lyricloom.app.main import MainWindow  # noqa: E402
from lyricloom.app.media import vocal_source  # noqa: E402
from lyricloom.stages.separate import kept_vocals_path  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(app, cond, timeout=10):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert cond()


class FakePlayer:
    def __init__(self):
        self.position_ms = 0
        self.state = QMediaPlayer.PausedState
        self.status = QMediaPlayer.LoadedMedia
        self.sources = []
        self.positions = []
        self.plays = 0
        self.error = ""

    def position(self):
        return self.position_ms

    def setPosition(self, value):
        self.position_ms = int(value)
        self.positions.append(int(value))

    def playbackState(self):
        return self.state

    def setSource(self, url):
        self.sources.append(url.toLocalFile())

    def play(self):
        self.plays += 1
        self.state = QMediaPlayer.PlayingState

    def pause(self):
        self.state = QMediaPlayer.PausedState

    def stop(self):
        self.state = QMediaPlayer.StoppedState

    def mediaStatus(self):
        return self.status

    def duration(self):
        return 100000

    def errorString(self):
        return self.error


def _track(root, name, lrc=None):
    audio = root / "Artist" / "Album" / name
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"x")
    if lrc is not None:
        audio.with_suffix(".lrc").write_text(lrc, encoding="utf-8")
    return audio


def _window(app, root):
    w = MainWindow(root)
    w.timer.stop()
    w.player = FakePlayer()
    return w


def test_seek_on_click_seeks_to_the_clicked_position(app, tmp_path):
    audio = _track(tmp_path, "01 - Song.flac")
    w = _window(app, tmp_path)
    try:
        w.resize(1200, 800)
        w.show()
        app.processEvents()
        w.load(audio)
        w.seek.setRange(0, 100000)
        w.seek.setValue(0)
        app.processEvents()

        QTest.mouseClick(w.seek, Qt.LeftButton,
                         pos=QPoint(int(w.seek.width() * 0.6), w.seek.height() // 2))
        app.processEvents()

        assert w.seek.value() > 40000          # jumped to the click, not one page step
        assert w.player.positions             # the click reached the player
        assert abs(w.player.positions[-1] - w.seek.value()) <= 1
    finally:
        w.dirty = False
        w.close()


def test_vocals_only_keeps_the_position(app, tmp_path, monkeypatch):
    audio = _track(tmp_path, "01 - Song.flac", "[00:01.00]line\n")
    other = _track(tmp_path, "02 - Other.flac", "[00:01.00]other\n")
    work_vocals = cache.work_dir(audio) / "vocals.wav"
    work_vocals.write_bytes(b"wav")
    w = _window(app, tmp_path)
    try:
        w.load(audio)
        assert w.vocals.isEnabled() and not w.vocals.isChecked()
        assert Path(w.player.sources[-1]) == audio

        w.player.position_ms = 12345
        w.player.state = QMediaPlayer.PlayingState
        w.vocals.setChecked(True)
        assert w._pending_seek == 12345 and w._pending_play
        assert Path(w.player.sources[-1]) == work_vocals

        w._media_status(QMediaPlayer.LoadedMedia)
        assert w.player.positions[-1] == 12345
        assert w.player.plays == 1
        assert w._pending_seek is None

        # The work cache can disappear; the durable kept FLAC still enables the checkbox.
        work_vocals.unlink()
        kept = kept_vocals_path(audio)
        kept.parent.mkdir(parents=True, exist_ok=True)
        kept.write_bytes(b"flac")
        assert vocal_source(audio) == kept
        w.load(audio)
        assert w.vocals.isEnabled() and str(kept) in w.vocals.toolTip()
        w.vocals.setChecked(True)
        assert Path(w.player.sources[-1]) == kept

        # A new track without vocals must not keep the previous track's checked state.
        w.load(other)
        assert not w.vocals.isEnabled() and not w.vocals.isChecked()
        assert Path(w.player.sources[-1]) == other
    finally:
        w.dirty = False
        w.close()


def test_main_player_reports_errors_and_handles_end_of_media(app, tmp_path):
    audio = _track(tmp_path, "01 - Song.flac")
    w = _window(app, tmp_path)
    try:
        w.load(audio)
        w._media_error(QMediaPlayer.ResourceError, "No such file")
        assert "Playback error" in w.statusBar().currentMessage()
        assert "No such file" in w.statusBar().currentMessage()

        w.player.position_ms = 5000
        w._media_status(QMediaPlayer.EndOfMedia)
        assert w.player.positions[-1] == 0
        assert w._pending_seek is None

        w.player.error = "Cannot open the media"
        w._media_status(QMediaPlayer.InvalidMedia)
        assert "Cannot open the media" in w.statusBar().currentMessage()
    finally:
        w.dirty = False
        w.close()


def test_main_compact_view_follows_the_player_and_stops_when_paused(app, tmp_path):
    audio = _track(tmp_path, "01 - Song.flac",
                   "[00:01.00]<00:01.00>old <00:01.50>words<00:02.00>\n")
    w = _window(app, tmp_path)
    try:
        w.show()
        app.processEvents()
        w.load(audio)
        w.player.position_ms = 1500
        w.player.state = QMediaPlayer.PlayingState
        w._tick()
        w.now.advance(w.now.elapsed_ms())
        assert w.now.current_line_text() == "old words"
        assert w.now.is_animating

        w.player.state = QMediaPlayer.PausedState
        w._tick()
        assert not w.now.is_animating
        assert w.now.current_line_text() == "old words"
    finally:
        w.dirty = False
        w.hide()
        w.close()


def test_compact_lyric_view_clears_for_a_track_without_lyrics(app, tmp_path):
    first = _track(tmp_path, "01 - First.flac",
                   "[re:LyricLoom 2.1.0]\n[00:01.00]<00:01.00>old <00:01.50>words<00:02.00>\n")
    second = _track(tmp_path, "02 - Second.flac")
    w = _window(app, tmp_path)
    try:
        w.load(first)
        assert w.doc is not None and w.lines.count() == 1
        assert len(w.now._lines) == 1

        w.load(second)
        assert w.doc is None
        assert w.now.current_line_text() == ""
        assert w.now._lines == []

        w.load(first)
        assert len(w.now._lines) == 1
        w._reload_lrc()
        assert len(w.now._lines) == 1
    finally:
        w.dirty = False
        w.close()
