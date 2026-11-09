"""GitHub Releases update check and installer download.

Only release metadata and the installer are fetched from github.com. The check is opt-out in
Settings; it never uploads anything about the user or the library.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import tempfile
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

from . import VERSION

REPO = "nishizumi-maho/lyricloom"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
STABLE_ASSET = "LyricLoom-Setup.exe"
USER_AGENT = f"LyricLoom/{VERSION} (+https://github.com/{REPO})"

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


def _request(url: str, **kwargs) -> httpx.Response:
    return httpx.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
                     follow_redirects=True, timeout=20, **kwargs)


def check() -> UpdateInfo | None:
    """Return the latest release when it is newer than this build, else None. Network errors are
    reported to the caller as exceptions; the GUI turns them into a non-blocking status message."""
    release = _request(API_LATEST).raise_for_status().json()
    tag = str(release.get("tag_name", "")).strip()
    version = tag.lstrip("vV")
    if not version or not is_newer(version):
        return None
    assets = {a.get("name", ""): a for a in release.get("assets", [])}
    asset = assets.get(STABLE_ASSET) or next(
        (a for name, a in assets.items()
         if name.startswith("LyricLoom-Setup-") and name.lower().endswith(".exe")), None)
    if asset is None:
        return None
    checksum = assets.get(asset["name"] + ".sha256") or assets.get("SHA256SUMS")
    digest = str(asset.get("digest") or "")
    sha = digest.split(":", 1)[1] if digest.lower().startswith("sha256:") else ""
    return UpdateInfo(
        version=version,
        tag=tag,
        page_url=str(release.get("html_url") or RELEASES_PAGE),
        notes=str(release.get("body") or ""),
        asset_name=str(asset["name"]),
        asset_url=str(asset["browser_download_url"]),
        asset_size=int(asset.get("size") or 0),
        asset_sha256=sha,
        checksum_url=str(checksum["browser_download_url"]) if checksum else "",
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
    """Download the installer into the temp folder and verify its checksum when one is published.
    `cancel` stops between chunks (the caller deletes the partial file)."""
    dest = Path(tempfile.gettempdir()) / info.asset_name
    tmp = dest.with_name(dest.name + ".part")
    expected = info.asset_sha256.lower()
    if not expected and info.checksum_url:
        expected = _checksum_from_text(_request(info.checksum_url).raise_for_status().text, info.asset_name)
    if cancel is not None and cancel.is_set():
        raise RuntimeError("the update download was cancelled")
    with httpx.stream("GET", info.asset_url, headers={"User-Agent": USER_AGENT},
                      follow_redirects=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0)) or info.asset_size
        done = 0
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                if cancel is not None and cancel.is_set():
                    f.close()
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError("the update download was cancelled")
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    got = hashlib.sha256()
    with tmp.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            got.update(chunk)
    if expected and got.hexdigest() != expected:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("the update checksum does not match; the download was discarded")
    tmp.replace(dest)
    return dest


def launch_installer(path: Path) -> None:
    """Start the Inno Setup installer and close the current app. On non-Windows, open the page."""
    if sys.platform == "win32" and path.suffix.lower() == ".exe":
        subprocess.Popen([str(path), "/CLOSEAPPLICATIONS", "/NORESTART"],
                         close_fds=True)
        return
    webbrowser.open(RELEASES_PAGE)
