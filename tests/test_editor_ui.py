import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from lyricloom.app.main import MainWindow  # noqa: E402
from lyricloom.lrc import parse_lrc  # noqa: E402

LRC = ("[re:LyricLoom 2.1.0]\n[#engine:7]\n[#source:netease conf:0.53]\n[#review:0]\n"
       "[00:01.00]<00:01.00>eu <00:01.50>vou<00:02.00>\n"
       "[00:03.00]<00:03.00>de <00:03.40>novo<00:04.00>\n")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(app, cond, timeout=10):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert cond()


def _audio(root, lrc=LRC):
    audio = root / "Artist" / "Album" / "01 - Song.flac"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"x")
    audio.with_suffix(".lrc").write_text(lrc, encoding="utf-8")
    return audio


def _window(app, root):
    w = MainWindow(root)
    _wait(app, lambda: w.proxy.rowCount() == 1)
    w.timer.stop()
    w.table.selectRow(0)
    _wait(app, lambda: w.doc is not None)
    return w


def test_undo_redo_for_three_editor_operations(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lyricloom.app.main.QMessageBox.question",
                        lambda *args, **kwargs: QMessageBox.Yes)
    audio = _audio(tmp_path)
    w = _window(app, tmp_path)
    try:
        w.lines.setCurrentRow(0)
        w.words.selectRow(1)

        # 1. nudge a word
        w.nudge(50)
        assert w.doc.lines[0].segments[1].start_ms == 1550
        w.undo_stack.undo()
        assert w.doc.lines[0].segments[1].start_ms == 1500
        w.undo_stack.redo()
        assert w.doc.lines[0].segments[1].start_ms == 1550

        # 2. add a word
        w.lines.setCurrentRow(0)
        w.words.selectRow(1)
        w.add_word("já")
        assert w.doc.lines[0].text == "eu vou já"
        w.undo_stack.undo()
        assert w.doc.lines[0].text == "eu vou"
        w.undo_stack.redo()
        assert w.doc.lines[0].text == "eu vou já"

        # 3. insert a line
        w.lines.setCurrentRow(0)
        w.add_line("nova linha")
        assert [line.text for line in w.doc.lines] == ["eu vou já", "nova linha", "de novo"]
        w.undo_stack.undo()
        assert [line.text for line in w.doc.lines] == ["eu vou já", "de novo"]
        w.undo_stack.redo()
        assert [line.text for line in w.doc.lines][1] == "nova linha"

        # 4. merge a line
        w.lines.setCurrentRow(1)
        w.merge_current_line()
        assert [line.text for line in w.doc.lines] == ["eu vou já nova linha", "de novo"]
        w.undo_stack.undo()
        assert [line.text for line in w.doc.lines] == ["eu vou já", "nova linha", "de novo"]

        # 5. delete a word
        w.lines.setCurrentRow(0)
        w.words.selectRow(0)
        w.delete_current_word()
        assert w.doc.lines[0].text == "vou já"
        w.undo_stack.undo()
        assert w.doc.lines[0].text == "eu vou já"

        # 6. delete a line (asks first)
        w.lines.setCurrentRow(0)
        w.delete_current_line()
        assert [line.text for line in w.doc.lines] == ["nova linha", "de novo"]
        w.undo_stack.undo()
        assert [line.text for line in w.doc.lines] == ["eu vou já", "nova linha", "de novo"]
    finally:
        w.dirty = False
        w.close()


def test_undo_redo_shortcuts_and_actions(app, tmp_path):
    _audio(tmp_path)
    w = _window(app, tmp_path)
    try:
        assert w.act_undo.shortcut() == QKeySequence(QKeySequence.Undo)
        redo = [sequence for sequence in w.act_redo.shortcuts()]
        assert QKeySequence(QKeySequence.Redo) in redo and QKeySequence("Ctrl+Shift+Z") in redo
        assert w.act_delete_line.shortcut() == QKeySequence(QKeySequence.Delete)
        assert not w.act_undo.isEnabled() and not w.act_redo.isEnabled()

        w.lines.setCurrentRow(0)
        w.words.selectRow(0)
        w.nudge(10)
        assert w.act_undo.isEnabled() and not w.act_redo.isEnabled()
        w.undo_stack.undo()
        assert not w.act_undo.isEnabled() and w.act_redo.isEnabled()
    finally:
        w.dirty = False
        w.close()


def test_delete_line_asks_before_removing_it(app, tmp_path, monkeypatch):
    answers = [QMessageBox.No, QMessageBox.Yes]
    seen = []

    def question(*args, **kwargs):
        seen.append(args[2] if len(args) > 2 else "")
        return answers.pop(0)

    monkeypatch.setattr("lyricloom.app.main.QMessageBox.question", question)
    _audio(tmp_path)
    w = _window(app, tmp_path)
    try:
        w.lines.setCurrentRow(0)
        assert w.lines.count() == 2
        w.delete_current_line()
        assert w.lines.count() == 2 and seen
        w.delete_current_line()
        assert w.lines.count() == 1
        assert "Delete this line" in seen[-1]
    finally:
        w.dirty = False
        w.close()


def test_accept_line_clears_review_and_marks_the_row_done(app, tmp_path):
    audio = _audio(tmp_path)
    w = _window(app, tmp_path)
    try:
        assert w.rows[0].status == "review"
        w.lines.setCurrentRow(0)
        w.accept_line()

        assert w.doc.meta["#review"] == ""
        assert not w.dirty
        saved = parse_lrc(audio.with_suffix(".lrc").read_text(encoding="utf-8"))
        assert saved.meta["#review"] == ""
        assert w.rows[0].status == "done"
        assert w.proxy.index(0, 2).data() == "done"

        w.undo_stack.undo()
        assert w.doc.meta["#review"] == "0"
        assert w.dirty
    finally:
        w.dirty = False
        w.close()


def test_accept_all_clears_a_transcription_only_review(app, tmp_path):
    lrc = ("[re:LyricLoom 2.1.0]\n[#engine:7]\n[#source:transcription conf:0.80]\n"
           "[00:01.00]<00:01.00>one<00:02.00>\n")
    audio = _audio(tmp_path, lrc)
    w = _window(app, tmp_path)
    try:
        assert w.rows[0].status == "review"
        w.accept_all()
        saved = parse_lrc(audio.with_suffix(".lrc").read_text(encoding="utf-8"))
        assert "#review" in saved.meta and saved.meta["#review"] == ""
        assert w.rows[0].status == "done"
    finally:
        w.dirty = False
        w.close()
