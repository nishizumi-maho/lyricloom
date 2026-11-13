"""Setup detection and acceleration backends, with no Qt and no hidden network calls.

The setup assistant imports this module; everything here runs from a plain Python process.  Every
external command goes through an injectable :data:`Runner` and every download through an injectable
:data:`Downloader`, so tests never need WSL, a GPU, the network or a real install.

Public surface:

* :func:`detect` returns a :class:`SystemReport` (OS, CPU, RAM, disk, GPUs, WSL, whisper-cli).
* :func:`recommend` turns a report into a :class:`Recommendation` with one reason per item.
* :func:`find_wsl_environments` probes the interpreters inside a WSL distro.
* :func:`use_wsl_environment` stores the WSL GPU settings, but only after a passing probe.
* :func:`run_wsl_setup` streams ``packaging/wsl/setup-lyricloom-wsl.sh`` then probes the result.
* :func:`install_whisper_backend` installs an official whisper.cpp Windows build and points the
  ``whisper_cli`` setting at it; :func:`remove_whisper_backend` and :func:`use_bundled_whisper`
  undo that.

Nothing in this module elevates privileges.  The only elevated command is the one the GUI may
start itself with :func:`wsl_install_command`.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Callable

from . import config, downloads
from .errtext import error_text
from .workers import WorkerCancelled, run_process, run_process_stream, wsl_path
from .workers.probe_gpu import RESULT_MARK as PROBE_MARK

log = logging.getLogger(__name__)

GiB = 1024 ** 3
WSL_DISTRO = "Ubuntu-24.04"
WSL_SCRIPT_NAME = "setup-lyricloom-wsl.sh"
WSL_VENV_PYTHON = "/opt/lyricloom/venv/bin/python"
WSL_PROBE_TIMEOUT_S = 180.0
WHISPER_CPP_VERSION = "1.9.2"
WHISPER_HELP_TIMEOUT_S = 20.0
WSL_SETUP_TIMEOUT_S = 3600.0
SETUP_RESULT_MARK = "@@lyricloom-setup "


class SetupError(RuntimeError):
    """A setup step could not be completed; the message is meant for the user."""


class BackendError(SetupError):
    """A downloaded transcription backend is unusable (bad archive, missing binary, no help)."""


@dataclass(frozen=True)
class CommandResult:
    """The small part of ``subprocess.CompletedProcess`` the probes need."""

    returncode: int
    stdout: bytes = b""
    stderr: bytes = b""


# ``runner(argv, timeout_s, *, input_bytes=b"", cancel=None) -> CommandResult``.  Tests replace it
# with a fake; production uses :func:`_run`.
Runner = Callable[..., CommandResult]
# ``downloader(spec, dest, progress=..., cancel=...) -> Path``; tests pass a local writer.
Downloader = Callable[..., Path]


def _run(argv: list[str], timeout_s: float, *, input_bytes: bytes = b"",
         cancel: threading.Event | None = None) -> CommandResult:
    proc = run_process(argv, input_bytes=input_bytes, timeout_s=timeout_s, cancel=cancel)
    return CommandResult(proc.returncode, proc.stdout or b"", proc.stderr or b"")


# --------------------------------------------------------------------------- small value types


@dataclass(frozen=True)
class GpuAdapter:
    """One display adapter reported by Windows."""

    name: str
    vendor: str = "other"            # nvidia | amd | intel | other
    memory_bytes: int | None = None
    driver_version: str = ""


@dataclass(frozen=True)
class NvidiaGpu:
    """One GPU reported by ``nvidia-smi``."""

    name: str
    driver_version: str = ""
    memory_bytes: int | None = None


@dataclass(frozen=True)
class WslDistro:
    """One distro from ``wsl.exe -l -v``."""

    name: str
    state: str = ""
    version: int = 0
    default: bool = False


@dataclass(frozen=True)
class WslState:
    """Whether WSL is usable and which distros (and versions) exist."""

    installed: bool = False
    version2: bool = False
    distros: tuple[WslDistro, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class ToolInfo:
    """A command the app runs, where it came from, and whether the file exists."""

    name: str = ""
    path: str = ""
    present: bool = False
    source: str = "missing"
    error: str | None = None


@dataclass(frozen=True)
class SystemReport:
    """Everything the setup assistant shows about the machine.  Failed probes carry an error."""

    os_name: str = ""
    os_version: str = ""
    machine: str = ""
    cpu_cores: int | None = None
    cpu_error: str | None = None
    ram_bytes: int | None = None
    ram_error: str | None = None
    models_dir: str = ""
    disk_free_bytes: int | None = None
    disk_total_bytes: int | None = None
    disk_error: str | None = None
    gpus: tuple[GpuAdapter, ...] = ()
    gpu_error: str | None = None
    nvidia: tuple[NvidiaGpu, ...] = ()
    nvidia_error: str | None = None
    wsl: WslState = field(default_factory=WslState)
    whisper_cli: ToolInfo = field(default_factory=ToolInfo)


@dataclass(frozen=True)
class Recommendation:
    """Plain recommendations for the setup assistant, each with its reason."""

    cpu_available: bool
    cpu_reason: str
    wsl_gpu: bool
    wsl_gpu_reason: str
    gpu_vendor: str | None
    whisper_backend: str             # "cublas" | "blas"
    whisper_backend_reason: str
    whisper_model: str               # "whisper-large-v3" | "whisper-large-v3-turbo"
    whisper_model_reason: str
    # Where separation and alignment should run: "cuda" | "directml" | "wsl" | "cpu".
    acceleration: str = "cpu"
    acceleration_reason: str = ""


@dataclass(frozen=True)
class WslEnvironment:
    """The result of probing one interpreter inside a distro."""

    distro: str
    python: str
    python_version: str = ""
    torch_version: str = ""
    gpu_available: bool = False
    device_name: str = ""
    backend: str = "cpu"             # rocm | cuda | cpu
    imports: dict[str, bool] = field(default_factory=dict)
    import_versions: dict[str, str] = field(default_factory=dict)
    import_errors: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    REQUIRED_IMPORTS = ("torch", "audio_separator", "torchaudio", "g2p_en", "nltk", "lyricloom")

    @property
    def missing_imports(self) -> tuple[str, ...]:
        return tuple(name for name in self.REQUIRED_IMPORTS if not self.imports.get(name))

    @property
    def passed(self) -> bool:
        """True only when the GPU works *and* every package a GPU worker imports is present."""
        return (self.error is None and self.gpu_available and self.backend in ("rocm", "cuda")
                and not self.missing_imports)


@dataclass(frozen=True)
class WslSetupResult:
    """What :func:`run_wsl_setup` produced (the streamed lines went to ``on_line``)."""

    ok: bool
    distro: str
    backend: str
    wheel: str
    returncode: int
    environments: tuple[WslEnvironment, ...] = ()
    environment: WslEnvironment | None = None
    details: dict = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class WhisperBackend:
    """One official whisper.cpp Windows zip, pinned by size and SHA-256."""

    name: str                        # "blas" or "cublas"; the folder is whisper-<name>
    label: str
    filename: str
    url: str
    size: int
    sha256: str
    description: str
    vendor: str = "any"              # "any" or "nvidia"


WHISPER_BACKENDS: tuple[WhisperBackend, ...] = (
    WhisperBackend(
        name="blas",
        label="whisper.cpp BLAS (faster CPU)",
        filename="whisper-blas-bin-x64.zip",
        url="https://github.com/ggml-org/whisper.cpp/releases/download/v1.9.2/"
            "whisper-blas-bin-x64.zip",
        size=20_981_386,
        sha256="ffe5b47ca8e53a7677949f23a9c4641bbec4eee8a5714c3d14b67bb8d7b24a78",
        description="The official whisper.cpp v1.9.2 Windows build with OpenBLAS. It speeds up "
                    "CPU transcription on every machine and needs no extra driver.",
    ),
    WhisperBackend(
        name="cublas",
        label="whisper.cpp cuBLAS (NVIDIA)",
        filename="whisper-cublas-12.4.0-bin-x64.zip",
        url="https://github.com/ggml-org/whisper.cpp/releases/download/v1.9.2/"
            "whisper-cublas-12.4.0-bin-x64.zip",
        size=670_611_449,
        sha256="443110ddaad70d4290ab2e77179e31cf712035bbc4fad56bb4519a90c917b39c",
        description="The official whisper.cpp v1.9.2 Windows build with CUDA 12.4 libraries. It "
                    "uses an NVIDIA GPU for transcription and needs a current NVIDIA driver.",
        vendor="nvidia",
    ),
)


def _backend(name: str) -> WhisperBackend:
    for backend in WHISPER_BACKENDS:
        if backend.name == name:
            return backend
    names = ", ".join(backend.name for backend in WHISPER_BACKENDS)
    raise ValueError(f"unknown whisper backend {name!r}; choose one of: {names}")


# --------------------------------------------------------------------------- decoding / errors


def _decode(data: bytes) -> str:
    """Decodes console output; Windows PowerShell/WSL use UTF-16 when their output is piped."""
    return config._decode_wsl_output(data)


def _describe(exc: BaseException) -> str:
    return error_text(exc)


def _attempt(call: Callable[[], object], default):
    """Runs one probe; a failure becomes ``(default, error text)`` instead of an exception."""
    try:
        return call(), None
    except Exception as exc:  # noqa: BLE001 - a report must always be printable
        log.debug("setup probe failed: %s", exc)
        return default, _describe(exc)


def _tail(data: bytes, limit: int = 1500) -> str:
    text = _decode(data).strip()
    return text[-limit:]


# --------------------------------------------------------------------------- machine probes


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _ram_bytes() -> int:
    """Total physical memory.  Windows uses GlobalMemoryStatusEx through ctypes."""
    if config.IS_WINDOWS:
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        function = kernel32.GlobalMemoryStatusEx
        function.argtypes = [ctypes.POINTER(_MemoryStatusEx)]
        function.restype = ctypes.c_int
        if not function(ctypes.byref(status)):
            raise OSError(ctypes.get_last_error(), "GlobalMemoryStatusEx failed")
        return int(status.ullTotalPhys)
    page_size = os.sysconf("SC_PAGE_SIZE")
    pages = os.sysconf("SC_PHYS_PAGES")
    return int(page_size) * int(pages)


def _disk_space(path: Path) -> tuple[int, int]:
    """Free/total bytes for the filesystem that holds ``path`` (or its nearest existing parent)."""
    candidate = Path(path)
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    usage = shutil.disk_usage(candidate)
    return int(usage.free), int(usage.total)


GPU_QUERY = [
    "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
    "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion | "
    "ConvertTo-Json",
]
NVIDIA_QUERY = [
    "nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader",
]


def _vendor(name: str) -> str:
    lowered = name.lower()
    if "nvidia" in lowered:
        return "nvidia"
    if "amd" in lowered or "radeon" in lowered or "advanced micro devices" in lowered or "ati " in lowered:
        return "amd"
    if "intel" in lowered:
        return "intel"
    return "other"


def _parse_gpu_adapters(data: bytes) -> tuple[GpuAdapter, ...]:
    """Parses the JSON from the Win32_VideoController query (one object or a list)."""
    text = _decode(data).strip()
    if not text:
        return ()
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"the GPU query returned invalid JSON: {exc}") from exc
    items = raw if isinstance(raw, list) else [raw]
    adapters: list[GpuAdapter] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or "").strip()
        if not name:
            continue
        raw_memory = item.get("AdapterRAM")
        try:
            memory = int(raw_memory) if raw_memory not in (None, "") else None
        except (TypeError, ValueError):
            memory = None
        adapters.append(GpuAdapter(
            name=name,
            vendor=_vendor(name),
            memory_bytes=memory,
            driver_version=str(item.get("DriverVersion") or "").strip(),
        ))
    return tuple(adapters)


def _memory_bytes(value: str) -> int | None:
    match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGTP]?i?B)?\s*$", value, re.IGNORECASE)
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "B").upper()
    exponents = {"B": 0, "KB": 1, "KIB": 1, "MB": 2, "MIB": 2, "GB": 3, "GIB": 3,
                 "TB": 4, "TIB": 4, "PB": 5, "PIB": 5}
    exponent = exponents.get(unit, 0)
    base = 1024 if "I" in unit or unit == "B" else 1000
    return int(number * (base ** exponent))


def _parse_nvidia_smi(data: bytes) -> tuple[NvidiaGpu, ...]:
    """Parses ``name, driver_version, memory.total`` CSV lines (the query has no header)."""
    gpus: list[NvidiaGpu] = []
    for line in _decode(data).splitlines():
        line = line.strip()
        if not line or "not found" in line.lower():
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            continue
        gpus.append(NvidiaGpu(
            name=parts[0] or "NVIDIA GPU",
            driver_version=parts[1],
            memory_bytes=_memory_bytes(parts[2]),
        ))
    return tuple(gpus)


def _parse_wsl_distros(data: bytes) -> tuple[WslDistro, ...]:
    """Parses ``wsl.exe -l -v``; the output is normally UTF-16 with a NAME/STATE/VERSION header."""
    distros: list[WslDistro] = []
    for raw_line in _decode(data).splitlines():
        line = raw_line.replace("\x00", "").strip().lstrip("\ufeff")
        if not line:
            continue
        default = line.startswith("*")
        if default:
            line = line[1:].strip()
        parts = line.split()
        if len(parts) < 3 or parts[0].upper() == "NAME":
            continue
        if not parts[-1].isdigit():
            continue
        distros.append(WslDistro(
            name=parts[0],
            state=" ".join(parts[1:-1]),
            version=int(parts[-1]),
            default=default,
        ))
    return tuple(distros)


def _probe_gpus(runner: Runner) -> tuple[GpuAdapter, ...]:
    if not config.IS_WINDOWS:
        return ()
    result = runner(GPU_QUERY, 15.0)
    if result.returncode != 0:
        raise RuntimeError(f"the Windows GPU query failed: {_tail(result.stderr) or 'no output'}")
    return _parse_gpu_adapters(result.stdout)


def _probe_nvidia(runner: Runner) -> tuple[NvidiaGpu, ...]:
    if shutil.which("nvidia-smi") is None:
        return ()
    result = runner(NVIDIA_QUERY, 10.0)
    if result.returncode != 0:
        raise RuntimeError(f"nvidia-smi failed: {_tail(result.stderr) or 'no output'}")
    return _parse_nvidia_smi(result.stdout)


def _wsl_answers_version(runner: Runner) -> bool:
    """True when ``wsl.exe --version`` succeeds: WSL is installed, in any display language."""
    try:
        return runner(["wsl.exe", "--version"], 10.0).returncode == 0
    except Exception:  # noqa: BLE001 - an old in-box WSL has no --version; treat it as unknown
        return False


def _probe_wsl(runner: Runner) -> WslState:
    if not config.IS_WINDOWS:
        return WslState(error="WSL is only available on Windows")
    if shutil.which("wsl.exe") is None:
        return WslState(error="wsl.exe was not found")
    try:
        result = runner(["wsl.exe", "-l", "-v"], 10.0)
    except Exception as exc:  # noqa: BLE001 - a report must always be printable
        return WslState(error=_describe(exc))
    distros = _parse_wsl_distros(result.stdout)
    if result.returncode != 0:
        text = (_decode(result.stdout) + "\n" + _decode(result.stderr)).lower()
        # wsl.exe answers in the Windows display language, so the English sentence only matches
        # on an English system.  ``wsl.exe --version`` succeeding means WSL itself is installed
        # and the failed listing is the "no distro yet" case, whatever the language.
        if ("no installed distributions" in text or "no distributions" in text
                or _wsl_answers_version(runner)):
            return WslState(installed=True, version2=False)
        detail = _tail(result.stderr) or _tail(result.stdout) or "no output"
        return WslState(installed=False, version2=False,
                        error=f"wsl.exe -l -v failed (exit code {result.returncode}): {detail}")
    return WslState(installed=True, version2=any(distro.version >= 2 for distro in distros),
                    distros=distros)


def _whisper_cli_source(path: Path) -> str:
    explicit = os.environ.get("LYRICLOOM_WHISPER_CLI")
    if explicit:
        try:
            if Path(explicit).expanduser().resolve() == path.resolve():
                return "environment"
        except OSError:
            pass
    chosen = config.setting("whisper_cli")
    if chosen:
        try:
            if Path(str(chosen)).expanduser().resolve() == path.resolve():
                return "setting"
        except OSError:
            pass
    roots = []
    if config.IS_FROZEN:
        roots.append(("bundled", Path(config.RESOURCE_ROOT) / "tools" / "bin"))
    else:
        roots.append(("checkout", Path(config.PROJECT_ROOT) / "tools" / "bin"))
    roots += [
        ("app-data", Path(config.APP_DATA) / "bin"),
        ("backend", Path(config.APP_DATA) / "backends"),
    ]
    for source, root in roots:
        try:
            path.resolve().relative_to(root.resolve())
            return source
        except (OSError, ValueError):
            continue
    if shutil.which(path.name):
        return "PATH"
    return "missing"


def _probe_whisper_cli() -> ToolInfo:
    try:
        path = config.whisper_cli()
        present = path.is_file()
    except Exception as exc:  # noqa: BLE001
        return ToolInfo(name="whisper-cli", error=_describe(exc))
    if present:
        return ToolInfo(name="whisper-cli", path=str(path), present=True,
                        source=_whisper_cli_source(path))
    return ToolInfo(name="whisper-cli", path=str(path), present=False,
                    source=_whisper_cli_source(path),
                    error=f"whisper-cli was not found at {path}")


def detect(runner: Runner | None = None) -> SystemReport:
    """Returns a :class:`SystemReport`; every probe has a timeout and no probe can raise."""
    run = runner or _run
    cpu = os.cpu_count()
    ram, ram_error = _attempt(_ram_bytes, None)
    disk, disk_error = _attempt(lambda: _disk_space(Path(config.MODELS)), (None, None))
    free, total = disk
    if config.IS_WINDOWS:
        gpus, gpu_error = _attempt(lambda: _probe_gpus(run), ())
    else:
        gpus, gpu_error = (), None
    nvidia, nvidia_error = _attempt(lambda: _probe_nvidia(run), ())
    try:
        wsl = _probe_wsl(run)
    except Exception as exc:  # noqa: BLE001
        wsl = WslState(error=_describe(exc))
    try:
        whisper = _probe_whisper_cli()
    except Exception as exc:  # noqa: BLE001
        whisper = ToolInfo(name="whisper-cli", error=_describe(exc))
    return SystemReport(
        os_name=f"{platform.system()} {platform.release()}".strip(),
        os_version=platform.version(),
        machine=platform.machine(),
        cpu_cores=cpu,
        cpu_error=None if cpu else "os.cpu_count() returned no value",
        ram_bytes=ram,
        ram_error=ram_error,
        models_dir=str(config.MODELS),
        disk_free_bytes=free,
        disk_total_bytes=total,
        disk_error=disk_error,
        gpus=gpus,
        gpu_error=gpu_error,
        nvidia=nvidia,
        nvidia_error=nvidia_error,
        wsl=wsl,
        whisper_cli=whisper,
    )


ACCELERATION_CHOICES = ("cuda", "directml", "wsl", "cpu")


def choose_acceleration(report: SystemReport) -> tuple[str, str]:
    """Where the assistant suggests running separation and alignment, and why.

    Returns ``(choice, reason)`` with ``choice`` one of :data:`ACCELERATION_CHOICES`.  The reason is
    one plain English sentence shown to a non-technical user under "Suggested setup"; the choice
    preselects the matching control on the Acceleration page.  Nothing is installed here.

    What the report offers: ``report.gpus`` (each with ``name``, ``vendor`` in nvidia/amd/intel/
    other and ``memory_bytes``), ``report.wsl.installed``/``.version2``, ``report.disk_free_bytes``
    (the drive the runtime is installed on) and ``report.ram_bytes``.  A CUDA runtime needs about
    8 GB of free disk; a DirectML one about 3 GB and only speeds up MDX-Net/VR separator models.
    """
    # TODO(human): decide the suggestion from the report.
    return "cpu", ("CPU processing needs no extra setup and runs on every machine.")


def recommend(report: SystemReport) -> Recommendation:
    """Turns a report into the assistant's plain recommendations, each explained in one sentence."""
    gpu = next((adapter for adapter in report.gpus if adapter.vendor in ("nvidia", "amd")), None)
    wsl_ready = bool(gpu and report.wsl.installed and report.wsl.version2)
    if wsl_ready:
        wsl_reason = (f"{gpu.name} and WSL 2 are available, so vocal separation and forced "
                      "alignment can run on the GPU inside WSL.")
    elif gpu:
        wsl_reason = (f"{gpu.name} was found, but WSL 2 is not ready; install WSL 2 to use the "
                      "GPU for separation and alignment.")
    else:
        wsl_reason = ("No NVIDIA or AMD GPU was found, so separation and alignment use the CPU; "
                      "the WSL GPU path is not offered.")
    nvidia = any(adapter.vendor == "nvidia" for adapter in report.gpus)
    if nvidia:
        backend = "cublas"
        backend_reason = ("An NVIDIA GPU was found, so the official cuBLAS whisper.cpp build can "
                          "use it for faster transcription.")
    else:
        backend = "blas"
        backend_reason = ("No NVIDIA GPU was found, so the official BLAS whisper.cpp build is the "
                          "fastest available transcription binary.")
    low_memory = report.ram_bytes is not None and report.ram_bytes < 12 * GiB
    few_cores = report.cpu_cores is not None and report.cpu_cores < 6
    if low_memory or few_cores:
        model = "whisper-large-v3-turbo"
        reason = ("The machine has less than 12 GB of RAM or fewer than 6 CPU cores, so the "
                  "smaller and faster large-v3-turbo model is recommended.")
    else:
        model = "whisper-large-v3"
        reason = ("With at least 12 GB of RAM and 6 CPU cores, the full large-v3 model gives the "
                  "best accuracy.")
    acceleration, acceleration_reason = choose_acceleration(report)
    return Recommendation(
        acceleration=acceleration,
        acceleration_reason=acceleration_reason,
        cpu_available=True,
        cpu_reason=("CPU processing needs no extra setup beyond downloading the Whisper model "
                    "and runs on every machine."),
        wsl_gpu=wsl_ready,
        wsl_gpu_reason=wsl_reason,
        gpu_vendor=gpu.vendor if gpu else None,
        whisper_backend=backend,
        whisper_backend_reason=backend_reason,
        whisper_model=model,
        whisper_model_reason=reason,
    )


