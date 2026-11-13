"""The Windows GPU runtime engine, with fakes in place of uv, the network and the GPU."""
import json
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

import pytest

from lyricloom import config, gpu_runtime
from lyricloom.workers import WorkerCancelled


@pytest.fixture(autouse=True)
def windows_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "IS_WINDOWS", True)
    monkeypatch.setattr(config, "IS_FROZEN", False)
    monkeypatch.setattr(config, "RUNTIMES", tmp_path / "runtimes")
    monkeypatch.setattr(config, "APP_DATA", tmp_path / "data")
    # A CI disk may be nearly full; the size check has its own test.
    monkeypatch.setattr(gpu_runtime.shutil, "disk_usage",
                        lambda path: gpu_runtime.shutil._ntuple_diskusage(10 ** 13, 0, 10 ** 13))


def _payload(backend="cuda", **overrides):
    values = {
        "python": "python.exe", "python_version": "3.11.9", "torch_version": "2.5.1+cu124",
        "gpu_available": True, "device_name": "NVIDIA GeForce RTX 3060", "backend": backend,
        "smoke_error": None, "import_errors": {}, "error": None,
        "imports": {name: True for name in ("torch", "torchaudio", "audio_separator", "g2p_en",
                                            "nltk", "lyricloom")},
    }
    values.update(overrides)
    return values


def _probe_output(**overrides) -> bytes:
    return (gpu_runtime.PROBE_MARK + json.dumps(_payload(**overrides)) + "\n").encode()


def _download(spec, dest, progress=None, cancel=None):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w") as bundle:
        bundle.writestr("uv.exe", b"uv")
        bundle.writestr("uvx.exe", b"uvx")
    return dest


class Uv:
    """A fake uv: records every call and creates the interpreter on ``venv``."""

    def __init__(self, fail_on=None, cancel_on=None):
        self.calls, self.envs = [], []
        self.fail_on, self.cancel_on = fail_on, cancel_on

    def __call__(self, argv, *, timeout_s, env, cancel, on_line):
        arguments = list(argv[1:])
        self.calls.append(arguments)
        self.envs.append(env)
        if self.cancel_on and self.cancel_on in arguments:
            raise WorkerCancelled()
        if arguments[0] == "venv":
            python = Path(arguments[-1]) / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_bytes(b"")
        on_line("Resolved 3 packages")
        if self.fail_on and any(self.fail_on in item for item in arguments):
            return subprocess.CompletedProcess(argv, 2, b"", b"error: No solution found")
        return subprocess.CompletedProcess(argv, 0, b"", b"")


def _runner(output: bytes, calls=None):
    def run(argv, timeout_s, *, input_bytes=b"", env=None, cwd=None, cancel=None):
        if calls is not None:
            calls.append((list(argv), input_bytes, env, cwd))
        return subprocess.CompletedProcess(argv, 0, output, b"")
    return run


# --------------------------------------------------------------------------- plans


@pytest.mark.parametrize("name", ["NVIDIA GeForce RTX 5080", "NVIDIA GeForce RTX 5070 Ti",
                                  "NVIDIA RTX PRO 6000 Blackwell", "nvidia geforce rtx 5090 d"])
def test_rtx_50_series_gets_the_cuda_12_8_build(name):
    plan = gpu_runtime.plan_for("cuda", name)
    assert plan.torch_index == "https://download.pytorch.org/whl/cu128"
    assert plan.torch_packages == ("torch==2.7.1", "torchaudio==2.7.1", "torchvision==0.22.1")


@pytest.mark.parametrize("name", ["NVIDIA GeForce RTX 3060", "NVIDIA GeForce GTX 1660 SUPER",
                                  "NVIDIA GeForce RTX 4070", "NVIDIA RTX A5000", "",
                                  "NVIDIA Quadro RTX 5000", "NVIDIA RTX 5000 Ada Generation"])
def test_other_nvidia_cards_get_the_cuda_12_4_build(name):
    plan = gpu_runtime.plan_for("cuda", name)
    assert plan.torch_index == "https://download.pytorch.org/whl/cu124"
    assert plan.torch_packages == ("torch==2.5.1", "torchaudio==2.5.1", "torchvision==0.20.1")
    assert plan.packages == ("audio-separator[gpu]==0.47.1", "g2p_en", "nltk")


