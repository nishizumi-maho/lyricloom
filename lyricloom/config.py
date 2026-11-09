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
import threading
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
    """Copies settings from the pre-rename LyricsBoca data directory once. Returns True when a
    migration happened, so the caller can tell the user where the new data lives."""
    if SETTINGS_FILE != APP_DATA / "settings.json":
        return False   # tests and portable profiles manage their own settings
    if SETTINGS_FILE.exists():
        return False
    if not IS_WINDOWS:
        return False
    old = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LyricsBoca" / "settings.json"
    if not old.is_file():
        return False
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old, SETTINGS_FILE)
        return True
    except OSError:
        return False


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
# Kept for compatibility with older code and installs.  New code resolves a model through
# `models.catalog`/`resolve_model`, which understands the model_choices setting and custom models.
WHISPER_MODEL_NAME = os.environ.get("LYRICLOOM_WHISPER_MODEL", "ggml-large-v3.bin")
WHISPER_MODEL = MODELS / WHISPER_MODEL_NAME


def whisper_cli_candidates() -> list[Path]:
    """Every path checked for whisper-cli, in precedence order (the error message lists them)."""
    suffix = ".exe" if IS_WINDOWS else ""
    explicit = os.environ.get("LYRICLOOM_WHISPER_CLI") or _settings().get("whisper_cli")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(str(explicit)).expanduser())
    candidates += [
        RESOURCE_ROOT / "tools" / "bin" / f"whisper-cli{suffix}",
        PROJECT_ROOT / "tools" / "bin" / f"whisper-cli{suffix}",
        APP_DATA / "bin" / f"whisper-cli{suffix}",
    ]
    found = shutil.which("whisper-cli")
    if found:
        candidates.append(Path(found))
    return candidates


def whisper_cli() -> Path:
    """The whisper.cpp binary to run.

    Precedence: the ``whisper_cli`` setting (or ``LYRICLOOM_WHISPER_CLI``) > the bundled copy >
    a developer checkout's copy > the per-user bin folder > ``PATH``.  The configured candidate is
    returned even when missing, so the error message can name what the user set.
    """
    suffix = ".exe" if IS_WINDOWS else ""
    explicit = os.environ.get("LYRICLOOM_WHISPER_CLI") or _settings().get("whisper_cli")
    if explicit:
        return Path(str(explicit)).expanduser()
    for candidate in whisper_cli_candidates():
        if candidate.is_file():
            return candidate
    return RESOURCE_ROOT / "tools" / "bin" / f"whisper-cli{suffix}"


# --------------------------------------------------------------------------- model choices

# The model used by each stage for the track being processed (a per-track override from the CLI
# or the app's "Process with other models..." action).  A thread-local keeps concurrent folder
# runs from leaking a choice into another track.
_ACTIVE_MODELS = threading.local()
_ACTIVE_LANGUAGE = threading.local()


def set_active_models(overrides: dict[str, str] | None) -> None:
    _ACTIVE_MODELS.overrides = dict(overrides or {})


def clear_active_models() -> None:
    _ACTIVE_MODELS.overrides = {}


def active_models() -> dict[str, str]:
    return dict(getattr(_ACTIVE_MODELS, "overrides", {}) or {})


def set_active_language(lang: str | None) -> None:
    """The track's tag language, so stage helpers without a language argument (separation) can
    resolve a per-language model choice."""
    _ACTIVE_LANGUAGE.lang = lang


def active_language() -> str | None:
    return getattr(_ACTIVE_LANGUAGE, "lang", None)


def clear_active_language() -> None:
    _ACTIVE_LANGUAGE.lang = None


def model_choices() -> dict:
    value = _settings().get("model_choices")
    return value if isinstance(value, dict) else {}


def resolve_model(stage: str, lang: str | None = None,
                  models: dict[str, str] | None = None):
    """The :class:`lyricloom.models.ModelSpec` a stage should use for ``lang``.

    Precedence: per-run ``models`` override > language choice > default choice > catalog default.
    Unknown or invalid ids are logged and skipped; this function always returns a model.
    """
    from . import models as catalog

    merged = {**active_models(), **(models or {})}
    return catalog.resolve(stage, lang=lang if lang is not None else active_language(),
                           overrides=merged, choices=model_choices())


# Resolved at import for compatibility; transcribe() asks whisper_cli() at stage start so a setting
# changed in the app takes effect without restarting.
WHISPER_CLI = whisper_cli()

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

# Optional AssemblyAI transcription (cloud). Off unless the user pastes a key; the key never lives
# in the repository.
ASSEMBLYAI_KEY_FILE = APP_DATA / "assemblyai.key"
ASSEMBLYAI_ENABLED = ASSEMBLYAI_KEY_FILE.exists() or bool(os.environ.get("ASSEMBLYAI_API_KEY"))


def set_assemblyai_key(key: str) -> None:
    """Stores (or, when empty, removes) the AssemblyAI key."""
    global ASSEMBLYAI_ENABLED
    key = key.strip()
    if key:
        ASSEMBLYAI_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        ASSEMBLYAI_KEY_FILE.write_text(key, encoding="utf-8")
    elif ASSEMBLYAI_KEY_FILE.exists():
        ASSEMBLYAI_KEY_FILE.unlink()
    ASSEMBLYAI_ENABLED = bool(key) or bool(os.environ.get("ASSEMBLYAI_API_KEY"))