# --------------------------------------------------------------------------- WSL environments


def _wsl_env_assignments() -> list[str]:
    env = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", **config._wsl_env()}
    return [f"{key}={value}" for key, value in env.items()]


def _probe_script() -> bytes:
    path = Path(__file__).resolve().with_name("workers") / "probe_gpu.py"
    try:
        return path.read_bytes()
    except OSError as exc:
        raise SetupError(f"the WSL GPU probe is missing from this installation: {path}") from exc


def _list_wsl_pythons(distro: str, runner: Runner) -> list[str]:
    """The one allowed ``sh -c``: a fixed glob, never a caller-provided command."""
    argv = ["wsl.exe", "-d", distro, "--", "sh", "-c", "ls -1 /opt/*/bin/python 2>/dev/null"]
    try:
        result = runner(argv, 20.0)
    except WorkerCancelled:
        raise
    except Exception as exc:  # noqa: BLE001 - the standard locations are still probed
        log.debug("could not list /opt interpreters in WSL distro %s: %s", distro, exc)
        return []
    if result.returncode != 0:
        return []
    paths: list[str] = []
    for line in _decode(result.stdout).splitlines():
        value = line.strip().replace("\x00", "")
        if value.startswith("/") and value.endswith("/bin/python") and ".." not in value:
            paths.append(value)
    return paths


