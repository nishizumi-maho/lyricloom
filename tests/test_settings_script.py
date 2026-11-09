import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from lyricloom import config  # noqa: E402
from lyricloom.app.main import MainWindow  # noqa: E402
from lyricloom.lrc import parse_lrc  # noqa: E402
from lyricloom.model import Line, LrcDoc, Segment  # noqa: E402
from lyricloom.stages.write import japanese_path, romaji_path, write_lyrics  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(app, cond, timeout=10):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert cond()


def _doc():
    return LrcDoc({"ti": "Synthetic Song"},
                  [Line(1000, [Segment("試験が", 1000, 1400), Segment("歌を", 1400, 1800)])])


def _setup(tmp_path):
    audio = tmp_path / "Artist" / "Album" / "01 - Song.flac"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"x")
    write_lyrics(audio, _doc())
    config.set_library_root(tmp_path)
    return audio


class FakeSettings:
    Accepted = QDialog.Accepted
    change_to = "romaji"

    def __init__(self, parent=None):
        pass

    def exec(self):
        config.set_japanese_script(self.change_to)
        return self.Accepted


def test_settings_script_change_confirms_and_rewrites_with_a_backup(app, tmp_path, monkeypatch):
    audio = _setup(tmp_path)
    before = audio.with_suffix(".lrc").read_bytes()
    config.set_japanese_script("japanese")
    monkeypatch.setattr("lyricloom.app.main.SettingsDialog", FakeSettings)
    seen = []
    monkeypatch.setattr("lyricloom.app.main.QMessageBox.question",
                        lambda *args, **kwargs: seen.append(args[2]) or QMessageBox.Yes)

    w = MainWindow(tmp_path)
    try:
        _wait(app, lambda: w.proxy.rowCount() == 1)
        w.open_settings()
        assert seen and "1 Japanese song" in seen[0] and "romaji" in seen[0]
        assert config.japanese_script() == "romaji"
        assert parse_lrc(audio.with_suffix(".lrc").read_text(encoding="utf-8")).lines[0].text.startswith("shikenga")
        assert audio.with_name("01 - Song.lrc.bak").read_bytes() == before
        assert japanese_path(audio).exists() and romaji_path(audio).exists()
        assert w.script.currentIndex() == 1
    finally:
        w.dirty = False
        w.close()


def test_settings_script_change_can_be_declined(app, tmp_path, monkeypatch):
    audio = _setup(tmp_path)
    before = audio.with_suffix(".lrc").read_bytes()
    config.set_japanese_script("japanese")
    monkeypatch.setattr("lyricloom.app.main.SettingsDialog", FakeSettings)
    monkeypatch.setattr("lyricloom.app.main.QMessageBox.question",
                        lambda *args, **kwargs: QMessageBox.No)

    w = MainWindow(tmp_path)
    try:
        _wait(app, lambda: w.proxy.rowCount() == 1)
        w.open_settings()
        assert config.japanese_script() == "japanese"
        assert audio.with_suffix(".lrc").read_bytes() == before
        assert w.script.currentIndex() == 0
    finally:
        w.dirty = False
        w.close()
