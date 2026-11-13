"""A GPU build of PyTorch for Windows, set up on request and kept outside the installation.

The packaged app carries a CPU-only torch: PyInstaller freezes its DLLs into the bundle, so a CUDA
build cannot be swapped in, and a CUDA installer would be larger than a release asset may be.
Instead the heavy stages can run in a separate Python environment, exactly as the WSL path does:

* :func:`install` downloads `uv <https://github.com/astral-sh/uv>`_ (pinned by size and SHA-256),
  creates a Python 3.11 environment in ``<data>/runtimes/<backend>`` and installs the matching
  torch build and audio-separator into it.
* :func:`probe` runs a real operation on the GPU from that environment.
* :func:`use` stores ``gpu_backend``/``gpu_python``, but only for an environment that passed.

LyricLoom itself is never installed into the environment.  The workers are imported from the
running app's own copy (:func:`package_source`), so an app update can never leave a stale worker
behind.  Nothing here imports Qt, elevates privileges or downloads without being called, and every
external command goes through an injectable callable so the tests need no network and no GPU.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import config, downloads
from .errtext import error_text
from .workers import run_process, run_process_stream
from .workers.probe_gpu import RESULT_MARK as PROBE_MARK

log = logging.getLogger(__name__)

GiB = 1024 ** 3
PYTHON_VERSION = "3.11"
STEP_TIMEOUT_S = 7200.0          # a 2.5 GB wheel on a slow line
PROBE_TIMEOUT_S = 300.0          # the first CUDA import on a cold disk is slow
UV_VERSION = "0.13.8"
AUDIO_SEPARATOR = "0.47.1"       # the release the separator worker is tested against (pyproject.toml)
TOTAL_STEPS = 5


class GpuRuntimeError(RuntimeError):
    """A runtime step could not be completed; the message is meant for the user."""


class GpuRuntimeMissing(OSError):
    """The selected runtime's interpreter is gone (the folder was deleted or moved)."""


@dataclass(frozen=True)
class UvRelease:
    """The official uv Windows zip, pinned like every other download."""

    filename: str
    url: str
    size: int
    sha256: str


UV = UvRelease(
    filename="uv-x86_64-pc-windows-msvc.zip",
    url=f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/"
        "uv-x86_64-pc-windows-msvc.zip",
    size=15_529_884,
    sha256="529e78a9cec6cd7e3e014f7ecd8bda0c113969d4ed0f2efeedb85c30943325b8",
)


@dataclass(frozen=True)
class RuntimePlan:
    """What one backend installs, and what it needs from the machine."""

    backend: str                       # "cuda" | "directml"
    label: str
    torch_index: str                   # "" means PyPI
    torch_packages: tuple[str, ...]
    packages: tuple[str, ...]
    required_imports: tuple[str, ...]
    download_bytes: int                # approximate, for the text beside the button
    disk_bytes: int                    # free space required before starting
    note: str


_CUDA_NOTE = ("Runs vocal separation and both alignment models on an NVIDIA GPU. Needs only a "
              "current NVIDIA driver; the CUDA libraries come with PyTorch.")
_DIRECTML_NOTE = ("Experimental. DirectML speeds up MDX-Net and VR separator models on AMD, Intel "
                  "and NVIDIA GPUs. RoFormer models (including the suggested one) and both "
                  "alignment models keep running on the CPU.")
_GPU_IMPORTS = ("torch", "torchaudio", "audio_separator", "g2p_en", "nltk", "lyricloom")


def _is_rtx_50(gpu_name: str) -> bool:
    """RTX 50-series (Blackwell) cards need CUDA 12.8 kernels; older torch builds cannot run."""
    # The GeForce models are 5050 to 5090.  "RTX 5000" is an older workstation card (Turing or
    # Ada) and must not match; the workstation Blackwell cards carry the word in their name.
    name = gpu_name.upper()
    return bool(re.search(r"\bRTX\s*50[5-9]0\b", name)) or "BLACKWELL" in name