def test_directml_comes_from_pypi_and_says_what_it_does_not_accelerate():
    plan = gpu_runtime.plan_for("directml")
    assert plan.torch_index == ""
    assert plan.torch_packages == ("torch==2.4.1", "torchaudio==2.4.1")
    assert plan.packages == ("audio-separator[dml]==0.47.1",)
    assert "RoFormer" in plan.note and "CPU" in plan.note


def test_an_unknown_backend_is_an_error():
    with pytest.raises(ValueError, match="unknown GPU backend"):
        gpu_runtime.plan_for("vulkan")


# --------------------------------------------------------------------------- install


def test_install_runs_the_uv_steps_in_order_inside_the_data_folder(tmp_path):
    uv, lines, probes = Uv(), [], []
    result = gpu_runtime.install("cuda", "NVIDIA GeForce RTX 3060", on_line=lines.append,
                                 download=_download, stream=uv,
                                 runner=_runner(_probe_output(), probes))
    python = str(tmp_path / "runtimes" / "cuda" / "Scripts" / "python.exe")
    assert result.ok and result.python == python and result.error is None
    assert uv.calls == [
        ["venv", "--python", "3.11", "--allow-existing", str(tmp_path / "runtimes" / "cuda")],
        ["pip", "install", "--python", python, "--default-index",
         "https://download.pytorch.org/whl/cu124", "torch==2.5.1", "torchaudio==2.5.1",
         "torchvision==0.20.1"],
        ["pip", "install", "--python", python, "audio-separator[gpu]==0.47.1", "g2p_en", "nltk"],
    ]
    env = uv.envs[0]
    assert env["UV_CACHE_DIR"] == str(tmp_path / "runtimes" / "cache")
    assert env["UV_PYTHON_INSTALL_DIR"] == str(tmp_path / "runtimes" / "python")
    assert env["UV_NO_CONFIG"] == "1" and env["UV_MANAGED_PYTHON"] == "1"
    steps = [line for line in lines if line.startswith("@@step")]
    assert [line.split()[1] for line in steps] == ["1/5", "2/5", "3/5", "4/5", "5/5"]
    assert lines[-1] == "NVIDIA GeForce RTX 3060 is ready (PyTorch 2.5.1+cu124)."
    # The probe ran the new interpreter with the app's own copy of the package on its path.
    argv, script, probe_env, _cwd = probes[0]
    assert argv == [python, "-"] and script.startswith(b'"""Probe one interpreter')
    assert probe_env["PYTHONPATH"] == str(config.PROJECT_ROOT)
    assert probe_env["PYTHONNOUSERSITE"] == "1"
    # Nothing is selected by installing; the caller decides with use().
    assert config.gpu_runtime() is None


def test_install_stops_at_the_first_failing_step_and_reports_uv_s_message():
    uv = Uv(fail_on="torch==2.5.1")
    result = gpu_runtime.install("cuda", download=_download, stream=uv, runner=_runner(b""))
    assert not result.ok
    assert result.error == ("Installing PyTorch for NVIDIA GPU (CUDA 12.4, PyTorch 2.5.1) failed "
                            "(exit code 2): error: No solution found")
    assert [call[0] for call in uv.calls] == ["venv", "pip"]   # the package step never ran
    assert config.gpu_runtime() is None


def test_a_cancelled_install_raises_and_changes_no_setting():
    config.update_settings({"wsl_gpu": True})
    with pytest.raises(WorkerCancelled):
        gpu_runtime.install("cuda", download=_download, stream=Uv(cancel_on="--default-index"),
                            runner=_runner(b""))
    assert config.setting("wsl_gpu") is True
    assert config.gpu_runtime() is None


def test_an_installed_environment_that_cannot_run_the_gpu_is_not_ok():
    # torch 2.5.1+cu124 on an RTX 50-series card: CUDA answers, the first kernel does not.
    output = _probe_output(smoke_error="RuntimeError: CUDA error: no kernel image is available")
    result = gpu_runtime.install("cuda", download=_download, stream=Uv(), runner=_runner(output))
    assert not result.ok
    assert "the GPU refused a test operation" in result.error
    assert "no kernel image" in result.error
    assert result.environment is not None and not result.environment.passed_for("cuda")


