"""Single-instance IPC: a second LyricLoom hands its command line to the running one.

A per-user named local socket carries small newline-terminated JSON objects. The server is limited
to the current user (``UserAccessOption``), accepts at most 64 KiB per object and rejects anything
that is not a well-formed command. Nothing here imports the window, so tests can exercise the
channel alone.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal, Slot
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .. import config
from .paths import expand_audio_paths, validate_audio_file

MAX_MESSAGE_BYTES = 64 * 1024
DEFAULT_TIMEOUT_MS = 2000
STALE_PROBE_MS = 5000


_INSTANCE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


def server_name() -> str:
    """Stable per-user name; the data directory tells apart portable profiles. A separate instance
    (a test run, a second portable profile) can set ``LYRICLOOM_INSTANCE_NAME`` so it never talks
    to, or answers for, the user's running LyricLoom."""
    override = os.environ.get("LYRICLOOM_INSTANCE_NAME", "").strip()
    if override and _INSTANCE_NAME.fullmatch(override):
        return override
    digest = hashlib.sha1(str(config.APP_DATA).lower().encode("utf-8")).hexdigest()[:12]
    return f"LyricLoom-{digest}"


def _validate(message) -> tuple[dict | None, str | None]:
    """Checks one decoded message. Returns (normalised message, error text)."""
    if not isinstance(message, dict):
        return None, "message must be a JSON object"
    command = message.get("cmd")
    if command == "activate":
        return {"cmd": "activate", "source": "ipc"}, None
    if command == "open":
        raw = message.get("path")
        if not isinstance(raw, str) or not raw.strip():
            return None, "open needs one file path"
        path, error = validate_audio_file(raw)
        if error is not None or path is None:
            # A bad path is not a malformed message: the running window reports it.
            return {"cmd": "report", "rejected": [error or f"{raw}: invalid path"],
                    "source": "ipc"}, None
        return {"cmd": "open", "path": path, "source": "ipc"}, None
    if command == "process":
        raw = message.get("paths")
        if not isinstance(raw, list) or not raw or not all(isinstance(p, str) and p.strip() for p in raw):
            return None, "process needs a non-empty list of file paths"
        redo = message.get("redo", False)
        if not isinstance(redo, bool):
            return None, "redo must be true or false"
        accepted, rejected = expand_audio_paths(raw)
        return {"cmd": "process", "paths": accepted, "rejected": rejected, "redo": redo,
                "source": "ipc"}, None
    return None, "unknown command"


class _Client(QObject):
    """Reads newline-terminated JSON objects from one connection."""

    def __init__(self, socket: QLocalSocket, server: "Server"):
        super().__init__(server)
        self._socket = socket
        self._server = server
        self._buffer = b""
        self._finished = False
        self._rejected = False

    def start(self) -> None:
        self._socket.readyRead.connect(self._read)
        self._socket.disconnected.connect(self._done)

    @Slot()
    def _read(self) -> None:
        if self._rejected:
            return
        self._buffer += bytes(self._socket.readAll())
        while not self._rejected and b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            if len(line) > MAX_MESSAGE_BYTES:
                self._reject("message is larger than 64 KiB")
                return
            self._handle(line)
        if not self._rejected and len(self._buffer) > MAX_MESSAGE_BYTES:
            self._reject("message is larger than 64 KiB")

    @Slot()
    def _done(self) -> None:
        if self._buffer and b"\n" not in self._buffer:
            self._reject("message is not newline-terminated")
        else:
            self._finish()

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        try:
            self._socket.readyRead.disconnect(self._read)
            self._socket.disconnected.disconnect(self._done)
        except (RuntimeError, TypeError):
            pass
        try:
            self._socket.deleteLater()
        except RuntimeError:
            pass
        try:
            self._server._clients.remove(self)
        except ValueError:
            pass
        try:
            self.deleteLater()
        except RuntimeError:
            pass

    def stop(self) -> None:
        """Detaches from a socket while the server is shutting down (tests recreate servers)."""
        if self._finished:
            return
        self._finished = True
        try:
            self._socket.readyRead.disconnect(self._read)
            self._socket.disconnected.disconnect(self._done)
        except (RuntimeError, TypeError):
            pass
        try:
            self._socket.abort()
            self._socket.deleteLater()
        except RuntimeError:
            pass
        try:
            self.deleteLater()
        except RuntimeError:
            pass

    def _handle(self, raw: bytes) -> None:
        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._reject("message is not valid JSON")
            return
        checked, error = _validate(message)
        if error is not None or checked is None:
            self._reject(error or "invalid message")
            return
        response = {"ok": True}
        if checked["cmd"] == "process":
            response.update(accepted=len(checked["paths"]), rejected=checked["rejected"])
        self._reply(response)
        self._server.deliver(checked)

    def _reply(self, response: dict) -> None:
        try:
            self._socket.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")
            self._socket.flush()
        except RuntimeError:
            pass

    def _reject(self, reason: str) -> None:
        if self._rejected:
            return
        self._rejected = True
        self._reply({"ok": False, "error": reason})
        self._buffer = b""
        QTimer.singleShot(100, self._close_after_reject)

    def _close_after_reject(self) -> None:
        if self._finished:
            return
        try:
            self._socket.disconnectFromServer()
        except RuntimeError:
            pass
        self._finish()


