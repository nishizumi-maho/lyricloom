"""Paths, settings and optional hardware backends for LyricLoom.

Everything LyricLoom writes lives in the per-user data directory, never in the source tree or in
Program Files:

* Windows: ``%LOCALAPPDATA%\\LyricLoom``
* Linux/macOS: ``$XDG_DATA_HOME/lyricloom`` (usually ``~/.local/share/lyricloom``)

``LYRICLOOM_DATA_DIR`` and ``LYRICLOOM_MODELS`` override those locations, which is useful for
portable installs and for tests.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "LyricLoom"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# PyInstaller sets sys._MEIPASS to the read-only bundle directory.
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
IS_WINDOWS = os.name == "nt"
IS_FROZEN = bool(getattr(sys, "frozen", False))


def _data_home() -> Path:
    override = os.environ.get("LYRICLOOM_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if IS_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "lyricloom"


APP_DATA = _data_home()
DEFAULT_WORK = APP_DATA / "work"
WORK_ROOT = DEFAULT_WORK
SETTINGS_FILE = APP_DATA / "settings.json"
LOG_DIR = APP_DATA / "logs"

# The library is chosen on first run. Music is a sensible default; the app offers a folder picker
# when it does not exist (or is empty).
DEFAULT_LIBRARY = Path.home() / "Music"
LIBRARY_ROOT = DEFAULT_LIBRARY   # kept as a module attribute so the app and tests can override it
# Lossless isolated vocals are cached outside the library so they never clutter the user's folders.
DEFAULT_VOCALS = APP_DATA / "vocals"


def _settings() -> dict:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_setting(key: str, value) -> None:
    data = _settings()
    data[key] = value
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_name(SETTINGS_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, SETTINGS_FILE)


def setting(key: str, default=None):
    return _settings().get(key, default)


def all_settings() -> dict:
    return dict(_settings())


def update_settings(values: dict) -> None:
    """Writes several settings at once (one atomic file replace)."""
    data = _settings()
    data.update(values)
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_name(SETTINGS_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, SETTINGS_FILE)


def set_setting(key: str, value) -> None:
    _save_setting(key, value)


def _flag(value) -> bool:
    """A JSON boolean setting, tolerating 0/1 and common string spellings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def library_root() -> Path:
    """The library chosen in the app (shared with the command line), else LIBRARY_ROOT."""
    chosen = _settings().get("library")
    return Path(chosen).expanduser() if chosen else Path(LIBRARY_ROOT)


def set_library_root(path: Path) -> None:
    _save_setting("library", str(path))


def vocals_root() -> Path:
    """Where isolated vocals are kept (the "vocals" setting), else DEFAULT_VOCALS."""
    chosen = _settings().get("vocals")
    return Path(chosen).expanduser() if chosen else Path(DEFAULT_VOCALS)


def set_vocals_root(path: Path) -> None:
    _save_setting("vocals", str(path))


def work_root() -> Path:
    """Scratch/cache folder for the pipeline. Large libraries can put it on another drive."""
    chosen = os.environ.get("LYRICLOOM_WORK") or _settings().get("work")
    return Path(chosen).expanduser() if chosen else Path(DEFAULT_WORK)


def set_work_root(path: Path) -> None:
    _save_setting("work", str(path))


WORK_ROOT = work_root()


def japanese_script() -> str:
    """Which script Japanese lyrics use in the .lrc players read: "japanese" or "romaji".
    Both are always kept as <song>.japanese.lrc and <song>.romaji.lrc."""
    return "romaji" if _settings().get("japanese_script") == "romaji" else "japanese"


def set_japanese_script(script: str) -> None:
    _save_setting("japanese_script", script)