def plan_for(backend: str, gpu_name: str = "") -> RuntimePlan:
    """The install plan for ``backend``; ``gpu_name`` picks the CUDA build the card can run."""
    if backend == "cuda":
        if _is_rtx_50(gpu_name):
            torch, index, label = "2.7.1", "https://download.pytorch.org/whl/cu128", "CUDA 12.8"
        else:
            torch, index, label = "2.5.1", "https://download.pytorch.org/whl/cu124", "CUDA 12.4"
        return RuntimePlan(
            backend="cuda", label=f"NVIDIA GPU ({label}, PyTorch {torch})", torch_index=index,
            torch_packages=(f"torch=={torch}", f"torchaudio=={torch}"),
            packages=(f"audio-separator[gpu]=={AUDIO_SEPARATOR}", "g2p_en", "nltk"),
            required_imports=_GPU_IMPORTS,
            download_bytes=int(3.2 * GiB), disk_bytes=8 * GiB, note=_CUDA_NOTE)
    if backend == "directml":
        return RuntimePlan(
            backend="directml", label="DirectML (PyTorch 2.4.1)", torch_index="",
            torch_packages=("torch==2.4.1", "torchaudio==2.4.1"),
            packages=(f"audio-separator[dml]=={AUDIO_SEPARATOR}",),
            required_imports=("torch", "audio_separator", "lyricloom"),
            download_bytes=int(0.6 * GiB), disk_bytes=3 * GiB, note=_DIRECTML_NOTE)
    raise ValueError(f"unknown GPU backend {backend!r}; choose one of: "
                     + ", ".join(config.GPU_BACKENDS))


@dataclass(frozen=True)
class RuntimeEnvironment:
    """The result of probing one interpreter of a Windows runtime."""

    python: str
    python_version: str = ""
    torch_version: str = ""
    gpu_available: bool = False
    device_name: str = ""
    backend: str = "cpu"               # cuda | directml | cpu
    smoke_error: str | None = None
    imports: dict[str, bool] = field(default_factory=dict)
    import_errors: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    def missing_imports(self, backend: str) -> tuple[str, ...]:
        return tuple(name for name in plan_for(backend).required_imports
                     if not self.imports.get(name))

    def passed_for(self, backend: str) -> bool:
        """True only when this environment really ran an operation on a ``backend`` device and has
        every package the workers import."""
        return (self.error is None and self.gpu_available and self.backend == backend
                and self.smoke_error is None and not self.missing_imports(backend))

    def problem(self, backend: str) -> str:
        """One sentence on why the environment did not pass (empty when it did)."""
        if self.error:
            return self.error
        missing = self.missing_imports(backend)
        if missing:
            detail = "; ".join(f"{name}: {self.import_errors[name]}"
                               for name in missing if name in self.import_errors)
            return "missing packages: " + ", ".join(missing) + (f" ({detail})" if detail else "")
        if not self.gpu_available or self.backend != backend:
            if backend == "cuda":
                return ("PyTorch found no CUDA device. Install or update the NVIDIA driver, then "
                        "set the runtime up again.")
            return "DirectML found no usable graphics adapter."
        if self.smoke_error:
            return f"the GPU refused a test operation: {self.smoke_error}"
        return ""


@dataclass(frozen=True)
class RuntimeResult:
    """What :func:`install` produced (the streamed lines went to ``on_line``)."""

    ok: bool
    backend: str
    python: str
    environment: RuntimeEnvironment | None = None
    error: str | None = None


# ``stream(argv, *, timeout_s, env, cancel, on_line) -> CompletedProcess``: tests pass a fake.
Stream = Callable[..., subprocess.CompletedProcess]
# ``runner(argv, timeout_s, *, input_bytes, env, cwd, cancel) -> CompletedProcess``.
Runner = Callable[..., subprocess.CompletedProcess]
# ``download(spec, dest, progress=..., cancel=...) -> Path``.
Downloader = Callable[..., Path]


def _run(argv: list[str], timeout_s: float, *, input_bytes: bytes = b"", env: dict | None = None,
         cwd: Path | None = None, cancel: threading.Event | None = None
         ) -> subprocess.CompletedProcess:
    return run_process(argv, input_bytes=input_bytes, timeout_s=timeout_s, env=env, cwd=cwd,
                       cancel=cancel)


# --------------------------------------------------------------------------- locations


def runtime_dir(backend: str) -> Path:
    if backend not in config.GPU_BACKENDS:
        raise ValueError(f"unknown GPU backend {backend!r}")
    return Path(config.RUNTIMES) / backend


def python_path(backend: str) -> Path:
    return runtime_dir(backend) / "Scripts" / "python.exe"


def installed(backend: str) -> bool:
    """Whether the environment of ``backend`` exists (it may still fail a probe)."""
    return python_path(backend).is_file()


