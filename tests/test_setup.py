import json
import re
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

from lyricloom import config, setup
from lyricloom.workers import WorkerCancelled, run_process_stream


def _imports(**overrides):
    values = {name: True for name in setup.WslEnvironment.REQUIRED_IMPORTS}
    values.update(overrides)
    return values


def _report(**overrides):
    values = {
        "os_name": "Windows 11",
        "cpu_cores": 8,
        "ram_bytes": 16 * setup.GiB,
        "gpus": (setup.GpuAdapter("NVIDIA GeForce RTX 4070", "nvidia", 12 * setup.GiB, "1.0"),),
        "wsl": setup.WslState(installed=True, version2=True),
    }
    values.update(overrides)
    return setup.SystemReport(**values)


class Runner:
    """A fake command runner that records calls and dispatches on the argv."""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def __call__(self, argv, timeout_s, *, input_bytes=b"", cancel=None):
        self.calls.append((list(argv), timeout_s, input_bytes, cancel))
        result = self.handler(list(argv), timeout_s, input_bytes, cancel)
        if isinstance(result, BaseException):
            raise result
        return result


# --------------------------------------------------------------------------- GPU parsing


def test_parse_gpu_adapters_handles_one_adapter_and_vendors():
    data = json.dumps({"Name": "NVIDIA GeForce RTX 4070", "AdapterRAM": 12 * setup.GiB,
                       "DriverVersion": "31.0.15.5222"}).encode()
    adapters = setup._parse_gpu_adapters(data)
    assert len(adapters) == 1
    assert adapters[0].name == "NVIDIA GeForce RTX 4070"
    assert adapters[0].vendor == "nvidia"
    assert adapters[0].memory_bytes == 12 * setup.GiB
    assert adapters[0].driver_version == "31.0.15.5222"


def test_parse_gpu_adapters_handles_several_adapters_and_vendor_names():
    data = json.dumps([
        {"Name": "AMD Radeon RX 7800 XT", "AdapterRAM": 16 * setup.GiB, "DriverVersion": "32.0"},
        {"Name": "Intel(R) UHD Graphics 770", "AdapterRAM": None, "DriverVersion": "31.0"},
        {"Name": "Microsoft Basic Display Adapter", "AdapterRAM": "", "DriverVersion": ""},
    ]).encode()
    adapters = setup._parse_gpu_adapters(data)
    assert [adapter.vendor for adapter in adapters] == ["amd", "intel", "other"]
    assert adapters[0].memory_bytes == 16 * setup.GiB
    assert adapters[1].memory_bytes is None
    assert adapters[2].driver_version == ""


def test_parse_gpu_adapters_rejects_invalid_json():
    with pytest.raises(ValueError, match="invalid JSON"):
        setup._parse_gpu_adapters(b"not json")


def test_parse_nvidia_smi_reads_name_driver_and_memory():
    data = (b"NVIDIA GeForce RTX 3060, 566.36, 12288 MiB\r\n"
            b"NVIDIA RTX A4000, 552.22, 16384 MiB\r\n")
    gpus = setup._parse_nvidia_smi(data)
    assert [gpu.name for gpu in gpus] == ["NVIDIA GeForce RTX 3060", "NVIDIA RTX A4000"]
    assert gpus[0].driver_version == "566.36"
    assert gpus[0].memory_bytes == 12_288 * 1024 ** 2
    assert gpus[1].memory_bytes == 16_384 * 1024 ** 2


def test_parse_nvidia_smi_skips_a_no_devices_message():
    assert setup._parse_nvidia_smi(b"No devices were found\n") == ()


# --------------------------------------------------------------------------- WSL parsing


def test_parse_wsl_distros_reads_state_version_and_default():
    text = ("  NAME      STATE           VERSION\r\n"
            "* linux     Running         2\r\n"
            "  acervo    Stopped         2\r\n")
    distros = setup._parse_wsl_distros(text.encode("utf-16-le"))
    assert [distro.name for distro in distros] == ["linux", "acervo"]
    assert distros[0].state == "Running"
    assert distros[0].version == 2
    assert distros[0].default is True
    assert distros[1].default is False


