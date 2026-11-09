"""Find MusicBee and install the bundled Starry Karaoke plugin files.

The installer (``packaging/windows/LyricLoom.iss``) and the setup assistant must agree on what
counts as "MusicBee is installed" and on which files may be replaced:

* the plugin's own files (``mb_StarryKaraoke.dll``, the recorder and its config, the licenses and
  the readme) are replaced on every install;
* ``RomajiCore.dll`` and ``LibNMeCab.dll`` are shared with the Desktop Lyrics (Romaji) plugin, so
  they are replaced only when the bundled copy is newer;
* the ``RomajiLyrics\\IpaDic`` dictionary is large and stable, so it is copied only when it is
  missing.

Nothing here imports Qt.  Every external effect (the process list, the registry, the file version)
is injectable so tests never need MusicBee, a real DLL or a Windows display.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import config

log = logging.getLogger(__name__)

PLUGIN_DLL = "mb_StarryKaraoke.dll"
SHARED_DLLS = ("RomajiCore.dll", "LibNMeCab.dll")
DICTIONARY_FOLDER = "RomajiLyrics"
MUSICBEE_EXE = "MusicBee.exe"
MUSICBEE_RUNNING_MESSAGE = "Close MusicBee and try again."


class MusicBeeError(RuntimeError):
    """The plugin could not be copied; the message is meant for the user."""


class MusicBeeRunning(MusicBeeError):
    """MusicBee has the plugin files open, so nothing was written."""


class PluginMissing(MusicBeeError):
    """This build does not contain the Starry Karaoke plugin files."""


@dataclass(frozen=True)
class MusicBeeStatus:
    """What the setup assistant's MusicBee page shows."""

    detected: bool
    plugins_dir: Path
    plugin_installed: bool
    plugin_version: str
    evidence: tuple[str, ...] = field(default_factory=tuple)

    @property
    def summary(self) -> str:
        if not self.detected:
            return ("MusicBee was not found. LyricLoom works without it; the built-in player and "
                    "the karaoke window are enough.")
        if self.plugin_installed:
            version = f" {self.plugin_version}" if self.plugin_version else ""
            return f"MusicBee found. Starry Karaoke is installed (version{version})."
        return "MusicBee found. Starry Karaoke is not installed in the MusicBee Plugins folder."


@dataclass(frozen=True)
class InstallResult:
    """Which plugin files were copied and which were deliberately kept."""

    destination: Path
    copied: tuple[Path, ...] = field(default_factory=tuple)
    skipped: tuple[Path, ...] = field(default_factory=tuple)

    @property
    def changed(self) -> bool:
        return bool(self.copied)


VersionOf = Callable[[Path], str]
Running = Callable[[], bool]
Progress = Callable[[str, int, int], None]


# --------------------------------------------------------------------------- locations


def appdata_dir() -> Path:
    """The roaming application-data folder (``%APPDATA%`` on Windows)."""
    value = os.environ.get("APPDATA")
    if value:
        return Path(value)
    return Path.home() / "AppData" / "Roaming"


def musicbee_dir(appdata: Path | str | None = None) -> Path:
    return Path(appdata if appdata is not None else appdata_dir()) / "MusicBee"


def plugins_dir(appdata: Path | str | None = None) -> Path:
    """MusicBee's per-user Plugins folder, where the installer puts the plugin."""
    return musicbee_dir(appdata) / "Plugins"


def bundled_plugin_dir() -> Path | None:
    """Where this build keeps the plugin files, or ``None`` when it has no copy.

    A frozen Windows build bundles ``dist\\MusicBeePlugin`` as ``_internal\\musicbee``.  A source
    checkout uses the staging folder the build script produces.
    """
    candidates: list[Path] = []
    if config.IS_FROZEN:
        candidates.append(Path(config.RESOURCE_ROOT) / "musicbee")
    candidates += [
        Path(config.PROJECT_ROOT) / "dist" / "MusicBeePlugin",
        Path(config.PROJECT_ROOT) / "musicbee" / "dist" / "MusicBeePlugin",
    ]
    for candidate in candidates:
        if (candidate / PLUGIN_DLL).is_file():
            return candidate
    return None


# --------------------------------------------------------------------------- versions


def version_tuple(value: str) -> tuple[int, ...]:
    """``"2.1.0.0"`` -> ``(2, 1, 0, 0)``; used only for "is this file newer?" comparisons."""
    parts = [part for part in str(value).replace(",", ".").split(".") if part.strip()]
    numbers: list[int] = []
    for part in parts:
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            break
        numbers.append(int(digits))
    while len(numbers) < 4:
        numbers.append(0)
    return tuple(numbers[:4])


