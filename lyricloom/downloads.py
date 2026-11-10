"""Verified model downloads: HTTPS, resumable, retried and checked before the atomic move.

Every catalog file goes through :func:`download_verified`.  A ``.part`` file keeps a partial
download so a dropped connection resumes with an HTTP ``Range`` request instead of starting over.
The finished file is moved into place only after its exact size and SHA-256 match the pinned
catalog values.  Tests use a loopback ``http.server``; real downloads must be HTTPS.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

Progress = Callable[[int, int], None]  # bytes done, bytes total (total may be 0)

CHUNK = 1 << 20
RETRIES = 4
BACKOFF_S = (1, 2, 4)


class DownloadError(RuntimeError):
    """A model file could not be downloaded or did not match its pinned metadata."""


class DownloadCancelled(DownloadError):
    """The caller's cancel event was set.  The ``.part`` file is kept for a later resume."""


class ChecksumMismatch(DownloadError):
    """The bytes did not match the pinned SHA-256.  The ``.part`` file has been deleted."""


def _is_loopback(host: str | None) -> bool:
    return host in ("127.0.0.1", "localhost", "::1", "::ffff:127.0.0.1")


def _check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return
    # The test suite runs a local http.server; no real download may ever use plain HTTP.
    if parsed.scheme == "http" and _is_loopback(parsed.hostname):
        return
    raise DownloadError(f"refusing a non-HTTPS model download: {url}")


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def download_verified(spec_file, dest: Path, progress: Progress | None = None,
                      cancel=None) -> Path:
    """Downloads ``spec_file`` to ``dest`` and returns it.

    ``spec_file`` is a :class:`lyricloom.models.ModelFile` (``url``, ``size``, ``sha256``).
    ``progress`` receives ``(bytes done, bytes total)``.  ``cancel`` is a ``threading.Event``;
    when set, the partial file is kept and :class:`DownloadCancelled` is raised.

    The server must support ``Range`` for a resumed transfer; a server that ignores it simply
    restarts the file from byte zero.  Transient network failures are retried with a short
    exponential backoff.  A size or SHA-256 mismatch deletes the ``.part`` file and raises.
    """
    url = str(spec_file.url)
    _check_url(url)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    expected_size = int(getattr(spec_file, "size", 0) or 0)
    expected_sha = str(getattr(spec_file, "sha256", "") or "").lower()
    last_error: Exception | None = None

    for attempt in range(RETRIES):
        if cancel is not None and cancel.is_set():
            raise DownloadCancelled(f"download cancelled: {dest.name}")
        done = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={done}-"} if done else {}
        try:
            with httpx.stream("GET", url, headers=headers, follow_redirects=True,
                              timeout=httpx.Timeout(60.0, read=120.0)) as response:
                _check_url(str(response.url))
                if response.status_code == 416 and done:
                    # The server says our range is already past the end.  If the part is the
                    # whole expected file, verify it; otherwise it is unusable.
                    if expected_size and done == expected_size:
                        return _finish(part, dest, expected_size, expected_sha)
                    part.unlink(missing_ok=True)
                    raise DownloadError(f"the server rejected a resume at byte {done} for {dest.name}")
                response.raise_for_status()
                append = response.status_code == 206 and done > 0
                mode = "ab" if append else "wb"
                if not append:
                    done = 0
                total = expected_size or (done + int(response.headers.get("content-length", 0) or 0))
                with part.open(mode) as f:
                    for chunk in response.iter_bytes(CHUNK):
                        if cancel is not None and cancel.is_set():
                            raise DownloadCancelled(f"download cancelled: {dest.name}")
                        f.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
            if expected_size and part.stat().st_size != expected_size:
                raise DownloadError(
                    f"incomplete download for {dest.name}: got {part.stat().st_size} of "
                    f"{expected_size} bytes")
            return _finish(part, dest, expected_size, expected_sha)
        except (DownloadCancelled, ChecksumMismatch):
            raise
        except (httpx.HTTPError, OSError, DownloadError) as exc:
            last_error = exc
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (401, 403, 404):
                break   # retrying a permanent HTTP error only wastes time
            if attempt + 1 < RETRIES:
                time.sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
    raise DownloadError(f"could not download {dest.name} from {url}: {last_error}")


def _finish(part: Path, dest: Path, expected_size: int, expected_sha: str) -> Path:
    if not part.exists():
        raise DownloadError(f"the download produced no file for {dest.name}")
    if expected_size and part.stat().st_size != expected_size:
        got = part.stat().st_size
        part.unlink(missing_ok=True)
        raise DownloadError(
            f"size mismatch for {dest.name}: got {got} bytes, expected {expected_size}")
    if expected_sha and _sha256(part).lower() != expected_sha:
        part.unlink(missing_ok=True)
        raise ChecksumMismatch(f"checksum mismatch for {dest.name}: the partial file was deleted")
    os.replace(part, dest)
    return dest
