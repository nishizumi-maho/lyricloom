import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lyricloom import downloads
from lyricloom.downloads import ChecksumMismatch, DownloadCancelled, DownloadError
from lyricloom.models import ModelFile

PAYLOAD = bytes(range(256)) * 40


class _Handler(BaseHTTPRequestHandler):
    payload = PAYLOAD
    ranges: list[str | None] = []
    support_range = True

    def do_GET(self):
        range_header = self.headers.get("Range")
        type(self).ranges.append(range_header)
        start = 0
        if range_header and self.support_range:
            start = int(range_header.split("=")[1].split("-")[0])
            body = self.payload[start:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(self.payload) - 1}/{len(self.payload)}")
        else:
            body = self.payload
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    handler = type("Handler", (_Handler,), {"ranges": []})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd, handler
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _spec(url: str, payload: bytes = PAYLOAD) -> ModelFile:
    return ModelFile("model.bin", url, len(payload), hashlib.sha256(payload).hexdigest())


def test_download_verified_writes_the_file(server, tmp_path):
    httpd, _handler = server
    dest = tmp_path / "model.bin"
    out = downloads.download_verified(_spec(f"http://127.0.0.1:{httpd.server_address[1]}/m"), dest)
    assert out.read_bytes() == PAYLOAD
    assert not dest.with_name(dest.name + ".part").exists()


def test_resume_after_a_partial_download_uses_range(server, tmp_path):
    httpd, handler = server
    dest = tmp_path / "model.bin"
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(PAYLOAD[:1000])
    downloads.download_verified(_spec(f"http://127.0.0.1:{httpd.server_address[1]}/m"), dest)
    assert handler.ranges == ["bytes=1000-"]
    assert dest.read_bytes() == PAYLOAD


def test_checksum_mismatch_deletes_the_part_file(server, tmp_path):
    httpd, _handler = server
    dest = tmp_path / "model.bin"
    spec = ModelFile("model.bin", f"http://127.0.0.1:{httpd.server_address[1]}/m",
                     len(PAYLOAD), "0" * 64)
    with pytest.raises(ChecksumMismatch):
        downloads.download_verified(spec, dest)
    assert not dest.exists()
    assert not dest.with_name(dest.name + ".part").exists()


def test_plain_http_outside_the_loopback_is_refused(tmp_path):
    spec = ModelFile("model.bin", "http://example.com/model.bin", 1, "0" * 64)
    with pytest.raises(DownloadError, match="non-HTTPS"):
        downloads.download_verified(spec, tmp_path / "model.bin")


def test_cancel_keeps_the_partial_file(server, tmp_path):
    httpd, _handler = server
    dest = tmp_path / "model.bin"
    event = threading.Event()
    event.set()
    with pytest.raises(DownloadCancelled):
        downloads.download_verified(_spec(f"http://127.0.0.1:{httpd.server_address[1]}/m"),
                                    dest, cancel=event)
    assert not dest.exists()