def newer_version(candidate: str, installed: str) -> bool:
    """True only when both versions are readable and ``candidate`` is strictly newer."""
    if not candidate or not installed:
        return False
    return version_tuple(candidate) > version_tuple(installed)


def _windows_file_version(path: Path) -> str:
    """The fixed file version from a PE resource, through ``version.dll`` (no pywin32)."""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:  # pragma: no cover - ctypes is always available on Windows
        return ""

    class FixedFileInfo(ctypes.Structure):
        _fields_ = [
            ("dwSignature", wintypes.DWORD),
            ("dwStrucVersion", wintypes.DWORD),
            ("dwFileVersionMS", wintypes.DWORD),
            ("dwFileVersionLS", wintypes.DWORD),
            ("dwProductVersionMS", wintypes.DWORD),
            ("dwProductVersionLS", wintypes.DWORD),
            ("dwFileFlagsMask", wintypes.DWORD),
            ("dwFileFlags", wintypes.DWORD),
            ("dwFileOS", wintypes.DWORD),
            ("dwFileType", wintypes.DWORD),
            ("dwFileSubtype", wintypes.DWORD),
            ("dwFileDateMS", wintypes.DWORD),
            ("dwFileDateLS", wintypes.DWORD),
        ]

    try:
        version = ctypes.WinDLL("version", use_last_error=True)
        version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
        version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                                ctypes.c_void_p]
        version.GetFileVersionInfoW.restype = wintypes.BOOL
        version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                           ctypes.POINTER(ctypes.c_void_p),
                                           ctypes.POINTER(wintypes.UINT)]
        version.VerQueryValueW.restype = wintypes.BOOL

        size = version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return ""
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
            return ""
        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version.VerQueryValueW(ctypes.cast(buffer, ctypes.c_void_p), "\\",
                                      ctypes.byref(pointer), ctypes.byref(length)):
            return ""
        info = ctypes.cast(pointer, ctypes.POINTER(FixedFileInfo)).contents
        if info.dwSignature != 0xFEEF04BD:
            return ""
        high, low = info.dwFileVersionMS, info.dwFileVersionLS
        return (f"{high >> 16}.{high & 0xFFFF}.{low >> 16}.{low & 0xFFFF}")
    except (OSError, ValueError):
        return ""


def file_version(path: Path | str) -> str:
    """The DLL/EXE file version, or ``""`` when the platform cannot read one."""
    path = Path(path)
    if not config.IS_WINDOWS or not path.is_file():
        return ""
    return _windows_file_version(path)


# --------------------------------------------------------------------------- detection


def _registry_evidence() -> list[str]:
    """The registry keys the Inno Setup ``MusicBeeDetected`` function checks."""
    if not config.IS_WINDOWS:
        return []
    try:
        import winreg
    except ImportError:  # pragma: no cover - Windows always has winreg
        return []
    keys = [
        (winreg.HKEY_CURRENT_USER, r"Software\MusicBee"),
        (winreg.HKEY_CURRENT_USER,
         r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicBee"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicBee"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\MusicBee"),
    ]
    found: list[str] = []
    for root, name in keys:
        try:
            with winreg.OpenKey(root, name):
                found.append(f"registry {name}")
        except OSError:
            continue
    return found


def _program_files_evidence(roots: list[Path] | None = None) -> list[str]:
    if roots is None:
        values = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                  r"C:\Program Files", r"C:\Program Files (x86)"]
        roots = []
        seen: set[str] = set()
        for value in values:
            if not value:
                continue
            key = value.lower()
            if key not in seen:
                seen.add(key)
                roots.append(Path(value))
    found: list[str] = []
    for root in roots:
        exe = Path(root) / "MusicBee" / MUSICBEE_EXE
        if exe.is_file():
            found.append(str(exe))
    return found


def detect_musicbee(appdata: Path | str | None = None,
                    program_files: list[Path] | None = None,
                    registry_evidence: Callable[[], list[str]] | None = None) -> MusicBeeStatus:
    """Same rule as the installer: MusicBee is detected by its folders, registry keys or exe."""
    musicbee = musicbee_dir(appdata)
    plugins = musicbee / "Plugins"
    evidence: list[str] = []
    if plugins.is_dir():
        evidence.append(str(plugins))
    if musicbee.is_dir() and not plugins.is_dir():
        evidence.append(str(musicbee))
    registry = registry_evidence or _registry_evidence
    try:
        evidence.extend(registry())
    except Exception as exc:  # noqa: BLE001 - a locked registry must not hide the folders
        log.debug("could not read MusicBee registry marks: %s", exc)
    evidence.extend(_program_files_evidence(program_files))
    dll = plugins / PLUGIN_DLL
    installed = dll.is_file()
    return MusicBeeStatus(
        detected=bool(evidence),
        plugins_dir=plugins,
        plugin_installed=installed,
        plugin_version=file_version(dll) if installed else "",
        evidence=tuple(dict.fromkeys(evidence)),
    )


