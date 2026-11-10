"""GitHub Releases update check and installer download.

Automatic checks are on by default: the app asks once after start-up and then every 24 hours,
unless the user saved ``check_updates`` as false. Only public release metadata and the installer
(with its published SHA-256) are fetched from this project's own GitHub release. There is no
signer pin, because the installer is not code-signed; instead the updater fails closed when a
checksum is missing or wrong, follows redirects only to GitHub's release asset hosts, and refuses
to run a file from anywhere else. Nothing about the user or the library is uploaded.
"""
from __future__ import annotations

import hashlib
import logging
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

from . import VERSION, config, musicbee

LOG = logging.getLogger(__name__)

REPO = "nishizumi-maho/lyricloom"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
STABLE_ASSET = "LyricLoom-Setup.exe"
USER_AGENT = f"LyricLoom/{VERSION} (+https://github.com/{REPO})"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
CHECK_INTERVAL_MS = CHECK_INTERVAL_SECONDS * 1000
INSTALL_MODES = ("auto", "ask", "notify")
DEFAULT_INSTALL_MODE = "auto"
SKIPPED_VERSION_SETTING = "skipped_update_version"
PLUGIN_SKIP_NOTICE_SETTING = "plugin_update_notice_pending"

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
    tarball_name: str = ""
    tarball_url: str = ""


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
    """The saved update-check choice: True/False once the user chose, None when never chosen.

    An absent choice means the automatic check is on; only an explicit false turns it off.
    """
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


def check_enabled() -> bool:
    """True unless the user explicitly saved ``check_updates`` as false."""
    return check_choice() is not False


def setup_complete() -> bool:
    """True once the setup assistant finished, i.e. the owner has seen the update choice."""
    return bool(config.setting("setup_complete", False))


def should_check_on_startup() -> bool:
    """Whether the app may contact GitHub automatically (start-up and the 24-hour timer).

    Nothing is requested before the setup assistant finished: the owner must have seen the
    update choice first. A manual Help > Check for updates does not go through this gate.
    The offscreen guard keeps GUI tests from making a real request; it is not a user setting.
    """
    return (check_enabled() and setup_complete()
            and os.environ.get("QT_QPA_PLATFORM") != "offscreen")


def should_check_automatically() -> bool:
    """Whether an automatic check (start-up or periodic) is allowed right now."""
    return should_check_on_startup()


def install_mode() -> str:
    """How a found update is offered: ``auto`` (default), ``ask`` or ``notify``."""
    value = config.setting("update_install", DEFAULT_INSTALL_MODE)
    return value if value in INSTALL_MODES else DEFAULT_INSTALL_MODE


def installer_available() -> bool:
    """True only for a packaged Windows build; source checkouts and Linux have no installer."""
    return sys.platform == "win32" and bool(config.IS_FROZEN)


def skipped_version() -> str:
    """The version the user asked not to be offered again, if any."""
    value = config.setting(SKIPPED_VERSION_SETTING, "")
    return value.strip() if isinstance(value, str) else ""


def is_skipped(version: str) -> bool:
    """True when ``version`` is the skipped release (a newer release is offered again)."""
    skipped = skipped_version()
    return bool(skipped) and _version_tuple(version) <= _version_tuple(skipped)


def skip_version(version: str) -> None:
    """Remember a release the user does not want to be offered again."""
    config.set_setting(SKIPPED_VERSION_SETTING, str(version))


def take_plugin_skip_notice() -> bool:
    """True once after a silent update to this very version skipped the installed MusicBee plugin.

    The setting holds the version the skipping install was going to install. The notice is due
    only when this build is that version (so the install really happened); the setting is cleared
    either way, including an old boolean value.
    """
    target = config.setting(PLUGIN_SKIP_NOTICE_SETTING, "")
    if target in (None, "", False):
        return False
    try:
        config.set_setting(PLUGIN_SKIP_NOTICE_SETTING, "")
    except OSError as exc:
        LOG.warning("could not clear the MusicBee plugin notice: %s", exc)
    return isinstance(target, str) and target.strip().lstrip("vV") == VERSION