def test_detect_collects_gpus_nvidia_details_and_wsl(monkeypatch):
    # The Windows memory query cannot run on the Linux CI machine once IS_WINDOWS is forced.
    monkeypatch.setattr(setup, "_ram_bytes", lambda: 32 * setup.GiB)
    monkeypatch.setattr(config, "IS_WINDOWS", True)
    monkeypatch.setattr(setup.shutil, "which", lambda name: {
        "nvidia-smi": r"C:\Windows\System32\nvidia-smi.exe",
        "wsl.exe": r"C:\Windows\System32\wsl.exe",
    }.get(name))
    gpu_json = json.dumps({"Name": "NVIDIA GeForce RTX 4070", "AdapterRAM": 12 * setup.GiB,
                           "DriverVersion": "31.0.15.5222"}).encode()
    wsl_list = ("  NAME      STATE           VERSION\r\n"
                "* linux     Running         2\r\n").encode("utf-16-le")

    def handler(argv, timeout_s, input_bytes, cancel):
        if argv == setup.GPU_QUERY:
            return setup.CommandResult(0, gpu_json)
        if argv == setup.NVIDIA_QUERY:
            return setup.CommandResult(0, b"NVIDIA GeForce RTX 4070, 566.36, 12288 MiB\n")
        if argv == ["wsl.exe", "-l", "-v"]:
            return setup.CommandResult(0, wsl_list)
        raise AssertionError(f"unexpected command: {argv}")

    report = setup.detect(runner=Runner(handler))
    assert report.gpus[0].vendor == "nvidia"
    assert report.gpus[0].memory_bytes == 12 * setup.GiB
    assert report.nvidia[0].name == "NVIDIA GeForce RTX 4070"
    assert report.nvidia[0].memory_bytes == 12_288 * 1024 ** 2
    assert report.wsl.installed is True
    assert report.wsl.version2 is True
    assert report.wsl.distros[0].name == "linux"
    assert report.os_name
    assert report.cpu_cores
    assert report.ram_bytes == 32 * setup.GiB
    assert report.disk_free_bytes


def test_detect_never_raises_when_every_command_times_out(monkeypatch):
    monkeypatch.setattr(config, "IS_WINDOWS", True)
    monkeypatch.setattr(setup.shutil, "which", lambda name: rf"C:\tools\{name}")

    def timeout(argv, timeout_s, input_bytes, cancel):
        return subprocess.TimeoutExpired(argv, timeout_s)

    report = setup.detect(runner=Runner(timeout))
    assert isinstance(report, setup.SystemReport)
    assert "TimeoutExpired" in (report.gpu_error or "")
    assert "TimeoutExpired" in (report.nvidia_error or "")
    assert report.wsl.error


def test_probe_python_listing_is_the_one_allowed_fixed_sh_c():
    calls = []

    def handler(argv, timeout_s, input_bytes, cancel):
        calls.append(list(argv))
        return setup.CommandResult(0, b"")

    runner = Runner(handler)
    setup._list_wsl_pythons("linux", runner)
    assert calls == [["wsl.exe", "-d", "linux", "--", "sh", "-c",
                      "ls -1 /opt/*/bin/python 2>/dev/null"]]


def test_find_wsl_environments_probes_the_configured_and_opt_interpreters(monkeypatch):
    monkeypatch.setattr(config, "IS_WINDOWS", True)
    config.set_setting("wsl_python", "/opt/torch/bin/python")
    config.set_setting("wsl_env", {"HSA_OVERRIDE_GFX_VERSION": "10.3.0"})

    def payload(python):
        return {
            "python": python,
            "python_version": "3.12.3",
            "torch_version": "2.14.1+rocm7.2",
            "gpu_available": True,
            "device_name": "AMD Radeon RX 6900 XT",
            "backend": "rocm",
            "imports": _imports(),
            "import_versions": {"torch": "2.14.1+rocm7.2"},
            "import_errors": {},
            "error": None,
        }

    def handler(argv, timeout_s, input_bytes, cancel):
        if argv[-3:] == ["sh", "-c", "ls -1 /opt/*/bin/python 2>/dev/null"]:
            return setup.CommandResult(0, b"/opt/torch/bin/python\n/opt/wtmod/bin/python\n")
        assert argv[-1] == "-", argv
        python = argv[-2]
        return setup.CommandResult(0, (setup.PROBE_MARK + json.dumps(payload(python)) + "\n").encode())

    runner = Runner(handler)
    environments = setup.find_wsl_environments("linux", runner=runner)
    assert [env.python for env in environments] == [
        "/opt/torch/bin/python", "/opt/lyricloom/venv/bin/python", "/opt/wtmod/bin/python"]
    assert environments[0].gpu_available and environments[0].backend == "rocm"
    assert environments[0].device_name == "AMD Radeon RX 6900 XT"
    assert environments[0].passed

    probe_calls = [call for call in runner.calls if call[0][-1] == "-"]
    assert len(probe_calls) == 3
    argv, _timeout, script, _cancel = probe_calls[0]
    assert argv[:4] == ["wsl.exe", "-d", "linux", "--exec"]
    assert "env" in argv
    assert "HSA_OVERRIDE_GFX_VERSION=10.3.0" in argv
    assert "PYTHONIOENCODING=utf-8" in argv
    assert script.startswith(b'"""Probe one interpreter')
    assert probe_calls[0][0][-2:] == ["/opt/torch/bin/python", "-"]


