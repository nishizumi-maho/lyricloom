"""A packaged build must not hand its own DLL folder to a program that is not its own."""
import ctypes
import sys

import pytest

from lyricloom import config, workers

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="SetDllDirectoryW is Windows-only")


def _dll_directory() -> str:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetDllDirectoryW.argtypes = [ctypes.c_ulong, ctypes.c_wchar_p]
    kernel32.GetDllDirectoryW.restype = ctypes.c_ulong
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel32.GetDllDirectoryW(len(buffer), buffer)
    return buffer.value if length else ""


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    """Pretends to be a packaged build whose bootloader set a DLL directory."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
    before = _dll_directory()
    bundle = tmp_path / "LyricLoom" / "_internal"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(config, "IS_FROZEN", True)
    monkeypatch.setattr(config, "IS_WINDOWS", True)
    monkeypatch.setattr(sys, "executable", str(bundle.parent / "LyricLoom.exe"))
    kernel32.SetDllDirectoryW(str(bundle))
    yield bundle
    kernel32.SetDllDirectoryW(before or None)


def test_the_dll_directory_is_cleared_for_an_outside_program_and_restored(frozen, tmp_path):
    outside = tmp_path / "runtimes" / "cuda" / "Scripts" / "python.exe"
    assert _dll_directory() == str(frozen)
    with workers._system_dll_search(str(outside)):
        assert _dll_directory() == ""
    assert _dll_directory() == str(frozen)


def test_the_dll_directory_is_restored_when_starting_the_program_fails(frozen, tmp_path):
    with pytest.raises(OSError):
        with workers._system_dll_search(str(tmp_path / "elsewhere" / "uv.exe")):
            raise OSError("cannot start")
    assert _dll_directory() == str(frozen)


def test_our_own_worker_and_bare_command_names_keep_the_bundle_directory(frozen):
    for program in (str(frozen.parent / "LyricLoomWorker.exe"),
                    str(frozen / "tools" / "bin" / "whisper-cli.exe"), "wsl.exe"):
        with workers._system_dll_search(program):
            assert _dll_directory() == str(frozen)


def test_nothing_is_touched_when_no_dll_directory_is_set(frozen, tmp_path):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
    kernel32.SetDllDirectoryW(None)
    with workers._system_dll_search(str(tmp_path / "runtimes" / "python.exe")):
        assert _dll_directory() == ""
    assert _dll_directory() == ""


def test_a_source_checkout_never_changes_the_dll_directory(frozen, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "IS_FROZEN", False)
    with workers._system_dll_search(str(tmp_path / "runtimes" / "python.exe")):
        assert _dll_directory() == str(frozen)