def test_an_environment_without_a_cuda_device_tells_the_user_what_to_do():
    output = _probe_output(gpu_available=False, backend="cpu", device_name=None)
    result = gpu_runtime.install("cuda", download=_download, stream=Uv(), runner=_runner(output))
    assert not result.ok and "NVIDIA driver" in result.error


def test_install_refuses_to_start_without_enough_disk_space(monkeypatch):
    monkeypatch.setattr(gpu_runtime.shutil, "disk_usage",
                        lambda path: gpu_runtime.shutil._ntuple_diskusage(10 ** 12, 0, 2 * 1024 ** 3))
    uv = Uv()
    with pytest.raises(gpu_runtime.GpuRuntimeError, match="Not enough free disk space"):
        gpu_runtime.install("cuda", download=_download, stream=uv, runner=_runner(b""))
    assert uv.calls == []


def test_install_is_windows_only(monkeypatch):
    monkeypatch.setattr(config, "IS_WINDOWS", False)
    with pytest.raises(gpu_runtime.GpuRuntimeError, match="only available on Windows"):
        gpu_runtime.install("cuda", download=_download, stream=Uv(), runner=_runner(b""))


def test_uv_is_downloaded_once_and_only_its_programs_are_extracted(tmp_path):
    fetched = []

    def download(spec, dest, progress=None, cancel=None):
        fetched.append(spec)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest, "w") as bundle:
            bundle.writestr("uv.exe", b"uv")
            bundle.writestr("../escape.exe", b"no")
            bundle.writestr("nested/evil.exe", b"no")
            bundle.writestr("README.txt", b"no")
        return dest

    first = gpu_runtime.ensure_uv(download=download)
    second = gpu_runtime.ensure_uv(download=download)
    assert first == second == tmp_path / "runtimes" / "uv" / gpu_runtime.UV_VERSION / "uv.exe"
    assert fetched == [gpu_runtime.UV]
    assert sorted(path.name for path in first.parent.iterdir()) == ["uv.exe"]
    assert not (tmp_path / "runtimes" / "uv" / "escape.exe").exists()


def test_the_pinned_uv_release_is_an_https_github_asset():
    assert gpu_runtime.UV.url == ("https://github.com/astral-sh/uv/releases/download/"
                                  f"{gpu_runtime.UV_VERSION}/uv-x86_64-pc-windows-msvc.zip")
    assert len(gpu_runtime.UV.sha256) == 64 and gpu_runtime.UV.size > 1_000_000


# --------------------------------------------------------------------------- probe


@pytest.mark.skipif(sys.platform != "win32", reason="WinError exists on Windows")
def test_probe_reports_a_broken_interpreter_instead_of_raising():
    def run(argv, timeout_s, **kwargs):
        raise FileNotFoundError(2, "O sistema não pode encontrar o arquivo", "python.exe", 2)

    environment = gpu_runtime.probe("python.exe", runner=run)
    assert environment.error == ("FileNotFoundError: [WinError 2] No such file or directory: "
                                 "'python.exe'")
    assert not environment.passed_for("cuda")


def test_probe_without_a_result_line_shows_the_interpreter_s_own_error():
    def run(argv, timeout_s, **kwargs):
        return subprocess.CompletedProcess(argv, 1, b"", b"ModuleNotFoundError: torch")

    environment = gpu_runtime.probe("python.exe", runner=run)
    assert environment.error == ("the GPU probe did not return a result: "
                                 "ModuleNotFoundError: torch")


def test_probe_lets_a_cancellation_through():
    def run(argv, timeout_s, **kwargs):
        raise WorkerCancelled()

    with pytest.raises(WorkerCancelled):
        gpu_runtime.probe("python.exe", runner=run, cancel=threading.Event())