def migrate_legacy_settings() -> bool:
    """Migrates settings and the data folders from the pre-rename LyricsBoca directory once.

    Returns True when something was migrated, so the caller can tell the user where the new data
    lives. A portable or test profile (``LYRICLOOM_DATA_DIR`` / ``LYRICLOOM_MODELS``) is never
    migrated, because it explicitly manages its own files."""
    if os.environ.get("LYRICLOOM_DATA_DIR") or os.environ.get("LYRICLOOM_MODELS"):
        return False
    if SETTINGS_FILE != APP_DATA / "settings.json":
        return False   # tests and portable profiles manage their own settings
    if not IS_WINDOWS:
        return False
    old = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LyricsBoca"
    if not old.is_dir():
        return False
    APP_DATA.mkdir(parents=True, exist_ok=True)
    changed = False
    moved: set[str] = set()
    old_settings = old / "settings.json"
    if not SETTINGS_FILE.exists() and old_settings.is_file():
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old_settings, SETTINGS_FILE)
            changed = True
        except OSError:
            return False
    # Move rather than copy: models alone can be several gigabytes and both folders are normally
    # on the same drive. An existing destination is never overwritten.
    for name in ("models", "vocals", "work"):
        source, destination = old / name, APP_DATA / name
        if source.is_dir() and not destination.exists():
            try:
                shutil.move(str(source), str(destination))
                moved.add(name)
                changed = True
            except OSError:
                pass
    old_key, new_key = old / "assemblyai.key", APP_DATA / "assemblyai.key"
    if old_key.is_file() and not new_key.exists():
        try:
            shutil.move(str(old_key), str(new_key))
            changed = True
        except OSError:
            pass
    if changed and moved and SETTINGS_FILE.exists():
        # The copied settings still name the old folders; point the moved ones at the new location.
        updates: dict[str, str] = {}
        data = _settings()
        for key in ("vocals", "work", "models"):
            value = data.get(key)
            if not isinstance(value, str) or not value:
                continue
            try:
                relative = Path(value).expanduser().relative_to(old)
            except ValueError:
                continue
            if not relative.parts or relative.parts[0] not in moved:
                continue
            updates[key] = str(APP_DATA / relative)
        if updates:
            update_settings(updates)
    return changed


# --------------------------------------------------------------------------- models and tools

def models_root() -> Path:
    """Where large model files are stored.

    Order: ``LYRICLOOM_MODELS``, the ``models`` setting, a developer checkout's ``models/``
    directory (so local development keeps working), then the per-user data directory.
    """
    override = os.environ.get("LYRICLOOM_MODELS")
    if override:
        return Path(override).expanduser()
    chosen = _settings().get("models")
    if chosen:
        return Path(chosen).expanduser()
    local = PROJECT_ROOT / "models"
    if local.is_dir() and (any(local.glob("*.bin")) or (local / "separator").is_dir()):
        return local
    return APP_DATA / "models"


MODELS = models_root()
WHISPER_MODEL_NAME = os.environ.get("LYRICLOOM_WHISPER_MODEL", "ggml-large-v3.bin")
WHISPER_MODEL = MODELS / WHISPER_MODEL_NAME


