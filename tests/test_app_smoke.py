import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from lyricloom.app.main import MainWindow, parse_ts  # noqa: E402
from lyricloom.lrc import parse_lrc  # noqa: E402

LRC = "[re:LyricLoom 1.0.0]\n[#source:netease conf:0.53]\n[#review:1]\n" \
      "[00:01.00]<00:01.00>eu <00:01.50>vou<00:02.00>\n[00:03.00]<00:03.00>de <00:03.40>novo<00:04.00>\n"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(app, cond, timeout=10):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert cond()


def test_parse_ts():
    assert parse_ts("01:23.45") == 83450 and parse_ts("1:02") == 62000 and parse_ts("x") is None


def test_window_lists_loads_nudges_and_saves(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lyricloom.app.main.QMessageBox.question",
                        lambda *args, **kwargs: QMessageBox.Yes)
    audio = tmp_path / "Artist" / "Album" / "01 - Song.flac"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"x")
    audio.with_suffix(".lrc").write_text(LRC, encoding="utf-8")
    w = MainWindow(tmp_path)
    try:
        _wait(app, lambda: w.proxy.rowCount() == 1)
        assert w.proxy.index(0, 2).data() == "review"
        w.table.selectRow(0)
        _wait(app, lambda: w.doc is not None)
        assert w.lines.count() == 2
        w.lines.setCurrentRow(0)
        w.words.selectRow(1)
        w.nudge(50)
        assert w.dirty and w.doc.lines[0].segments[1].start_ms == 1550
        w.save()
        assert not w.dirty
        assert audio.with_name("01 - Song.lrc.bak").exists()
        saved = parse_lrc(audio.with_suffix(".lrc").read_text(encoding="utf-8"))
        assert saved.lines[0].segments[1].start_ms == 1550
        w.lines.setCurrentRow(0)
        w.words.selectRow(0)
        from unittest import mock
        with mock.patch("lyricloom.app.main.QInputDialog.getText", return_value=("ok", True)) as ask:
            w.btn_add_word.click()   # the real button: must open the dialog, not take clicked's bool
            assert ask.called and w.doc.lines[0].text == "eu ok vou"
        w.delete_current_word()
        w.words.selectRow(0)   # after a delete the selection moves to the next word
        w.add_word("já")
        assert w.doc.lines[0].text == "eu já vou"
        w.delete_current_word()
        assert w.doc.lines[0].text == "eu vou"
        w.add_line("linha nova")
        assert [l.text for l in w.doc.lines] == ["eu vou", "linha nova", "de novo"]
        w.lines.setCurrentRow(1)
        w.merge_current_line()
        assert [l.text for l in w.doc.lines] == ["eu vou linha nova", "de novo"]
        w.add_line("linha nova")
        w.lines.setCurrentRow(1)
        w.delete_current_line()
        w.lines.setCurrentRow(0)
        w.delete_current_line()
        assert w.dirty and w.lines.count() == 1 and w.doc.lines[0].text == "de novo"
        assert w.doc.meta["#review"] == "0"

        # progress bar: a track in the separation stage shows a moving, labelled bar
        w._prog = {"done": 0, "total": 2, "name": "x", "stage": "lyrics", "since": time.time(), "dur": 240.0}
        w._track_started(str(audio))
        assert w.proxy.index(0, 2).data() == "processing"
        w._stage_changed("separate")
        w._prog["since"] -= 120
        w._update_progress()
        assert 0 < w.progress.value() < 500 and "separating vocals" in w.progress.format()

        # AssemblyAI key button writes the (test) key file
        from lyricloom import config
        with mock.patch("lyricloom.app.main.QInputDialog.getText", return_value=("newkey", True)):
            w.btn_key.click()
        assert config.read_assemblyai_key() == "newkey"
    finally:
        w.dirty = False
        w.close()