def test_a_directml_environment_needs_only_the_separator_packages():
    payload = _payload(backend="directml", device_name="AMD Radeon RX 6900 XT",
                       imports={"torch": True, "audio_separator": True, "lyricloom": True,
                                "g2p_en": False, "nltk": False, "torchaudio": True})
    environment = gpu_runtime._parse_probe(
        "python.exe", (gpu_runtime.PROBE_MARK + json.dumps(payload)).encode())
    assert environment.passed_for("directml")
    assert not environment.passed_for("cuda")
    assert environment.problem("directml") == ""


def test_a_missing_package_is_named_with_its_import_error():
    payload = _payload(imports={"torch": True, "torchaudio": True, "audio_separator": False,
                                "g2p_en": True, "nltk": True, "lyricloom": True},
                       import_errors={"audio_separator": "ImportError: DLL load failed"})
    environment = gpu_runtime._parse_probe(
        "python.exe", (gpu_runtime.PROBE_MARK + json.dumps(payload)).encode())
    assert environment.problem("cuda") == (
        "missing packages: audio_separator (audio_separator: ImportError: DLL load failed)")


# --------------------------------------------------------------------------- settings


def _passing(backend="cuda"):
    return gpu_runtime._parse_probe(
        r"C:\data\runtimes\cuda\Scripts\python.exe",
        (gpu_runtime.PROBE_MARK + json.dumps(_payload(backend=backend))).encode())


def test_use_selects_a_passing_environment_and_turns_wsl_off():
    config.update_settings({"wsl_gpu": True, "wsl_distro": "Ubuntu"})
    assert gpu_runtime.use(_passing(), "cuda") is True
    assert config.gpu_runtime() == ("cuda", r"C:\data\runtimes\cuda\Scripts\python.exe")
    assert gpu_runtime.selected() == "cuda"
    assert config.setting("wsl_gpu") is False
    assert config.setting("wsl_distro") == "Ubuntu"      # the user's WSL details are kept


def test_use_refuses_an_environment_that_did_not_pass():
    broken = gpu_runtime.RuntimeEnvironment(python="python.exe", error="no torch")
    assert gpu_runtime.use(broken, "cuda") is False
    assert gpu_runtime.use(_passing("cuda"), "directml") is False   # the wrong kind of device
    assert config.gpu_runtime() is None


def test_disable_keeps_the_environment_but_goes_back_to_the_cpu():
    gpu_runtime.use(_passing(), "cuda")
    gpu_runtime.disable()
    assert config.gpu_runtime() is None and gpu_runtime.selected() == ""


def test_the_runtime_is_ignored_off_windows(monkeypatch):
    gpu_runtime.use(_passing(), "cuda")
    monkeypatch.setattr(config, "IS_WINDOWS", False)
    assert config.gpu_runtime() is None


def test_remove_deletes_the_environment_and_the_shared_tools_when_it_was_the_last(tmp_path):
    root = tmp_path / "runtimes"
    for backend in ("cuda", "directml"):
        python = root / backend / "Scripts" / "python.exe"
        python.parent.mkdir(parents=True)
        python.write_bytes(b"")
    for name in ("cache", "python", "uv", "downloads"):
        (root / name).mkdir()
    config.update_settings({"gpu_backend": "cuda",
                            "gpu_python": str(root / "cuda" / "Scripts" / "python.exe")})

    assert gpu_runtime.remove("cuda") is True
    assert not (root / "cuda").exists() and config.gpu_runtime() is None
    assert (root / "uv").exists()                         # DirectML still needs the tools
    assert gpu_runtime.remove("directml") is True
    assert not any((root / name).exists() for name in ("cache", "python", "uv", "downloads"))
    assert gpu_runtime.remove("directml") is False


def test_removing_one_runtime_leaves_the_other_selected(tmp_path):
    root = tmp_path / "runtimes"
    for backend in ("cuda", "directml"):
        python = root / backend / "Scripts" / "python.exe"
        python.parent.mkdir(parents=True)
        python.write_bytes(b"")
    config.update_settings({"gpu_backend": "directml",
                            "gpu_python": str(root / "directml" / "Scripts" / "python.exe")})
    gpu_runtime.remove("cuda")
    assert gpu_runtime.selected() == "directml"
