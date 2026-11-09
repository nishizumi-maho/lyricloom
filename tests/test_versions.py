"""The released version is copied into packaging files; keep them in sync."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from lyricloom import VERSION

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_packaging_versions_match_lyricloom_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)

    pyproject = tomllib.loads(_read("pyproject.toml"))
    assert pyproject["project"]["version"] == VERSION

    version_info = _read("packaging/windows/version_info.txt")
    major, minor, patch = (int(part) for part in VERSION.split("."))
    numeric = f"({major}, {minor}, {patch}, 0)"
    assert f"filevers={numeric}" in version_info
    assert f"prodvers={numeric}" in version_info
    assert f"StringStruct('FileVersion', '{VERSION}')" in version_info
    assert f"StringStruct('ProductVersion', '{VERSION}')" in version_info

    installer = _read("packaging/windows/LyricLoom.iss")
    fallback = re.search(r'^\s*#define MyAppVersion "([^"]+)"', installer, re.MULTILINE)
    assert fallback is not None
    assert fallback.group(1) == VERSION


def test_plugin_projects_share_the_plugin_version():
    def project_version(relative: str) -> str:
        match = re.search(r"<Version>([^<]+)</Version>", _read(relative))
        assert match is not None, f"{relative} has no <Version>"
        return match.group(1).strip()

    plugin = project_version("musicbee/src/StarryKaraoke/StarryKaraoke.csproj")
    recorder = project_version("musicbee/src/StarryKaraoke.Recorder/StarryKaraoke.Recorder.csproj")
    assert re.fullmatch(r"\d+\.\d+\.\d+", plugin)
    assert recorder == plugin