def cleanup_stale_downloads() -> None:
    """Remove installer files in UPDATE_DIR that this process did not download and verify.

    A file left by an earlier run (or planted there) is never trusted, so it is deleted before
    the new process starts a download. Only direct regular files and symlinks are removed; this
    never recurses and never follows a symlink.
    """
    try:
        if UPDATE_DIR.is_symlink() or not UPDATE_DIR.is_dir():
            return
        entries = list(UPDATE_DIR.iterdir())
    except FileNotFoundError:
        return
    except OSError as exc:
        LOG.warning("could not read the update folder %s: %s", UPDATE_DIR, exc)
        return
    for entry in entries:
        try:
            if not entry.is_symlink() and entry.is_dir():
                continue
            if not entry.is_symlink() and entry.resolve() in _VERIFIED:
                continue
            entry.unlink()
        except OSError as exc:
            LOG.warning("could not remove the stale update file %s: %s", entry, exc)


def release_page_url(info: UpdateInfo) -> str:
    """The release page to open, restricted to this project's GitHub release URLs."""
    return info.page_url if _is_release_url(info.page_url) else RELEASES_PAGE


def open_release_page(info: UpdateInfo) -> None:
    """Open the release page in the user's browser. Only called from an explicit click."""
    webbrowser.open(release_page_url(info))


def open_tarball_page(info: UpdateInfo) -> bool:
    """Open the Linux tarball download for ``info``; False when it has no valid asset URL."""
    if info.tarball_url and _is_asset_url(info.tarball_url):
        webbrowser.open(info.tarball_url)
        return True
    return False