def is_musicbee_running() -> bool:
    """True when ``MusicBee.exe`` is in the process list.  Never raises."""
    if not config.IS_WINDOWS:
        return False
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq MusicBee.exe", "/NH"],
            capture_output=True, text=True, timeout=10, creationflags=creationflags)
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("could not read the process list: %s", exc)
        return False
    return "musicbee.exe" in (result.stdout or "").lower()


# --------------------------------------------------------------------------- install


def _safe_target(destination: Path, relative: Path) -> Path:
    target = destination.joinpath(relative)
    try:
        target.resolve().relative_to(destination.resolve())
    except (OSError, ValueError) as exc:
        raise MusicBeeError(f"refusing to write outside the MusicBee Plugins folder: {relative}") from exc
    return target


def install_plugin(source: Path | str | None = None, destination: Path | str | None = None,
                   *, running: Running | None = None, version_of: VersionOf | None = None,
                   progress: Progress | None = None) -> InstallResult:
    """Copies the bundled plugin into the Plugins folder using the installer's rules.

    Raises :class:`MusicBeeRunning` before writing anything when MusicBee has the DLLs open, and
    :class:`PluginMissing` when this build has no plugin files.  File-copy errors are wrapped in
    :class:`MusicBeeError` with the path that failed.
    """
    check_running = running or is_musicbee_running
    if check_running():
        raise MusicBeeRunning(MUSICBEE_RUNNING_MESSAGE)

    source_dir = Path(source) if source is not None else bundled_plugin_dir()
    if source_dir is None or not (source_dir / PLUGIN_DLL).is_file():
        raise PluginMissing(
            "This build does not include the Starry Karaoke plugin files. "
            "Install the plugin from its releases page.")
    destination_dir = Path(destination) if destination is not None else plugins_dir()
    version_getter = version_of or file_version
    files = sorted(path for path in source_dir.rglob("*") if path.is_file())
    if not files:
        raise PluginMissing(f"the bundled plugin folder is empty: {source_dir}")

    copied: list[Path] = []
    skipped: list[Path] = []
    for index, path in enumerate(files, start=1):
        relative = path.relative_to(source_dir)
        target = _safe_target(destination_dir, relative)
        parts = relative.parts
        shared = len(parts) == 1 and parts[0] in SHARED_DLLS
        dictionary = bool(parts) and parts[0].lower() == DICTIONARY_FOLDER.lower()
        if shared:
            if target.is_file() and not newer_version(version_getter(path), version_getter(target)):
                skipped.append(relative)
                if progress:
                    progress(str(relative), index, len(files))
                continue
        elif dictionary and target.exists():
            skipped.append(relative)
            if progress:
                progress(str(relative), index, len(files))
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        except OSError as exc:
            raise MusicBeeError(f"could not copy {relative} to {target}: {exc}") from exc
        copied.append(relative)
        if progress:
            progress(str(relative), index, len(files))
    log.info("copied %d Starry Karaoke file(s) to %s", len(copied), destination_dir)
    return InstallResult(destination=destination_dir, copied=tuple(copied), skipped=tuple(skipped))


def current_plugin_version(appdata: Path | str | None = None) -> str:
    """The installed plugin DLL's version, or ``""`` when it is not installed."""
    dll = plugins_dir(appdata) / PLUGIN_DLL
    return file_version(dll) if dll.is_file() else ""


__all__ = [
    "DICTIONARY_FOLDER",
    "InstallResult",
    "MUSICBEE_RUNNING_MESSAGE",
    "MusicBeeError",
    "MusicBeeRunning",
    "MusicBeeStatus",
    "PLUGIN_DLL",
    "PluginMissing",
    "SHARED_DLLS",
    "appdata_dir",
    "bundled_plugin_dir",
    "current_plugin_version",
    "detect_musicbee",
    "file_version",
    "install_plugin",
    "is_musicbee_running",
    "musicbee_dir",
    "newer_version",
    "plugins_dir",
    "version_tuple",
]