def _tool(name: str) -> Path | None:
    """A bundled or installed helper binary, with the platform suffix."""
    suffix = ".exe" if IS_WINDOWS else ""
    candidates = [
        RESOURCE_ROOT / "tools" / "bin" / f"{name}{suffix}",
        PROJECT_ROOT / "tools" / "bin" / f"{name}{suffix}",
        APP_DATA / "bin" / f"{name}{suffix}",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which(name)
    return Path(found) if found else None


WHISPER_CLI = _tool("whisper-cli") or (
    RESOURCE_ROOT / "tools" / "bin" / ("whisper-cli.exe" if IS_WINDOWS else "whisper-cli"))

# Mel-Band RoFormer with one of the highest published vocals SDRs in audio-separator.
SEPARATOR_MODEL = "vocals_mel_band_roformer.ckpt"
SEPARATOR_MODEL_DIR = MODELS / "separator"
# "auto" lets audio-separator pick CUDA/ROCm when the installed torch supports it; "cpu" forces
# the CPU. The WSL/ROCm path below is independent of this.
SEPARATOR_DEVICE = os.environ.get("LYRICLOOM_SEPARATOR_DEVICE", "auto")
SEPARATOR_OVERLAP = int(os.environ.get("LYRICLOOM_SEPARATOR_OVERLAP", "2"))
CPU_THREADS = max(1, int(os.environ.get("LYRICLOOM_CPU_THREADS", (os.cpu_count() or 4) // 4)))
SEPARATOR_PYTHON = sys.executable


# --------------------------------------------------------------------------- WSL / ROCm (Windows)

def _wsl_distros() -> list[str]:
    if not IS_WINDOWS or shutil.which("wsl.exe") is None:
        return []
    try:
        out = subprocess.run(["wsl.exe", "-l", "-q"], capture_output=True, timeout=8,
                             stdin=subprocess.DEVNULL)
        text = out.stdout.decode("utf-16-le", "replace") if b"\x00" in out.stdout else out.stdout.decode("utf-8", "replace")
        return [line.strip().replace("\x00", "") for line in text.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


def _wsl_has(distro: str, path: str) -> bool:
    try:
        return subprocess.run(["wsl.exe", "-d", distro, "--", "test", "-x", path],
                              capture_output=True, timeout=10, stdin=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def wsl_distro() -> str:
    chosen = setting("wsl_distro")
    if chosen:
        return str(chosen)
    distros = _wsl_distros()
    return distros[0] if distros else ""


def wsl_python(distro: str | None = None) -> str:
    """Interpreter inside the distro. The first configured venv that exists wins; otherwise
    python3 is used (the system packages must then provide torch/audio-separator)."""
    chosen = setting("wsl_python")
    if chosen:
        return str(chosen)
    distro = distro or wsl_distro()
    for candidate in ("/opt/lyricloom/venv/bin/python",):
        if distro and _wsl_has(distro, candidate):
            return candidate
    return "python3"


def _wsl_env() -> dict:
    env = dict(setting("wsl_env") or {})
    override = setting("wsl_hsa_override")
    if override:
        env.setdefault("HSA_OVERRIDE_GFX_VERSION", str(override))
    return env


# WSL is opt-in: a fresh install must not launch the distro on every startup. The app's Settings
# screen writes wsl_gpu=true after the user runs the WSL setup helper.
SEPARATOR_WSL_ENABLED = bool(IS_WINDOWS and shutil.which("wsl.exe") and setting("wsl_gpu", False))
SEPARATOR_WSL_DISTRO = (wsl_distro() if SEPARATOR_WSL_ENABLED else "") or str(setting("wsl_distro", "Ubuntu"))
SEPARATOR_WSL_PYTHON = (wsl_python(SEPARATOR_WSL_DISTRO) if SEPARATOR_WSL_ENABLED else "") or "python3"
SEPARATOR_WSL_ENV = _wsl_env()
# Optional: a copy of the separator model inside the distro (e.g. /opt/lyricloom/models/separator).
# Loading it from /mnt is slower, so the WSL setup helper can copy it there.
WSL_MODELS_DIR = str(setting("wsl_models_dir", ""))

# Forced alignment (MMS_FA wav2vec2) runs on the GPU in the same WSL distro. TORCH_HOME points at
# a cache inside the distro; checkpoints read from /mnt are several times slower to load.
ALIGN_DEVICE = os.environ.get("LYRICLOOM_ALIGN_DEVICE", "cpu" if IS_WINDOWS else "auto")
ALIGN_WSL_ENABLED = SEPARATOR_WSL_ENABLED
ALIGN_WSL_DISTRO = SEPARATOR_WSL_DISTRO
ALIGN_WSL_PYTHON = SEPARATOR_WSL_PYTHON
ALIGN_WSL_ENV = {"TORCH_HOME": str(setting("wsl_torch_home", "/opt/lyricloom/models/torch")),
                 **SEPARATOR_WSL_ENV}

# English songs: LyricsAlignment-MTL (trained on sung vocals) times the words; on English pop test
# tracks it put 92-99% of words within 300 ms of human timing vs 69-82% for CTC. The inference
# code is vendored (MIT); the 66 MB checkpoint is downloaded on first use.
MTL_REPO = Path(__file__).resolve().parent / "vendor" / "mtl"
MTL_CHECKPOINT = MODELS / "mtl" / "checkpoints" / "checkpoint_MTL"
MTL_PYTHON = Path(sys.executable)
MTL_ENABLED = (MTL_REPO / "wrapper.py").is_file()
MTL_WSL_ENABLED = MTL_ENABLED and ALIGN_WSL_ENABLED
MTL_WSL_REPO = str(setting("wsl_mtl_repo", "/opt/lyricloom/mtl"))
MTL_WSL_CHECKPOINT = str(setting("wsl_mtl_checkpoint", "/opt/lyricloom/models/mtl"))
MTL_WSL_ENV = dict(ALIGN_WSL_ENV)

# --------------------------------------------------------------------------- optional cloud

# Optional AssemblyAI transcription (cloud). A key alone does not turn it on: cloud transcription
# is an explicit setting (`assemblyai_enabled`, default false) and every run can also refuse it
# through `runner.process(..., allow_cloud=...)`. The key never lives in the repository.
ASSEMBLYAI_KEY_FILE = APP_DATA / "assemblyai.key"
_DPAPI_MAGIC = b"DPAPI1\n"


def assemblyai_enabled() -> bool:
    """Whether the user turned cloud transcription on in Settings (default: off)."""
    return _flag(_settings().get("assemblyai_enabled", False))


def set_assemblyai_enabled(value: bool) -> None:
    """Stores the cloud-transcription choice. The key is stored separately."""
    _save_setting("assemblyai_enabled", bool(value))


def _dpapi(data: bytes, protect: bool) -> bytes:
    """CryptProtectData/CryptUnprotectData for the current Windows user, through ctypes."""
    if not IS_WINDOWS:
        raise OSError("Windows DPAPI is not available on this platform")
    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    def blob(value: bytes):
        buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        return DataBlob(len(value), buffer), buffer

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    source, keepalive = blob(data)   # noqa: F841 - keepalive owns the source buffer
    result = DataBlob()
    if protect:
        function = crypt32.CryptProtectData
        function.argtypes = [ctypes.POINTER(DataBlob), wintypes.LPCWSTR, ctypes.POINTER(DataBlob),
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(DataBlob)]
        args = (ctypes.byref(source), "LyricLoom AssemblyAI key", None, None, None, 0x1,
                ctypes.byref(result))
    else:
        function = crypt32.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.POINTER(DataBlob),
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(DataBlob)]
        args = (ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(result))
    function.restype = wintypes.BOOL
    if not function(*args):
        code = ctypes.get_last_error()
        raise OSError(code, "CryptProtectData failed" if protect else "CryptUnprotectData failed")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


def _write_key_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if IS_WINDOWS:
        try:
            protected = _dpapi(text.encode("utf-8"), protect=True)
        except OSError as exc:
            raise RuntimeError(f"could not encrypt the AssemblyAI key for this Windows user: {exc}") from exc
        path.write_bytes(_DPAPI_MAGIC + protected)
        return
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
        file.write(text)
    os.chmod(path, 0o600)


def _read_key_text(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"could not read the AssemblyAI key file: {exc}") from exc
    if raw.startswith(_DPAPI_MAGIC):
        if not IS_WINDOWS:
            raise RuntimeError("the AssemblyAI key was encrypted with Windows DPAPI and cannot be read "
                               "on this platform; add the key again")
        try:
            return _dpapi(raw[len(_DPAPI_MAGIC):], protect=False).decode("utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise RuntimeError("the AssemblyAI key could not be decrypted for this Windows user; "
                               "add the key again") from exc
    text = raw.decode("utf-8", "replace").strip()
    if text:
        _write_key_text(path, text)   # migrate a plain-text key on first read
    return text


def read_assemblyai_key() -> str:
    """The AssemblyAI key from the environment or the data file, decrypted/migrated as needed."""
    path = ASSEMBLYAI_KEY_FILE
    environment_key = os.environ.get("ASSEMBLYAI_API_KEY", "").strip()
    file_key = ""
    if path.is_file():
        try:
            file_key = _read_key_text(path)   # also migrates a plain-text file on first read
        except Exception:
            if not environment_key:
                raise
    if environment_key:
        return environment_key
    if file_key and not IS_WINDOWS:
        try:
            if os.stat(path).st_mode & 0o077:
                os.chmod(path, 0o600)
        except OSError:
            pass
    return file_key


def has_assemblyai_key() -> bool:
    """Whether a key is configured, without decrypting or exposing it."""
    return bool(os.environ.get("ASSEMBLYAI_API_KEY", "").strip()) or ASSEMBLYAI_KEY_FILE.is_file()


def redact_assemblyai_key(text: str) -> str:
    """Removes a configured key from text that is about to be logged or shown to the user."""
    try:
        key = read_assemblyai_key()
    except Exception:  # noqa: BLE001 - a broken key file must not break logging
        return text
    return text.replace(key, "***") if key else text


def set_assemblyai_key(key: str) -> None:
    """Stores (or, when empty, removes) the AssemblyAI key.

    Having a key does **not** enable cloud transcription; `assemblyai_enabled` is a separate
    setting, so an environment-provided key can never be mistaken for consent."""
    key = key.strip()
    if key:
        _write_key_text(ASSEMBLYAI_KEY_FILE, key)
    else:
        ASSEMBLYAI_KEY_FILE.unlink(missing_ok=True)