def _name_answers(name: str, timeout_ms: int) -> bool:
    """True when something still listens on `name` (it may be too busy to reply to a command)."""
    socket = QLocalSocket()
    socket.connectToServer(name)
    try:
        return socket.waitForConnected(timeout_ms)
    finally:
        try:
            socket.abort()
        except RuntimeError:
            pass
        socket.deleteLater()


class Server(QObject):
    """Owns the per-user QLocalServer and emits validated messages."""

    received = Signal(object)

    def __init__(self, name: str | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self.name = name or server_name()
        self._server: QLocalServer | None = None
        self._clients: list[_Client] = []
        self._ready = True
        self._pending: list[dict] = []

    @property
    def is_listening(self) -> bool:
        return self._server is not None and self._server.isListening()

    def listen(self) -> bool:
        if self._server is not None and self._server.isListening():
            # MainWindow is handed an already-listening server; a second listen() would fail and
            # made every startup close and re-acquire the single-instance name (FRB-03).
            return True
        if self._server is None:
            self._server = QLocalServer(self)
            self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
            self._server.newConnection.connect(self._accept)
        return self._server.listen(self.name)

    def hold(self) -> None:
        """Buffers messages until the window is connected (startup gap)."""
        self._ready = False

    def set_ready(self) -> None:
        self._ready = True
        pending, self._pending = self._pending, []
        for message in pending:
            self.received.emit(message)

    def deliver(self, message: dict) -> None:
        if self._ready:
            self.received.emit(message)
        else:
            self._pending.append(message)

    def remove_stale(self, probe_ms: int = STALE_PROBE_MS) -> bool:
        """Removes a name a crashed process left behind (only call after connect failed).

        A name that still accepts a connection belongs to a live process, even when that process
        is too busy to answer a message. Unlinking it on Linux would let a second window start and
        write the same settings, so probe once more before removing it. Returns True when the name
        was removed.
        """
        if self._server is not None:
            self._server.close()
        if _name_answers(self.name, probe_ms):
            return False
        QLocalServer.removeServer(self.name)
        return True

    def close(self) -> None:
        for client in list(self._clients):
            client.stop()
        self._clients.clear()
        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None
        QLocalServer.removeServer(self.name)

    @Slot()
    def _accept(self) -> None:
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                return
            client = _Client(socket, self)
            self._clients.append(client)
            client.start()


def _json_ready(value):
    """Converts ``Path`` values (and containers holding them) before ``json.dumps``.

    A second instance forwards the startup command through ``send``; those dicts carried
    ``WindowsPath`` objects and JSON serialisation raised ``TypeError`` while the first instance
    was busy (FRB-02).  Normalising here protects every caller, including future commands.
    """
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_ready(item) for item in value]
    return value


def send(message, *, name: str | None = None, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict | None:
    """Sends one command to the running instance. Returns its JSON reply or None if nobody answers.

    A list of paths is accepted as a shorthand for a ``process`` message. The wait pumps the event
    loop because tests run both ends in one thread; in a real second process there is no other event
    loop yet, so this is only extra safety.
    """
    if not isinstance(message, dict):
        paths = message if isinstance(message, (list, tuple, set)) else [message]
        message = {"cmd": "process", "paths": [str(path) for path in paths]}
    payload = json.dumps(_json_ready(message), ensure_ascii=False).encode("utf-8") + b"\n"
    if len(payload) > MAX_MESSAGE_BYTES:
        return None
    socket = QLocalSocket()
    socket.connectToServer(name or server_name())
    if not socket.waitForConnected(timeout_ms):
        socket.deleteLater()
        return None
    written = socket.write(payload)
    if written != len(payload):
        socket.deleteLater()
        return None
    socket.waitForBytesWritten(50)   # advisory only: local sockets can report False and still send
    deadline = time.monotonic() + timeout_ms / 1000
    buffer = b""
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if socket.bytesAvailable():
            buffer += bytes(socket.readAll())
            if b"\n" in buffer:
                break
        time.sleep(0.01)
    try:
        socket.disconnectFromServer()
    except RuntimeError:
        pass
    socket.deleteLater()
    if b"\n" not in buffer:
        return None
    try:
        reply = json.loads(buffer.split(b"\n", 1)[0].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return reply if isinstance(reply, dict) else None
