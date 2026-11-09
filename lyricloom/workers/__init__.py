"""GPU stages run as subprocesses: JSON payload on stdin, JSON result on the last stdout line.
A process per stage releases all VRAM when it exits and lets a stage use another interpreter."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .. import config


RESULT_MARK = "@@lyricloom-RESULT@@ "


def _worker_argv(module: str) -> list[str]:
    """The command that starts a worker in this installation.

    A PyInstaller build ships ``LyricLoomWorker.exe`` next to the GUI, because a windowed exe has no
    usable stdout. Source checkouts use the current interpreter and ``-m``."""
    if config.IS_FROZEN:
        suffix = ".exe" if config.IS_WINDOWS else ""
        worker = Path(sys.executable).with_name(f"LyricLoomWorker{suffix}")
        if worker.is_file():
            return [str(worker), module.rsplit(".", 1)[-1]]
        if config.IS_WINDOWS:
            raise WorkerError(
                module,
                "LyricLoomWorker.exe is missing from this installation. The installation is damaged; "
                "reinstall LyricLoom from the official installer, or restore LyricLoomWorker.exe from "
                "antivirus quarantine.")
        return [sys.executable, "--worker", module.rsplit(".", 1)[-1]]
    return [sys.executable, "-m", module]


def _is_this_interpreter(python: str | None) -> bool:
    """True when `python` names the running interpreter. In a packaged build that is the GUI
    executable, which must never be started as a worker (it would open a second window)."""
    if python is None:
        return True
    try:
        return Path(python).resolve() == Path(sys.executable).resolve()
    except OSError:
        return False


def read_payload() -> dict:
    return json.loads(sys.stdin.buffer.read().decode("utf-8"))


def emit(result: dict) -> None:
    """Writes the result line. Libraries may print to stdout too, so the line is marked and
    pending text output is flushed first."""
    sys.stdout.flush()
    sys.stdout.buffer.write((RESULT_MARK + json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


class WorkerError(RuntimeError):
    def __init__(self, module: str, stderr_tail: str):
        super().__init__(f"{module} failed: {stderr_tail}")
        self.module = module
        self.stderr_tail = stderr_tail


def wsl_path(path: Path | str) -> str:
    r"""WSL's view of a Windows path: F:\X\a.flac -> /mnt/f/X/a.flac."""
    s = str(path).replace("\\", "/")
    if s.startswith("//"):
        raise ValueError("UNC paths (\\\\server\\share) are not supported by the WSL bridge; "
                         "map the share to a drive letter first")
    return f"/mnt/{s[0].lower()}{s[2:]}" if re.match(r"^[A-Za-z]:", s) else s


def windows_path(path: str) -> Path:
    """The inverse of wsl_path; paths outside /mnt/<drive> come back unchanged."""
    m = re.match(r"^/mnt/([a-z])(/.*)?$", path)
    return Path(f"{m.group(1).upper()}:{m.group(2) or '/'}") if m else Path(path)


def run_worker(module: str, payload: dict, python: str | None = None, timeout_s: int = 3600,
               cwd: Path | None = None, wsl: str | None = None, wsl_env: dict | None = None) -> dict:
    """`wsl` names a WSL distro to run the worker in, with `python` being that distro's
    interpreter and `wsl_env` extra variables for it; paths in the payload are the caller's job."""
    threads = {"OMP_NUM_THREADS": str(config.CPU_THREADS), "MKL_NUM_THREADS": str(config.CPU_THREADS)}
    cwd = cwd or (config.APP_DATA if config.IS_FROZEN else config.PROJECT_ROOT)
    cwd = Path(cwd)
    if not cwd.exists():
        cwd.mkdir(parents=True, exist_ok=True)
    if wsl:
        # Windows variables do not reach the distro, so everything it needs goes through `env`.
        assigned = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", **threads, **(wsl_env or {})}
        argv = ["wsl.exe", "-d", wsl, "--cd", wsl_path(cwd), "--exec", "env",
                *(f"{k}={v}" for k, v in assigned.items()), python or "python3", "-m", module]
        env = dict(os.environ)
    else:
        # audio-separator looks for ffmpeg on PATH; imageio-ffmpeg ships a static binary.
        scripts = str(Path(python or sys.executable).parent)
        path_parts = [scripts]
        try:
            import imageio_ffmpeg

            path_parts.insert(0, str(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent))
        except Exception:  # noqa: BLE001 - a system ffmpeg is fine
            pass
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
               "PATH": os.pathsep.join(path_parts + [os.environ.get("PATH", "")]),
               # Caps torch/numpy/onnxruntime thread pools in the worker (see config.CPU_THREADS).
               **threads}
        argv = _worker_argv(module) if _is_this_interpreter(python) else [python, "-m", module]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if config.IS_WINDOWS else 0
    proc = subprocess.run(
        argv, input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True, timeout=timeout_s, env=env, cwd=str(cwd), creationflags=flags,
    )
    stderr = proc.stderr.decode("utf-8", "replace")
    if proc.returncode != 0:
        raise WorkerError(module, stderr[-2000:])
    marked = [l for l in proc.stdout.decode("utf-8", "replace").splitlines() if l.startswith(RESULT_MARK)]
    if not marked:
        raise WorkerError(module, "no result line on stdout; stderr: " + stderr[-1500:])
    return json.loads(marked[-1][len(RESULT_MARK):])
