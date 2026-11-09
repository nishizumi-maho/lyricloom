"""GitHub Releases update check and installer download.

The automatic check is opt-in: when no ``check_updates`` choice has been saved, no request is
made. Only public release metadata and the installer (with its published SHA-256) are fetched
from this project's own GitHub release. There is no signer pin, because the installer is not
code-signed; instead the updater fails closed when a checksum is missing or wrong, follows
redirects only to GitHub's release asset hosts, and refuses to run a file from anywhere else.
Nothing about the user or the library is uploaded.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
import threading
import webbrowser
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urljoin, urlparse

import httpx

from . import VERSION, config

REPO = "nishizumi-maho/lyricloom"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
STABLE_ASSET = "LyricLoom-Setup.exe"
USER_AGENT = f"LyricLoom/{VERSION} (+https://github.com/{REPO})"

UPDATE_DIR = Path(tempfile.gettempdir()) / "LyricLoom-update"
_API_HOST = "api.github.com"
_RELEASE_PREFIX = f"/{REPO}/releases/"
_ASSET_HOSTS = frozenset({
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "github-releases.githubusercontent.com",
})
_SAFE_ASSET_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERIFIED: dict[Path, str] = {}   # downloads verified in this process, by absolute path

Progress = Callable[[int, int], None]


@dataclass
class UpdateInfo:
    version: str
    tag: str
    page_url: str
    notes: str
    asset_name: str
    asset_url: str
    asset_size: int
    asset_sha256: str
    checksum_url: str = ""


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", value.lstrip("vV").split("-", 1)[0])
    return tuple(int(p) for p in parts[:4]) or (0,)


def is_newer(candidate: str) -> bool:
    return _version_tuple(candidate) > _version_tuple(VERSION)


def _is_https(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.hostname)


def _is_api_url(url: str) -> bool:
    parsed = urlparse(url)
    return (_is_https(url) and parsed.hostname == _API_HOST
            and parsed.path.startswith(f"/repos/{REPO}/releases/"))


def _is_release_url(url: str) -> bool:
    parsed = urlparse(url)
    return _is_https(url) and parsed.hostname == "github.com" and parsed.path.startswith(_RELEASE_PREFIX)


def _is_asset_url(url: str) -> bool:
    return _is_release_url(url) and urlparse(url).path.startswith(_RELEASE_PREFIX + "download/")


def _is_asset_redirect(url: str) -> bool:
    parsed = urlparse(url)
    return _is_https(url) and parsed.hostname in _ASSET_HOSTS


def _client(timeout: float) -> httpx.Client:
    return httpx.Client(follow_redirects=False, timeout=timeout)


@contextmanager
def _stream(url: str, *, allowed: Callable[[str], bool], headers: dict[str, str],
            timeout: float = 60) -> Iterator[httpx.Response]:
    """GET `url`, following redirects only to allowed hosts, and yield the final response."""
    current = url
    with _client(timeout) as client:
        for _ in range(10):
            if not allowed(current):
                host = urlparse(current).hostname or "an unknown host"
                raise RuntimeError(f"refusing to fetch the update from {host}: not a GitHub release asset")
            with client.stream("GET", current, headers=headers) as response:
                if response.is_redirect:
                    current = urljoin(current, response.headers.get("location", ""))
                    continue
                response.raise_for_status()
                yield response
                return
    raise RuntimeError("too many redirects while fetching the update")


def _get_text(url: str, *, allowed: Callable[[str], bool], timeout: float = 20) -> str:
    with _stream(url, allowed=allowed, headers={"User-Agent": USER_AGENT}, timeout=timeout) as response:
        return response.text


def _get_json(url: str) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    with _stream(url, allowed=_is_api_url, headers=headers, timeout=20) as response:
        data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("GitHub returned an unexpected release description")
    return data


def _safe_asset_name(name: object) -> str:
    value = str(name)
    if not value or value in (".", "..") or value != Path(value).name or not _SAFE_ASSET_NAME.fullmatch(value):
        raise RuntimeError("the release published an unsafe installer file name; refusing to download it")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_choice() -> bool | None:
    """The saved update-check choice: True/False once the user chose, None when not chosen yet."""
    data = config.all_settings()
    if "check_updates" not in data:
        return None
    value = data["check_updates"]
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return None


def should_check_on_startup() -> bool:
    """The startup path may contact GitHub only after the user explicitly opted in."""
    return check_choice() is True and os.environ.get("QT_QPA_PLATFORM") != "offscreen"


def check() -> UpdateInfo | None:
    """Return the latest release when it is newer than this build, else None. Network errors are
    reported to the caller as exceptions; the GUI turns them into a non-blocking status message."""
    release = _get_json(API_LATEST)
    tag = str(release.get("tag_name", "")).strip()
    version = tag.lstrip("vV")
    if not version or not is_newer(version):
        return None
    assets = {a.get("name", ""): a for a in release.get("assets", []) if isinstance(a, dict)}
    asset = assets.get(STABLE_ASSET) or next(
        (a for name, a in assets.items()
         if name.startswith("LyricLoom-Setup-") and name.lower().endswith(".exe")), None)
    if asset is None:
        return None
    asset_name = _safe_asset_name(asset.get("name", ""))
    asset_url = str(asset.get("browser_download_url") or "")
    if not _is_asset_url(asset_url):
        raise RuntimeError("the GitHub release points at a download outside its own release assets; "
                           "refusing to offer the update")
    checksum = assets.get(asset_name + ".sha256") or assets.get("SHA256SUMS")
    checksum_url = str(checksum.get("browser_download_url") or "") if checksum else ""
    if checksum_url and not _is_asset_url(checksum_url):
        raise RuntimeError("the GitHub release points at a checksum outside its own release assets; "
                           "refusing to offer the update")
    page = str(release.get("html_url") or "")
    digest = str(asset.get("digest") or "")
    sha = digest.split(":", 1)[1] if digest.lower().startswith("sha256:") else ""
    return UpdateInfo(
        version=version,
        tag=tag,
        page_url=page if _is_release_url(page) else RELEASES_PAGE,
        notes=str(release.get("body") or ""),
        asset_name=asset_name,
        asset_url=asset_url,
        asset_size=int(asset.get("size") or 0),
        asset_sha256=sha,
        checksum_url=checksum_url,
    )


def _checksum_from_text(text: str, filename: str) -> str:
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == filename:
            return parts[0].lower()
    parts = text.split()
    return parts[0].lower() if parts else ""


def download(info: UpdateInfo, progress: Progress | None = None,
             cancel: threading.Event | None = None) -> Path:
    """Download the installer and verify its SHA-256 before returning the path.

    Fails closed: a missing or invalid checksum, a non-GitHub URL, an incomplete transfer or a
    digest mismatch all discard the file and raise a clear error. `cancel` stops between chunks
    and discards the partial file."""
    name = _safe_asset_name(info.asset_name)
    if not _is_asset_url(info.asset_url):
        raise RuntimeError("refusing to download the update: the URL is not this project's GitHub release")
    expected = info.asset_sha256.strip().lower()
    if expected and not _SHA256.fullmatch(expected):
        raise RuntimeError("the release published an invalid SHA-256 checksum; refusing to run the installer")
    if not expected:
        if not info.checksum_url:
            raise RuntimeError(
                "this release does not publish a SHA-256 checksum for the installer; refusing to "
                "download or run it. Download the installer from the release page and verify it yourself.")
        if not _is_asset_url(info.checksum_url):
            raise RuntimeError("refusing to fetch the update checksum from outside this project's GitHub release")
        expected = _checksum_from_text(_get_text(info.checksum_url, allowed=_is_asset_redirect), name).lower()
        if not _SHA256.fullmatch(expected):
            raise RuntimeError(f"the release checksum file does not contain a valid SHA-256 for {name}; "
                               "refusing to run the installer")

    if cancel is not None and cancel.is_set():
        raise RuntimeError("the update download was cancelled")
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPDATE_DIR / name
    temporary = destination.with_name(destination.name + ".part")
    temporary.unlink(missing_ok=True)
    done = 0
    try:
        with _stream(info.asset_url, allowed=_is_asset_redirect,
                     headers={"User-Agent": USER_AGENT}) as response:
            total = int(response.headers.get("content-length", 0)) or info.asset_size
            with temporary.open("wb") as file:
                for chunk in response.iter_bytes(1 << 20):
                    if cancel is not None and cancel.is_set():
                        raise RuntimeError("the update download was cancelled")
                    file.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        if info.asset_size and done != info.asset_size:
            raise RuntimeError(f"the update download is incomplete ({done} of {info.asset_size} bytes); "
                               "it was discarded")
        if _sha256_file(temporary) != expected:
            raise RuntimeError("the update checksum does not match; the download was discarded")
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    _VERIFIED[destination.resolve()] = expected
    return destination


def launch_installer(path: Path) -> None:
    """Start the verified installer. On non-Windows, open the release page instead."""
    path = Path(path)
    expected = _VERIFIED.get(path.resolve())
    if expected is None or not path.is_file() or _sha256_file(path) != expected:
        raise RuntimeError("refusing to run an installer that LyricLoom did not download and verify "
                           "from its own GitHub release")
    if sys.platform == "win32" and path.suffix.lower() == ".exe":
        subprocess.Popen([str(path), "/CLOSEAPPLICATIONS", "/NORESTART"], close_fds=True)
        return
    webbrowser.open(RELEASES_PAGE)