def uv_path() -> Path:
    return Path(config.RUNTIMES) / "uv" / UV_VERSION / "uv.exe"


def package_source() -> Path | None:
    """Where a runtime imports ``lyricloom`` from: the running app's own copy.

    A packaged build bundles a wheel of exactly its version (a wheel of pure Python is importable
    as a zip); a source checkout is its own source.  None means a packaged build without the
    wheel, which cannot run a runtime."""
    if config.IS_FROZEN:
        wheels = sorted((Path(config.RESOURCE_ROOT) / "wsl").glob("lyricloom-*.whl"))
        return wheels[-1] if wheels else None
    return Path(config.PROJECT_ROOT)


def worker_env() -> dict[str, str]:
    """Variables for a worker (or probe) started with a runtime's interpreter."""
    env = {"PYTHONNOUSERSITE": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    source = package_source()
    if source is not None:
        env["PYTHONPATH"] = str(source)
    return env


def worker_python(python: str) -> str:
    """``python`` when it still exists; a stage catches the error and uses the CPU instead."""
    if not Path(python).is_file():
        raise GpuRuntimeMissing(
            f"the Windows GPU runtime is missing ({python}); set it up again in "
            "Help > Setup assistant > Acceleration")
    return python


def _uv_env() -> dict[str, str]:
    """uv keeps its Python and its cache inside LyricLoom's folder and ignores the user's own uv
    configuration, so removing the data folder removes everything this module created."""
    root = Path(config.RUNTIMES)
    return {**os.environ,
            "UV_CACHE_DIR": str(root / "cache"),
            "UV_PYTHON_INSTALL_DIR": str(root / "python"),
            "UV_MANAGED_PYTHON": "1",
            "UV_NO_CONFIG": "1",
            "UV_NO_PROGRESS": "1",
            "UV_HTTP_TIMEOUT": "300",
            "NO_COLOR": "1",
            "PYTHONUTF8": "1"}


# --------------------------------------------------------------------------- uv


def _extract_uv(archive: Path, target: Path) -> Path:
    """Extracts ``uv.exe`` (and only executables at the archive root) from the pinned zip."""
    target.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as bundle:
            names = [info for info in bundle.infolist()
                     if not info.is_dir() and Path(info.filename).name == info.filename
                     and info.filename.lower().endswith(".exe")]
            if not any(info.filename.lower() == "uv.exe" for info in names):
                raise GpuRuntimeError(f"{archive.name} does not contain uv.exe")
            for info in names:
                part = target / (info.filename + ".part")
                with bundle.open(info) as source, part.open("wb") as output:
                    shutil.copyfileobj(source, output)
                os.replace(part, target / info.filename)
    except zipfile.BadZipFile as exc:
        raise GpuRuntimeError(f"{archive.name} is not a valid zip file") from exc
    return target / "uv.exe"


def ensure_uv(progress: Callable[[int, int], None] | None = None,
              cancel: threading.Event | None = None, *,
              download: Downloader | None = None) -> Path:
    """Returns ``uv.exe``, downloading the pinned release once."""
    exe = uv_path()
    if exe.is_file():
        return exe
    fetch = download or downloads.download_verified
    archive = Path(config.RUNTIMES) / "downloads" / UV.filename
    fetch(UV, archive, progress=progress, cancel=cancel)
    return _extract_uv(archive, exe.parent)


# --------------------------------------------------------------------------- probe


def _parse_probe(python: str, data: bytes) -> RuntimeEnvironment | None:
    for line in reversed(data.decode("utf-8", "replace").splitlines()):
        if not line.startswith(PROBE_MARK):
            continue
        try:
            payload = json.loads(line[len(PROBE_MARK):])
        except ValueError as exc:
            return RuntimeEnvironment(python=python,
                                      error=f"the GPU probe returned invalid JSON: {exc}")
        if not isinstance(payload, dict):
            return RuntimeEnvironment(python=python,
                                      error="the GPU probe returned an unexpected result")
        raw_imports = payload.get("imports")
        raw_errors = payload.get("import_errors")
        return RuntimeEnvironment(
            python=python,
            python_version=str(payload.get("python_version") or ""),
            torch_version=str(payload.get("torch_version") or ""),
            gpu_available=bool(payload.get("gpu_available")),
            device_name=str(payload.get("device_name") or ""),
            backend=str(payload.get("backend") or "cpu"),
            smoke_error=str(payload.get("smoke_error") or "") or None,
            imports=({str(k): bool(v) for k, v in raw_imports.items()}
                     if isinstance(raw_imports, dict) else {}),
            import_errors=({str(k): str(v) for k, v in raw_errors.items()}
                           if isinstance(raw_errors, dict) else {}),
            error=str(payload.get("error") or "") or None,
        )
    return None


def _probe_script() -> bytes:
    # A packaged build ships the probe as a real file next to the frozen package (see the spec).
    path = Path(__file__).resolve().with_name("workers") / "probe_gpu.py"
    try:
        return path.read_bytes()
    except OSError as exc:
        raise GpuRuntimeError(f"the GPU probe is missing from this installation: {path}") from exc


def probe(python: Path | str, *, runner: Runner | None = None,
          cancel: threading.Event | None = None) -> RuntimeEnvironment:
    """Runs the GPU probe with ``python``; a failure is returned as ``error``, never raised
    (except a cancellation)."""
    from .workers import WorkerCancelled

    python = str(python)
    run = runner or _run
    cwd = Path(config.APP_DATA if config.IS_FROZEN else config.PROJECT_ROOT)
    cwd.mkdir(parents=True, exist_ok=True)
    try:
        result = run([python, "-"], PROBE_TIMEOUT_S, input_bytes=_probe_script(),
                     env={**os.environ, **worker_env()}, cwd=cwd, cancel=cancel)
    except WorkerCancelled:
        raise
    except Exception as exc:  # noqa: BLE001 - a broken interpreter is a reported failure
        return RuntimeEnvironment(python=python, error=error_text(exc))
    environment = _parse_probe(python, result.stdout or b"")
    if environment is None:
        detail = _tail(result.stderr) or _tail(result.stdout) or "no output"
        return RuntimeEnvironment(python=python,
                                  error=f"the GPU probe did not return a result: {detail}")
    return environment


def _tail(data: bytes | None, limit: int = 1500) -> str:
    return (data or b"").decode("utf-8", "replace").strip()[-limit:]


# --------------------------------------------------------------------------- install


def _check_disk(plan: RuntimePlan) -> None:
    root = Path(config.RUNTIMES)
    candidate = root
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    try:
        free = shutil.disk_usage(candidate).free
    except OSError:
        return   # an unreadable volume is reported by the first step that writes to it
    if free < plan.disk_bytes:
        raise GpuRuntimeError(
            f"Not enough free disk space for the {plan.label} runtime: it needs about "
            f"{plan.disk_bytes / GiB:.0f} GB in {root} and {free / GiB:.1f} GB are free.")


def install(backend: str, gpu_name: str = "",
            on_line: Callable[[str], None] | None = None,
            cancel: threading.Event | None = None, *,
            download: Downloader | None = None, stream: Stream | None = None,
            runner: Runner | None = None) -> RuntimeResult:
    """Builds (or repairs) the environment of ``backend`` and probes it.

    Each step is announced as ``@@step <n>/<total> <text>`` on ``on_line``, followed by the lines
    uv prints.  A failing step stops the run and is returned as ``error``; a cancellation raises
    :class:`lyricloom.workers.WorkerCancelled`.  No setting is written here: the caller passes the
    returned environment to :func:`use`.  An interrupted run is resumed by calling this again,
    because uv keeps what it already downloaded.
    """
    plan = plan_for(backend, gpu_name)
    if not config.IS_WINDOWS:
        raise GpuRuntimeError("the Windows GPU runtime is only available on Windows")
    if package_source() is None:
        raise GpuRuntimeError("this build does not include the LyricLoom wheel the GPU runtime "
                            "imports; reinstall LyricLoom from the official installer")
    _check_disk(plan)
    emit = on_line or (lambda _line: None)
    execute = stream or run_process_stream
    target = runtime_dir(backend)
    python = python_path(backend)
    env = _uv_env()

    def step(number: int, text: str) -> None:
        emit(f"@@step {number}/{TOTAL_STEPS} {text}")

    def uv_step(number: int, text: str, arguments: list[str]) -> str | None:
        step(number, text)
        proc = execute([str(uv), *arguments], timeout_s=STEP_TIMEOUT_S, env=env, cancel=cancel,
                       on_line=emit)
        if proc.returncode == 0:
            return None
        detail = _tail(proc.stderr) or _tail(proc.stdout) or "no output"
        return f"{text} failed (exit code {proc.returncode}): {detail}"

    def failed(error: str) -> RuntimeResult:
        return RuntimeResult(ok=False, backend=backend, python=str(python), error=error)

    step(1, f"Downloading the uv package installer {UV_VERSION}")
    uv = ensure_uv(cancel=cancel, download=download)

    error = uv_step(2, f"Creating the Python {PYTHON_VERSION} environment",
                    ["venv", "--python", PYTHON_VERSION, "--allow-existing", str(target)])
    if error:
        return failed(error)

    index = ["--default-index", plan.torch_index] if plan.torch_index else []
    error = uv_step(3, f"Installing PyTorch for {plan.label}",
                    ["pip", "install", "--python", str(python), *index, *plan.torch_packages])
    if error:
        return failed(error)

    error = uv_step(4, "Installing audio-separator and its packages",
                    ["pip", "install", "--python", str(python), *plan.packages])
    if error:
        return failed(error)

    step(5, "Testing the GPU from the new environment")
    environment = probe(python, runner=runner, cancel=cancel)
    if not environment.passed_for(backend):
        return RuntimeResult(ok=False, backend=backend, python=str(python),
                             environment=environment,
                             error="The environment was installed, but it cannot be used: "
                                   + environment.problem(backend))
    emit(f"{environment.device_name} is ready (PyTorch {environment.torch_version}).")
    # The unpacked packages are hard-linked into the environment; the cache only costs space now.
    shutil.rmtree(Path(config.RUNTIMES) / "cache", ignore_errors=True)
    return RuntimeResult(ok=True, backend=backend, python=str(python), environment=environment)


# --------------------------------------------------------------------------- settings


def use(environment: RuntimeEnvironment, backend: str) -> bool:
    """Selects a runtime, but only one that passed its probe.

    The WSL path is turned off with it: one choice is in effect at a time, and the Windows runtime
    is read at the start of every stage, so no restart is needed.  Returns True when the settings
    were written."""
    if not environment.passed_for(backend):
        return False
    config.update_settings({"gpu_backend": backend, "gpu_python": environment.python,
                            "wsl_gpu": False})
    return True


def disable() -> None:
    """Back to the CPU; an installed environment is kept for later."""
    config.update_settings({"gpu_backend": "", "gpu_python": ""})


def selected() -> str:
    """The backend in effect ("" when the CPU or WSL is used)."""
    runtime = config.gpu_runtime()
    return runtime[0] if runtime else ""


BACKEND_NAMES = {"cuda": "NVIDIA GPU on Windows (CUDA)", "directml": "DirectML on Windows"}


def acceleration_text() -> str:
    """One line on where separation and alignment run now, for Settings and the summaries."""
    runtime = config.gpu_runtime()
    if runtime is not None:
        backend, python = runtime
        text = BACKEND_NAMES[backend]
        if backend == "directml":
            text += " (MDX-Net and VR separator models; everything else on the CPU)"
        if not Path(python).is_file():
            text += " — the runtime is missing, so the CPU is used"
        return text
    if config.setting("wsl_gpu", False):
        return (f"WSL {config.setting('wsl_distro') or 'auto'} · "
                f"{config.setting('wsl_python') or 'python3'}")
    return "CPU only"


def remove(backend: str) -> bool:
    """Deletes the environment of ``backend`` and deselects it; True when something was deleted.

    The shared uv program, its Python and its cache go too once no environment is left."""
    target = runtime_dir(backend)
    was_selected = selected() == backend
    removed = target.exists()
    if removed:
        shutil.rmtree(target)
    if was_selected:
        disable()
    root = Path(config.RUNTIMES)
    if not any(installed(name) for name in config.GPU_BACKENDS):
        for name in ("cache", "python", "uv", "downloads"):
            shutil.rmtree(root / name, ignore_errors=True)
    return removed


__all__ = [
    "BACKEND_NAMES",
    "acceleration_text",
    "RuntimeEnvironment",
    "GpuRuntimeError",
    "GpuRuntimeMissing",
    "RuntimePlan",
    "RuntimeResult",
    "TOTAL_STEPS",
    "UV",
    "UV_VERSION",
    "disable",
    "ensure_uv",
    "install",
    "installed",
    "package_source",
    "plan_for",
    "probe",
    "python_path",
    "remove",
    "runtime_dir",
    "selected",
    "use",
    "uv_path",
    "worker_env",
    "worker_python",
]