def _parse_wsl_probe(distro: str, python: str, data: bytes) -> WslEnvironment | None:
    for line in reversed(_decode(data).splitlines()):
        if not line.startswith(PROBE_MARK):
            continue
        try:
            payload = json.loads(line[len(PROBE_MARK):])
        except ValueError as exc:
            return WslEnvironment(distro=distro, python=python,
                                  error=f"the WSL probe returned invalid JSON: {exc}")
        if not isinstance(payload, dict):
            return WslEnvironment(distro=distro, python=python,
                                  error="the WSL probe returned an unexpected result")
        raw_imports = payload.get("imports")
        raw_versions = payload.get("import_versions")
        raw_errors = payload.get("import_errors")
        imports = ({str(key): bool(value) for key, value in raw_imports.items()}
                   if isinstance(raw_imports, dict) else {})
        versions = ({str(key): str(value) for key, value in raw_versions.items()}
                    if isinstance(raw_versions, dict) else {})
        errors = ({str(key): str(value) for key, value in raw_errors.items()}
                  if isinstance(raw_errors, dict) else {})
        return WslEnvironment(
            distro=distro,
            python=str(payload.get("python") or python),
            python_version=str(payload.get("python_version") or ""),
            torch_version=str(payload.get("torch_version") or ""),
            gpu_available=bool(payload.get("gpu_available")),
            device_name=str(payload.get("device_name") or ""),
            backend=str(payload.get("backend") or "cpu"),
            imports=imports,
            import_versions=versions,
            import_errors=errors,
            error=str(payload.get("error") or "") or None,
        )
    return None