def test_find_wsl_environments_reports_a_failed_probe_without_raising(monkeypatch):
    monkeypatch.setattr(config, "IS_WINDOWS", True)
    monkeypatch.setattr(config, "setting", lambda key, default=None: {
        "wsl_python": "/opt/torch/bin/python"}.get(key, default))

    def handler(argv, timeout_s, input_bytes, cancel):
        if argv[-3:] == ["sh", "-c", "ls -1 /opt/*/bin/python 2>/dev/null"]:
            return setup.CommandResult(0, b"")
        return setup.CommandResult(1, b"", b"ModuleNotFoundError: torch")

    environments = setup.find_wsl_environments("linux", runner=Runner(handler))
    assert environments
    assert all(env.error for env in environments)


def test_parse_wsl_probe_reads_gpu_backend_and_imports():
    payload = {
        "python": "/opt/torch/bin/python",
        "python_version": "3.12.3",
        "torch_version": "2.14.1+rocm7.2",
        "gpu_available": True,
        "device_name": "AMD Radeon RX 6900 XT",
        "backend": "rocm",
        "imports": _imports(),
        "import_versions": {},
        "import_errors": {},
        "error": None,
    }
    data = (setup.PROBE_MARK + json.dumps(payload) + "\n").encode()
    environment = setup._parse_wsl_probe("linux", "/opt/torch/bin/python", data)
    assert environment is not None
    assert environment.passed
    assert environment.torch_version == "2.14.1+rocm7.2"
    assert environment.device_name == "AMD Radeon RX 6900 XT"
    assert environment.backend == "rocm"


def test_parse_wsl_probe_marks_missing_packages_as_a_failed_environment():
    payload = {
        "python": "/opt/torch/bin/python", "python_version": "3.12.3",
        "torch_version": "2.14.1+rocm7.2", "gpu_available": True,
        "device_name": "AMD Radeon RX 6900 XT", "backend": "rocm",
        "imports": _imports(lyricloom=False), "import_versions": {},
        "import_errors": {"lyricloom": "ModuleNotFoundError"}, "error": None,
    }
    data = (setup.PROBE_MARK + json.dumps(payload) + "\n").encode()
    environment = setup._parse_wsl_probe("linux", "/opt/torch/bin/python", data)
    assert environment is not None
    assert environment.missing_imports == ("lyricloom",)
    assert not environment.passed


def test_parse_wsl_probe_returns_none_without_a_result_line():
    assert setup._parse_wsl_probe("linux", "/usr/bin/python3", b"no result here\n") is None


# --------------------------------------------------------------------------- settings rule


