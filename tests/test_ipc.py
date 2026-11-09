import json
import os
import time
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtNetwork import QLocalSocket  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricloom.app import ipc  # noqa: E402
from lyricloom.app.main import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _audio(root: Path, name="01 - Song.flac") -> Path:
    audio = root / "Artist" / "Album" / name
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"x")
    return audio


def _name() -> str:
    return f"LyricLoom-test-{uuid.uuid4().hex[:12]}"


def _wait(app, cond, timeout=8):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert cond()


def _raw_exchange(app, name: str, payload: bytes, timeout=5) -> dict | None:
    """One QLocalSocket client end, with the same event loop as the server."""
    socket = QLocalSocket()
    socket.connectToServer(name)
    assert socket.waitForConnected(3000), socket.errorString()
    socket.write(payload)
    buffer = b""
    end = time.time() + timeout
    while b"\n" not in buffer and time.time() < end:
        app.processEvents()
        if socket.bytesAvailable():
            buffer += bytes(socket.readAll())
        time.sleep(0.01)
    socket.disconnectFromServer()
    socket.deleteLater()
    if b"\n" not in buffer:
        return None
    return json.loads(buffer.split(b"\n", 1)[0].decode("utf-8"))


def test_server_name_is_stable_and_per_profile():
    assert ipc.server_name() == ipc.server_name()
    assert ipc.server_name().startswith("LyricLoom-")
    assert len(ipc.server_name()) > len("LyricLoom-")


def test_instance_name_override_isolates_a_profile_and_rejects_bad_names(monkeypatch):
    monkeypatch.setenv("LYRICLOOM_INSTANCE_NAME", "LyricLoom-portable-1")
    assert ipc.server_name() == "LyricLoom-portable-1"
    for bad in ("", "  ", "a/b", "..\\pipe", "x" * 81):
        monkeypatch.setenv("LYRICLOOM_INSTANCE_NAME", bad)
        assert ipc.server_name().startswith("LyricLoom-") and "/" not in ipc.server_name()
        assert ipc.server_name() != bad
    monkeypatch.delenv("LYRICLOOM_INSTANCE_NAME")
    assert ipc.server_name().startswith("LyricLoom-")


def test_send_returns_none_without_a_server():
    assert ipc.send({"cmd": "activate"}, name=_name(), timeout_ms=200) is None


def test_server_queues_only_validated_audio_and_reports_the_rest(app, tmp_path):
    name = _name()
    server = ipc.Server(name=name)
    assert server.listen()
    received = []
    server.received.connect(received.append)
    try:
        audio = _audio(tmp_path)
        note = tmp_path / "notes.txt"
        note.write_text("not audio", encoding="utf-8")
        missing = tmp_path / "gone.flac"
        reply = ipc.send({"cmd": "process", "paths": [str(audio), str(note), str(missing)],
                          "redo": True}, name=name)
        assert reply is not None and reply["ok"]
        assert reply["accepted"] == 1 and len(reply["rejected"]) == 2
        assert received == [{"cmd": "process", "paths": [audio.resolve()],
                             "rejected": received[0]["rejected"], "redo": True, "source": "ipc"}]
        assert received[0]["redo"] is True
    finally:
        server.received.disconnect()
        server.close()
        app.processEvents()


def test_open_and_activate_commands(app, tmp_path):
    name = _name()
    server = ipc.Server(name=name)
    assert server.listen()
    received = []
    server.received.connect(received.append)
    try:
        audio = _audio(tmp_path)
        invalid = ipc.send({"cmd": "open", "path": str(tmp_path)}, name=name)
        assert invalid is not None and invalid["ok"]
        assert ipc.send({"cmd": "open", "path": str(audio)}, name=name)["ok"]
        assert ipc.send({"cmd": "activate"}, name=name)["ok"]
        assert received[0]["cmd"] == "report" and "not a file" in received[0]["rejected"][0]
        assert received[1]["cmd"] == "open" and received[1]["path"] == audio.resolve()
        assert received[2] == {"cmd": "activate", "source": "ipc"}
    finally:
        server.received.disconnect()
        server.close()
        app.processEvents()


def test_a_message_that_arrives_before_the_window_is_ready_is_not_lost(app, tmp_path):
    name = _name()
    server = ipc.Server(name=name)
    assert server.listen()
    server.hold()
    received = []
    try:
        audio = _audio(tmp_path)
        reply = ipc.send({"cmd": "process", "paths": [str(audio)]}, name=name)
        assert reply is not None and reply["ok"] and received == []
        server.received.connect(received.append)
        server.set_ready()
        assert received and received[0]["paths"] == [audio.resolve()]
    finally:
        server.received.disconnect()
        server.close()
        app.processEvents()


def test_malformed_and_oversized_messages_are_rejected(app):
    name = _name()
    server = ipc.Server(name=name)
    assert server.listen()
    received = []
    server.received.connect(received.append)
    try:
        malformed = _raw_exchange(app, name, b"{not json\n")
        assert malformed and not malformed["ok"]
        oversized = _raw_exchange(app, name, b"{" + b" " * (ipc.MAX_MESSAGE_BYTES + 1) + b"}\n")
        assert oversized and not oversized["ok"] and "64 KiB" in oversized["error"]
        unknown = _raw_exchange(app, name, b'{"cmd":"nope"}\n')
        assert unknown and not unknown["ok"]
        bad_type = _raw_exchange(app, name, b'{"cmd":"process","paths":[1,2]}\n')
        assert bad_type and not bad_type["ok"]
        assert received == []
    finally:
        server.received.disconnect()
        server.close()
        app.processEvents()


def test_a_second_instance_message_reaches_the_window_and_queues_valid_files(app, tmp_path, monkeypatch):
    w = MainWindow(tmp_path)
    try:
        assert w._ipc_available and w._ipc_server.is_listening
        audio = _audio(tmp_path)
        note = tmp_path / "notes.txt"
        note.write_text("not audio", encoding="utf-8")
        queued = []

        def fake_process(paths, redo=False):
            queued.append((list(paths), redo))
            return True

        monkeypatch.setattr(w, "process", fake_process)
        reply = ipc.send({"cmd": "process", "paths": [str(audio), str(note)]}, name=w._ipc_server.name)
        assert reply is not None and reply["ok"] and reply["accepted"] == 1
        _wait(app, lambda: queued)
        assert queued[0][0] == [audio.resolve()] and queued[0][1] is False
    finally:
        w.dirty = False
        w.close()