def _unique_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for path in paths:
        value = str(path).strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def find_wsl_environments(distro: str, *, runner: Runner | None = None,
                          cancel: threading.Event | None = None) -> list[WslEnvironment]:
    """Probes every likely interpreter inside ``distro``.

    Candidates, in order: the configured ``wsl_python``, ``/opt/lyricloom/venv/bin/python`` and
    every ``/opt/*/bin/python``.  The probe is sent on stdin to ``<python> -`` so the distro does
    not need the LyricLoom package importable.  A failed candidate is returned with ``error`` set
    instead of raising.
    """
    if not distro or not config.IS_WINDOWS:
        return []
    run = runner or _run
    configured = str(config.setting("wsl_python") or "").strip()
    candidates = [configured or "python3", WSL_VENV_PYTHON]
    candidates.extend(_list_wsl_pythons(distro, run))
    script = _probe_script()
    environments: list[WslEnvironment] = []
    for python in _unique_paths(candidates):
        argv = ["wsl.exe", "-d", distro, "--exec", "env", *_wsl_env_assignments(), python, "-"]
        try:
            result = run(argv, WSL_PROBE_TIMEOUT_S, input_bytes=script, cancel=cancel)
        except WorkerCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - one broken interpreter must not hide the others
            log.info("WSL probe failed for %s in %s: %s", python, distro, exc)
            environments.append(WslEnvironment(distro=distro, python=python,
                                               error=_describe(exc)))
            continue
        environment = _parse_wsl_probe(distro, python, result.stdout)
        if environment is None:
            detail = _tail(result.stderr) or _tail(result.stdout) or "no output"
            environments.append(WslEnvironment(
                distro=distro, python=python,
                error=f"the WSL probe did not return a result: {detail}"))
            continue
        if result.returncode != 0 and environment.error is None:
            detail = _tail(result.stderr) or "the probe exited with a failure"
            environment = replace(environment, error=detail)
        environments.append(environment)
    return environments