def test_use_wsl_environment_writes_settings_only_after_a_passing_probe():
    config.set_setting("wsl_env", {"HSA_OVERRIDE_GFX_VERSION": "10.3.0"})
    config.set_setting("wsl_hsa_override", "10.3.0")
    before = config.all_settings()
    failed = setup.WslEnvironment(
        distro="linux", python="/opt/torch/bin/python", gpu_available=True, backend="rocm",
        imports=_imports(), error="the probe failed")
    assert setup.use_wsl_environment(failed) is False
    assert config.all_settings() == before

    passing = setup.WslEnvironment(
        distro="linux", python="/opt/torch/bin/python", gpu_available=True, backend="rocm",
        imports=_imports())
    assert setup.use_wsl_environment(passing) is True
    assert config.setting("wsl_gpu") is True
    assert config.setting("wsl_distro") == "linux"
    assert config.setting("wsl_python") == "/opt/torch/bin/python"
    # The user's env values survive untouched.
    assert config.setting("wsl_env") == {"HSA_OVERRIDE_GFX_VERSION": "10.3.0"}
    assert config.setting("wsl_hsa_override") == "10.3.0"


# --------------------------------------------------------------------------- whisper backends


def test_whisper_manifest_is_pinned_to_the_official_v1_9_2_windows_builds():
    assert {backend.name for backend in setup.WHISPER_BACKENDS} == {"blas", "cublas"}
    expected = {
        "blas": ("whisper-blas-bin-x64.zip", 20_981_386,
                 "ffe5b47ca8e53a7677949f23a9c4641bbec4eee8a5714c3d14b67bb8d7b24a78"),
        "cublas": ("whisper-cublas-12.4.0-bin-x64.zip", 670_611_449,
                   "443110ddaad70d4290ab2e77179e31cf712035bbc4fad56bb4519a90c917b39c"),
    }
    for backend in setup.WHISPER_BACKENDS:
        filename, size, digest = expected[backend.name]
        assert backend.filename == filename
        assert backend.url == ("https://github.com/ggml-org/whisper.cpp/releases/download/"
                               f"v{setup.WHISPER_CPP_VERSION}/{filename}")
        assert backend.size == size
        assert backend.sha256 == digest
        assert re.fullmatch(r"[0-9a-f]{64}", backend.sha256)
    assert not any("vulkan" in backend.url.lower() for backend in setup.WHISPER_BACKENDS)