def musicbee_running() -> bool:
    """Whether MusicBee is running, so a silent install must not ask Restart Manager to close it.

    A failed process query (it cannot start, times out or exits with an error) is treated as
    "possibly running": skipping the plugin is safer than letting Restart Manager close the
    user's MusicBee. ``tasklist.exe`` is called by its absolute System32 path, never via PATH.
    """
    if sys.platform != "win32":
        return False
    system_root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    tasklist = str(Path(system_root) / "System32" / "tasklist.exe")
    try:
        result = subprocess.run(
            [tasklist, "/FI", "IMAGENAME eq MusicBee.exe", "/FO", "CSV", "/NH"],
            capture_output=True, timeout=10, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        LOG.warning("could not check whether MusicBee is running: %s", exc)
        return True
    if result.returncode != 0:
        LOG.warning("could not check whether MusicBee is running: tasklist exited with %s",
                    result.returncode)
        return True
    return "musicbee.exe" in (result.stdout or b"").decode(errors="replace").lower()


def _tarball_asset(assets: dict) -> tuple[str, str]:
    """The Linux tarball name and URL from this release, when they are a valid release asset."""
    for name, asset in assets.items():
        if not (str(name).startswith("LyricLoom-") and str(name).endswith("-linux-x86_64.tar.gz")):
            continue
        try:
            safe_name = _safe_asset_name(name)
        except RuntimeError:
            return "", ""
        url = str(asset.get("browser_download_url") or "")
        return (safe_name, url) if _is_asset_url(url) else ("", "")
    return "", ""


def check() -> UpdateInfo | None:
    """Return the latest release when it is newer than this build, else None. Network errors are
    reported to the caller as exceptions; the GUI turns them into a non-blocking status message."""
    release = _get_json(API_LATEST)
    tag = str(release.get("tag_name", "")).strip()
    version = tag.lstrip("vV")
    if not version or not is_newer(version):
        return None
    assets = {a.get("name", ""): a for a in release.get("assets", []) if isinstance(a, dict)}
    tarball_name, tarball_url = _tarball_asset(assets)
    asset = assets.get(STABLE_ASSET) or next(
        (a for name, a in assets.items()
         if name.startswith("LyricLoom-Setup-") and name.lower().endswith(".exe")), None)
    page = str(release.get("html_url") or "")
    common = dict(
        version=version,
        tag=tag,
        page_url=page if _is_release_url(page) else RELEASES_PAGE,
        notes=str(release.get("body") or ""),
        tarball_name=tarball_name,
        tarball_url=tarball_url,
    )
    if asset is None:
        if sys.platform != "win32" and tarball_url:
            # Linux has no installer: the notice links to the release page and this tarball.
            return UpdateInfo(asset_name="", asset_url="", asset_size=0, asset_sha256="", **common)
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
    digest = str(asset.get("digest") or "")
    sha = digest.split(":", 1)[1] if digest.lower().startswith("sha256:") else ""
    return UpdateInfo(
        asset_name=asset_name,
        asset_url=asset_url,
        asset_size=int(asset.get("size") or 0),
        asset_sha256=sha,
        checksum_url=checksum_url,
        **common,
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
    if UPDATE_DIR.is_symlink() or not UPDATE_DIR.is_dir():
        raise RuntimeError("refusing to download the update: the update folder is not a real directory")
    destination = UPDATE_DIR / name
    fd, temporary_name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".part", dir=UPDATE_DIR)
    temporary = Path(temporary_name)
    done = 0
    try:
        with os.fdopen(fd, "wb") as file:
            with _stream(info.asset_url, allowed=_is_asset_redirect,
                         headers={"User-Agent": USER_AGENT}) as response:
                total = int(response.headers.get("content-length", 0)) or info.asset_size
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


def _plugin_installed() -> bool:
    """Whether Starry Karaoke is in MusicBee's Plugins folder (the setup assistant's own rule)."""
    try:
        return (musicbee.plugins_dir() / musicbee.PLUGIN_DLL).is_file()
    except OSError:
        return False


def _remember_plugin_skip(version: str) -> None:
    """Remember the target version, so the start of that version explains the skipped plugin."""
    try:
        config.set_setting(PLUGIN_SKIP_NOTICE_SETTING, str(version))
    except OSError as exc:
        LOG.warning("could not remember the skipped MusicBee plugin update: %s", exc)


APP_MUTEX_NAME = "LyricLoomAppRunning"
_APP_MUTEX = None   # the handle is held for the life of the process and closed by Windows at exit


def hold_app_mutex() -> None:
    """Create the named mutex the installer waits on until every LyricLoom window has exited.

    Windows only; the handle is never closed explicitly, so the mutex lives exactly as long as
    this process. A failure is logged: the installer then falls back to its own process checks.
    """
    global _APP_MUTEX
    if sys.platform != "win32" or _APP_MUTEX is not None:
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateMutexW
    create.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    create.restype = wintypes.HANDLE
    handle = create(None, False, APP_MUTEX_NAME)
    if not handle:
        LOG.warning("could not create the %s mutex (error %s)", APP_MUTEX_NAME, ctypes.get_last_error())
        return
    _APP_MUTEX = handle


def launch_installer(path: Path, *, silent: bool, relaunch: bool, skip_plugin: bool,
                     version: str = "") -> None:
    """Start the verified installer, silently or interactively.

    ``silent`` uses Inno Setup's quiet switches plus ``/RELAUNCH=1`` when LyricLoom should start
    again and ``/SKIPPLUGIN=1`` when the optional MusicBee plugin must not be touched. A silent
    install never closes MusicBee: ``/NOCLOSEAPPLICATIONS`` is added when it is (or may be)
    running and the plugin task is skipped. When the plugin is installed, ``version`` (the
    release being installed) is remembered so that version's first start shows a notice. On
    non-Windows there is no installer, so an explicit download link is the only action (and
    silent mode is refused).
    """
    path = Path(path)
    expected = _VERIFIED.get(path.resolve())
    if expected is None or not path.is_file() or _sha256_file(path) != expected:
        raise RuntimeError("refusing to run an installer that LyricLoom did not download and verify "
                           "from its own GitHub release")
    if sys.platform == "win32" and path.suffix.lower() == ".exe":
        musicbee_open = False
        if silent:
            argv = [str(path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
            if musicbee_running():
                musicbee_open = True
                skip_plugin = True
                argv.append("/NOCLOSEAPPLICATIONS")
            if relaunch:
                argv.append("/RELAUNCH=1")
            if skip_plugin:
                argv.append("/SKIPPLUGIN=1")
        else:
            argv = [str(path), "/CLOSEAPPLICATIONS", "/NORESTART"]
        subprocess.Popen(argv, close_fds=True)
        if musicbee_open and version and _plugin_installed():
            _remember_plugin_skip(version)
        return
    if silent:
        raise RuntimeError("this build has no Windows installer; download the new version from the "
                           "release page")
    webbrowser.open(RELEASES_PAGE)