def use_wsl_environment(environment: WslEnvironment) -> bool:
    """Stores ``wsl_gpu``, ``wsl_distro`` and ``wsl_python`` only when the probe passed.

    ``wsl_env`` and ``wsl_hsa_override`` belong to the user and are kept untouched.  Returns True
    when the settings were written.
    """
    if not environment.passed:
        return False
    config.update_settings({
        "wsl_gpu": True,
        "wsl_distro": environment.distro,
        "wsl_python": environment.python,
        # One choice is in effect at a time: the Windows GPU runtime is deselected, not removed.
        "gpu_backend": "",
        "gpu_python": "",
    })
    return True


def _parse_setup_json(data: bytes) -> dict | None:
    lines = [line for line in _decode(data).splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith(SETUP_RESULT_MARK):
            try:
                payload = json.loads(line[len(SETUP_RESULT_MARK):])
            except ValueError:
                return None
            return payload if isinstance(payload, dict) else None
    if lines:
        try:
            payload = json.loads(lines[-1])
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None
    return None


def run_wsl_setup(distro: str, backend: str, wheel: Path,
                  on_line: Callable[[str], None] | None = None,
                  cancel: threading.Event | None = None, *,
                  runner: Runner | None = None,
                  stream: Callable[..., subprocess.CompletedProcess] | None = None
                  ) -> WslSetupResult:
    """Runs the WSL setup script with streamed lines, then probes the new environment.

    The script itself uses ``sudo`` only for ``apt``; this function starts no elevated process.
    ``wheel`` must be the path returned by :func:`bundled_wsl_files`.  ``on_line`` receives each
    stdout/stderr line as it arrives (including the ``@@step`` and final JSON lines).
    """
    if backend not in ("rocm", "cuda", "cpu"):
        raise ValueError(f"unknown WSL backend {backend!r}; choose rocm, cuda or cpu")
    wheel = Path(wheel)
    if not wheel.is_file():
        raise FileNotFoundError(
            f"the LyricLoom wheel passed to the WSL setup does not exist: {wheel}")
    wheel = wheel.resolve()
    script, _bundled_wheel = bundled_wsl_files()
    try:
        script_bytes = script.read_bytes()
    except OSError as exc:
        raise SetupError(f"cannot read the WSL setup script: {script}: {exc}") from exc
    argv = ["wsl.exe", "-d", distro, "--exec", "env", *_wsl_env_assignments(),
            "bash", "-s", "--", "--backend", backend, "--wheel", wsl_path(wheel)]
    execute = stream or run_process_stream
    proc = execute(argv, input_bytes=script_bytes, timeout_s=WSL_SETUP_TIMEOUT_S,
                   cancel=cancel, on_line=on_line)
    details = _parse_setup_json(proc.stdout)
    environments = tuple(find_wsl_environments(distro, runner=runner, cancel=cancel))
    target = next((env for env in environments if env.python == WSL_VENV_PYTHON), None)
    if target is None:
        target = next((env for env in environments if env.passed), None)
    if backend == "cpu":
        usable = (target is not None and target.error is None and not target.missing_imports)
    else:
        usable = target is not None and target.passed
    ok = proc.returncode == 0 and usable
    error: str | None = None
    if proc.returncode != 0:
        detail = _tail(proc.stderr) or _tail(proc.stdout) or "no output"
        error = f"the WSL setup script failed (exit code {proc.returncode}): {detail}"
    elif not ok:
        if target is None:
            error = "the setup script finished, but no WSL environment was found"
        elif target.error:
            error = f"the setup script finished, but the probe failed: {target.error}"
        else:
            missing = ", ".join(target.missing_imports) or "GPU support"
            error = f"the setup script finished, but the environment is missing: {missing}"
    return WslSetupResult(
        ok=ok,
        distro=distro,
        backend=backend,
        wheel=str(wheel),
        returncode=proc.returncode,
        environments=environments,
        environment=target,
        details=details or {},
        error=error,
    )


def wsl_install_command() -> list[str]:
    """The elevated command the GUI may start after the user clicks; this module never runs it."""
    return ["wsl.exe", "--install", "-d", WSL_DISTRO]


def bundled_wsl_files() -> tuple[Path, Path | None]:
    """The setup script and, in a frozen Windows build, the LyricLoom wheel next to it.

    A source checkout never builds anything here, so the wheel is ``None`` and the GUI explains
    that only an installed build can set up WSL for the user.
    """
    if config.IS_FROZEN:
        base = Path(config.RESOURCE_ROOT) / "wsl"
        script = base / WSL_SCRIPT_NAME
        wheels = sorted(base.glob("lyricloom-*.whl"))
        wheel = wheels[-1] if wheels else None
        if not script.is_file():
            raise FileNotFoundError(
                f"the WSL setup script is missing from this installation: {script}")
        return script, wheel
    return Path(config.PROJECT_ROOT) / "packaging" / "wsl" / WSL_SCRIPT_NAME, None


# --------------------------------------------------------------------------- whisper backends


def _extract_zip(archive: Path, target: Path) -> None:
    """Extracts ``archive`` into ``target``, refusing every zip-slip path and symlink."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    base = target.resolve()
    try:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
                    raise BackendError(f"the backend archive contains an absolute path: {info.filename}")
                parts = [part for part in PurePosixPath(name).parts if part not in ("", ".")]
                if any(part == ".." for part in parts):
                    raise BackendError(f"the backend archive escapes its folder: {info.filename}")
                if not parts:
                    continue
                destination = base.joinpath(*parts)
                try:
                    destination.relative_to(base)
                except ValueError as exc:
                    raise BackendError(
                        f"the backend archive escapes its folder: {info.filename}") from exc
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise BackendError(f"the backend archive contains a symlink: {info.filename}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except zipfile.BadZipFile as exc:
        raise BackendError(f"the backend archive is not a valid zip file: {archive.name}") from exc


def _is_within(path: Path, root: Path) -> bool:
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False


def install_whisper_backend(name: str, progress: Callable[[int, int], None] | None = None,
                            cancel: threading.Event | None = None, *,
                            download: Downloader | None = None,
                            runner: Runner | None = None) -> Path:
    """Installs an official whisper.cpp Windows build and points ``whisper_cli`` at it.

    The zip is downloaded with the pinned size/SHA-256 through
    :func:`lyricloom.downloads.download_verified`, extracted zip-slip safely to
    ``<data>/backends/whisper-<name>/``, and only stored in the setting after
    ``whisper-cli.exe --help`` runs.  Returns the installed ``whisper-cli.exe`` path.
    """
    backend = _backend(name)
    fetch = download or downloads.download_verified
    run = runner or _run
    data = Path(config.APP_DATA)
    archive = data / "backends" / "downloads" / backend.filename
    stage = data / "backends" / f".whisper-{backend.name}.installing"
    target = data / "backends" / f"whisper-{backend.name}"
    fetch(backend, archive, progress=progress, cancel=cancel)
    try:
        if stage.exists():
            shutil.rmtree(stage)
        _extract_zip(archive, stage)
        candidates = [path for path in stage.rglob("whisper-cli.exe") if path.is_file()]
        if not candidates:
            raise BackendError(
                f"the {backend.label} archive does not contain whisper-cli.exe")
        cli = candidates[0]
        result = run([str(cli), "--help"], WHISPER_HELP_TIMEOUT_S, cancel=cancel)
        if result.returncode != 0:
            detail = _tail(result.stderr) or _tail(result.stdout) or "no output"
            raise BackendError(
                f"{backend.label} did not run on this machine (whisper-cli.exe --help failed): "
                f"{detail}")
        if target.exists():
            shutil.rmtree(target)
        os.replace(stage, target)
        installed = target / cli.relative_to(stage)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    config.set_setting("whisper_cli", str(installed))
    return installed


def remove_whisper_backend(name: str) -> bool:
    """Removes an installed backend folder; clears ``whisper_cli`` if that backend was selected."""
    backend = _backend(name)
    data = Path(config.APP_DATA)
    target = data / "backends" / f"whisper-{backend.name}"
    removed = False
    if target.exists():
        shutil.rmtree(target)
        removed = True
    archive = data / "backends" / "downloads" / backend.filename
    try:
        archive.unlink()
        removed = True
    except OSError:
        pass
    chosen = str(config.setting("whisper_cli") or "")
    if chosen and _is_within(Path(chosen), target):
        config.set_setting("whisper_cli", "")
    return removed


def use_bundled_whisper() -> Path:
    """Clears the ``whisper_cli`` setting so the bundled/checkout binary is used again."""
    config.set_setting("whisper_cli", "")
    return config.whisper_cli()


__all__ = [
    "ACCELERATION_CHOICES",
    "BackendError",
    "CommandResult",
    "GpuAdapter",
    "NvidiaGpu",
    "PROBE_MARK",
    "Recommendation",
    "SETUP_RESULT_MARK",
    "SetupError",
    "SystemReport",
    "ToolInfo",
    "WHISPER_BACKENDS",
    "WHISPER_CPP_VERSION",
    "WhisperBackend",
    "WslDistro",
    "WslEnvironment",
    "WslSetupResult",
    "WslState",
    "bundled_wsl_files",
    "choose_acceleration",
    "detect",
    "find_wsl_environments",
    "install_whisper_backend",
    "recommend",
    "remove_whisper_backend",
    "run_wsl_setup",
    "use_bundled_whisper",
    "use_wsl_environment",
    "wsl_install_command",
]