def _installable_zip(path: Path, members: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as bundle:
        for name, data in members.items():
            bundle.writestr(name, data)
    return path


def test_install_whisper_backend_extracts_verifies_and_sets_the_setting(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DATA", tmp_path / "data")

    def download(spec, dest, progress=None, cancel=None):
        return _installable_zip(dest, {"Release/whisper-cli.exe": b"fake exe",
                                       "Release/whisper.dll": b"fake dll"})

    calls = []

    def handler(argv, timeout_s, input_bytes, cancel):
        calls.append((list(argv), timeout_s))
        return setup.CommandResult(0, b"usage: whisper-cli\n")

    cli = setup.install_whisper_backend("blas", download=download, runner=Runner(handler))
    expected = tmp_path / "data" / "backends" / "whisper-blas" / "Release" / "whisper-cli.exe"
    assert cli == expected
    assert cli.is_file()
    assert Path(str(config.setting("whisper_cli"))) == expected
    assert len(calls) == 1
    assert calls[0][0][-1] == "--help"
    assert Path(calls[0][0][0]).parts[-3:] == (
        ".whisper-blas.installing", "Release", "whisper-cli.exe")
    assert calls[0][1] == 20.0


def test_install_whisper_backend_does_not_store_a_broken_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DATA", tmp_path / "data")
    before = config.all_settings()

    def download(spec, dest, progress=None, cancel=None):
        return _installable_zip(dest, {"Release/whisper-cli.exe": b"fake exe"})

    def handler(argv, timeout_s, input_bytes, cancel):
        return setup.CommandResult(1, b"", b"a required DLL was not found")

    with pytest.raises(setup.BackendError, match="DLL"):
        setup.install_whisper_backend("cublas", download=download, runner=Runner(handler))
    assert config.all_settings() == before
    assert not (tmp_path / "data" / "backends" / "whisper-cublas").exists()


def test_extract_zip_refuses_zip_slip_paths(tmp_path):
    for name in ("../evil.txt", "/absolute.txt", r"..\evil.txt", "C:/evil.txt"):
        archive = tmp_path / "bad.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(name, "evil")
        with pytest.raises(setup.BackendError):
            setup._extract_zip(archive, tmp_path / "target")
        assert not (tmp_path / "evil.txt").exists()
        archive.unlink()


def test_remove_whisper_backend_deletes_files_and_clears_its_setting(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DATA", tmp_path / "data")

    def download(spec, dest, progress=None, cancel=None):
        return _installable_zip(dest, {"whisper-cli.exe": b"fake exe"})

    cli = setup.install_whisper_backend("blas", download=download,
                                        runner=Runner(lambda *args, **kwargs: setup.CommandResult(0)))
    assert setup.remove_whisper_backend("blas") is True
    assert not cli.exists()
    assert config.setting("whisper_cli") == ""


def test_use_bundled_whisper_clears_the_backend_setting(monkeypatch):
    monkeypatch.delenv("LYRICLOOM_WHISPER_CLI", raising=False)
    config.set_setting("whisper_cli", "C:/somewhere/whisper-cli.exe")
    result = setup.use_bundled_whisper()
    assert config.setting("whisper_cli") == ""
    assert result == config.whisper_cli()


def test_unknown_whisper_backend_is_rejected():
    with pytest.raises(ValueError, match="unknown whisper backend"):
        setup.install_whisper_backend("vulkan")


# --------------------------------------------------------------------------- WSL setup script


def test_bundled_wsl_files_in_a_source_checkout():
    script, wheel = setup.bundled_wsl_files()
    assert script == config.PROJECT_ROOT / "packaging" / "wsl" / "setup-lyricloom-wsl.sh"
    assert script.is_file()
    assert wheel is None


def test_wsl_install_command_names_ubuntu_24_04():
    assert setup.wsl_install_command() == ["wsl.exe", "--install", "-d", "Ubuntu-24.04"]


def test_run_wsl_setup_streams_lines_and_probes_the_new_environment(tmp_path, monkeypatch):
    script = tmp_path / "setup-lyricloom-wsl.sh"
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    wheel = tmp_path / "lyricloom-2.1.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    monkeypatch.setattr(setup, "bundled_wsl_files", lambda: (script, wheel))
    passing = setup.WslEnvironment(
        distro="linux", python=setup.WSL_VENV_PYTHON, gpu_available=True, backend="rocm",
        imports=_imports())
    probed = []

    def fake_find(distro, **kwargs):
        probed.append(distro)
        return [passing]

    monkeypatch.setattr(setup, "find_wsl_environments", fake_find)
    lines = []
    seen = []

    def stream(argv, *, input_bytes=b"", timeout_s=None, cancel=None, on_line=None):
        seen.append((list(argv), input_bytes))
        for line in ("@@step 1/7 Installing apt packages",
                     '{"ok": true, "python": "/opt/lyricloom/venv/bin/python"}'):
            if on_line:
                on_line(line)
        return subprocess.CompletedProcess(
            argv, 0,
            b"@@step 1/7 Installing apt packages\n"
            b'{"ok": true, "python": "/opt/lyricloom/venv/bin/python"}\n',
            b"")

    result = setup.run_wsl_setup("linux", "rocm", wheel, lines.append, stream=stream)
    assert result.ok is True
    assert result.environment is passing
    assert result.details["ok"] is True
    assert lines == ["@@step 1/7 Installing apt packages",
                     '{"ok": true, "python": "/opt/lyricloom/venv/bin/python"}']
    assert probed == ["linux"]
    argv, script_bytes = seen[0]
    assert argv[:4] == ["wsl.exe", "-d", "linux", "--exec"]
    assert "bash" in argv and "-s" in argv
    assert argv[argv.index("--backend") + 1] == "rocm"
    assert argv[argv.index("--wheel") + 1].endswith("lyricloom-2.1.0-py3-none-any.whl")
    assert script_bytes == script.read_bytes()


def test_run_wsl_setup_accepts_a_cpu_environment_without_a_gpu(tmp_path, monkeypatch):
    script = tmp_path / "setup-lyricloom-wsl.sh"
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    wheel = tmp_path / "lyricloom-2.1.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    monkeypatch.setattr(setup, "bundled_wsl_files", lambda: (script, wheel))
    cpu_environment = setup.WslEnvironment(
        distro="linux", python=setup.WSL_VENV_PYTHON, gpu_available=False, backend="cpu",
        imports=_imports())
    monkeypatch.setattr(setup, "find_wsl_environments",
                        lambda *args, **kwargs: [cpu_environment])

    def stream(argv, *, input_bytes=b"", timeout_s=None, cancel=None, on_line=None):
        return subprocess.CompletedProcess(argv, 0, b'{"ok": true}\n', b"")

    result = setup.run_wsl_setup("linux", "cpu", wheel, stream=stream)
    assert result.ok is True
    assert result.environment is cpu_environment


def test_run_wsl_setup_reports_a_failed_script(tmp_path, monkeypatch):
    script = tmp_path / "setup-lyricloom-wsl.sh"
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    wheel = tmp_path / "lyricloom-2.1.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    monkeypatch.setattr(setup, "bundled_wsl_files", lambda: (script, wheel))
    monkeypatch.setattr(setup, "find_wsl_environments", lambda *args, **kwargs: [])

    def stream(argv, *, input_bytes=b"", timeout_s=None, cancel=None, on_line=None):
        return subprocess.CompletedProcess(argv, 1, b"@@step 1/7 apt\n", b"apt failed")

    result = setup.run_wsl_setup("linux", "cpu", wheel, stream=stream)
    assert result.ok is False
    assert "apt failed" in (result.error or "")


def test_run_wsl_setup_requires_the_bundled_wheel(tmp_path):
    with pytest.raises(FileNotFoundError, match="wheel"):
        setup.run_wsl_setup("linux", "cpu", tmp_path / "missing.whl")


# --------------------------------------------------------------------------- recommendations


def test_recommend_nvidia_with_wsl2_uses_cublas_and_turbo_on_a_small_machine():
    recommendation = setup.recommend(_report(ram_bytes=8 * setup.GiB, cpu_cores=4))
    assert recommendation.cpu_available is True
    assert recommendation.wsl_gpu is True
    assert recommendation.gpu_vendor == "nvidia"
    assert recommendation.whisper_backend == "cublas"
    assert recommendation.whisper_model == "whisper-large-v3-turbo"
    assert "WSL 2" in recommendation.wsl_gpu_reason
    assert "12 GB" in recommendation.whisper_model_reason


def test_recommend_amd_with_wsl2_uses_blas():
    report = _report(gpus=(setup.GpuAdapter("AMD Radeon RX 7800 XT", "amd"),))
    recommendation = setup.recommend(report)
    assert recommendation.wsl_gpu is True
    assert recommendation.gpu_vendor == "amd"
    assert recommendation.whisper_backend == "blas"
    assert recommendation.whisper_model == "whisper-large-v3"
    assert "AMD" in recommendation.wsl_gpu_reason


def test_recommend_without_wsl2_or_a_supported_gpu_stays_on_the_cpu():
    intel = setup.SystemReport(gpus=(setup.GpuAdapter("Intel UHD 770", "intel"),),
                               wsl=setup.WslState(installed=True, version2=True))
    recommendation = setup.recommend(intel)
    assert recommendation.wsl_gpu is False
    assert recommendation.whisper_backend == "blas"
    assert "No NVIDIA or AMD GPU" in recommendation.wsl_gpu_reason

    no_wsl = setup.recommend(_report(wsl=setup.WslState(installed=False, version2=False)))
    assert no_wsl.wsl_gpu is False
    assert "WSL 2 is not ready" in no_wsl.wsl_gpu_reason


def test_recommend_uses_the_smaller_model_on_less_than_six_cores():
    recommendation = setup.recommend(_report(cpu_cores=4, ram_bytes=32 * setup.GiB))
    assert recommendation.whisper_model == "whisper-large-v3-turbo"


# --------------------------------------------------------------------------- streaming runner


def test_run_process_stream_reports_each_line_as_it_arrives():
    lines = []
    result = run_process_stream(
        [sys.executable, "-u", "-c", "print('first'); print('second')"], on_line=lines.append)
    assert result.returncode == 0
    assert lines == ["first", "second"]
    assert result.stdout.splitlines() == [b"first", b"second"]


def test_run_process_stream_is_cancellable():
    cancel = threading.Event()

    def stop_soon():
        time.sleep(0.4)
        cancel.set()

    threading.Thread(target=stop_soon, daemon=True).start()
    started = time.monotonic()
    with pytest.raises(WorkerCancelled):
        run_process_stream([sys.executable, "-c", "import time; time.sleep(30)"], cancel=cancel)
    assert time.monotonic() - started < 20
