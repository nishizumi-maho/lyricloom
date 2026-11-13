"""Probe one interpreter (WSL or the Windows GPU runtime) for GPU support and LyricLoom's packages.

Run this file as ``<python> -`` with the source on stdin, not with ``-m``: the environment being
probed may not have the ``lyricloom`` package installed, so it must not import anything from the
repository.  It prints one machine-readable result line and nothing else on stdout.

The caller (:func:`lyricloom.setup.find_wsl_environments`) sets the environment (including
``wsl_env`` values such as ``HSA_OVERRIDE_GFX_VERSION``) before starting the interpreter.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import platform
import sys

RESULT_MARK = "@@lyricloom-PROBE@@ "
IMPORTS = ("torch", "audio_separator", "torchaudio", "g2p_en", "nltk", "lyricloom")


def _import(name: str) -> tuple[bool, str | None, str]:
    """Returns ``(imported, version, error)``; a broken package is a failed import, not a crash."""
    try:
        module = importlib.import_module(name)
        version = getattr(module, "__version__", None)
        return True, str(version) if version is not None else None, ""
    except Exception as exc:  # noqa: BLE001 - any import failure is reported, never raised
        return False, None, f"{type(exc).__name__}: {exc}"


def _smoke(torch, device) -> str | None:
    """Runs one small convolution on ``device``; None when it worked.

    ``torch.cuda.is_available()`` only says a driver answered.  A torch build without kernels for
    the card (an RTX 50-series GPU with an older CUDA build) fails on the first real operation."""
    try:
        layer = torch.nn.Conv1d(4, 4, 3).to(device)
        value = layer(torch.ones((1, 4, 64), device=device)).sum().item()
        return None if value == value else "the GPU returned NaN for a simple operation"
    except Exception as exc:  # noqa: BLE001 - any failure is the answer
        return f"{type(exc).__name__}: {exc}"


def _directml(torch, result: dict) -> None:
    """Fills in the DirectML device when torch-directml is installed and has an adapter."""
    try:
        if importlib.util.find_spec("torch_directml") is None:
            return
        import torch_directml

        if not torch_directml.is_available():
            return
        result["gpu_available"] = True
        result["device_name"] = str(torch_directml.device_name(0))
        result["backend"] = "directml"
        result["smoke_error"] = _smoke(torch, torch_directml.device())
    except Exception as exc:  # noqa: BLE001 - a broken DirectML install is a reported failure
        result["error"] = f"{type(exc).__name__}: {exc}"


def probe() -> dict:
    result: dict = {
        "python": sys.executable,
        "python_version": platform.python_version(),
        "torch_version": None,
        "gpu_available": False,
        "device_name": None,
        "backend": "cpu",
        "smoke_error": None,
        "imports": {},
        "import_versions": {},
        "import_errors": {},
        "error": None,
    }
    for name in IMPORTS:
        imported, version, error = _import(name)
        result["imports"][name] = imported
        if version:
            result["import_versions"][name] = version
        if error:
            result["import_errors"][name] = error
    torch_imported = bool(result["imports"].get("torch"))
    if not torch_imported:
        result["error"] = result["import_errors"].get("torch") or "torch could not be imported"
        return result
    try:
        import torch

        result["torch_version"] = str(torch.__version__)
        try:
            available = bool(torch.cuda.is_available())
            result["gpu_available"] = available
            if available:
                result["device_name"] = str(torch.cuda.get_device_name(0))
                result["backend"] = "rocm" if getattr(torch.version, "hip", None) else "cuda"
                result["smoke_error"] = _smoke(torch, "cuda")
            else:
                _directml(torch, result)
        except Exception as exc:  # noqa: BLE001 - a broken GPU runtime is a reported failure
            result["error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 - already imported once, but never crash the probe
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def main() -> int:
    payload = probe()
    sys.stdout.write(RESULT_MARK + json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0 if payload.get("error") is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
