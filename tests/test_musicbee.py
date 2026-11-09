from pathlib import Path

import pytest

from lyricloom import musicbee


def _source(root: Path) -> Path:
    files = {
        "mb_StarryKaraoke.dll": b"new plugin",
        "StarryKaraoke.Recorder.exe": b"recorder",
        "StarryKaraoke.Recorder.exe.config": b"<configuration/>",
        "RomajiCore.dll": b"new core",
        "LibNMeCab.dll": b"new mecab",
        "RomajiLyrics/IpaDic/japanese.txt": b"new dictionary",
        "RomajiLyrics/IpaDic/mecab.txt": b"new mecab dictionary",
        "StarryKaraoke/README.md": b"readme",
    }
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


def test_install_plugin_replaces_plugin_files_and_keeps_a_newer_shared_dll(tmp_path):
    source = _source(tmp_path / "bundle")
    destination = tmp_path / "Plugins"
    (destination / "RomajiLyrics" / "IpaDic").mkdir(parents=True)
    (destination / "mb_StarryKaraoke.dll").write_bytes(b"old plugin")
    (destination / "RomajiCore.dll").write_bytes(b"old core")
    (destination / "LibNMeCab.dll").write_bytes(b"old mecab")
    (destination / "RomajiLyrics" / "IpaDic" / "japanese.txt").write_bytes(b"old dictionary")

    versions = {
        source / "RomajiCore.dll": "2.0.0.0",
        destination / "RomajiCore.dll": "1.0.0.0",
        source / "LibNMeCab.dll": "1.0.0.0",
        destination / "LibNMeCab.dll": "2.0.0.0",
        source / "mb_StarryKaraoke.dll": "2.1.0.0",
        destination / "mb_StarryKaraoke.dll": "1.0.0.0",
    }

    result = musicbee.install_plugin(
        source, destination, running=lambda: False, version_of=lambda path: versions.get(path, ""))

    assert (destination / "mb_StarryKaraoke.dll").read_bytes() == b"new plugin"
    assert (destination / "RomajiCore.dll").read_bytes() == b"new core"
    assert (destination / "LibNMeCab.dll").read_bytes() == b"old mecab"
    assert (destination / "RomajiLyrics" / "IpaDic" / "japanese.txt").read_bytes() == b"old dictionary"
    # A file that was missing is copied even though it lives in the dictionary folder.
    assert (destination / "RomajiLyrics" / "IpaDic" / "mecab.txt").read_bytes() == b"new mecab dictionary"
    assert (destination / "StarryKaraoke" / "README.md").is_file()
    assert Path("LibNMeCab.dll") in result.skipped
    assert Path("RomajiLyrics/IpaDic/japanese.txt") in result.skipped
    assert Path("RomajiCore.dll") in result.copied


def test_install_plugin_refuses_while_musicbee_is_running(tmp_path):
    source = _source(tmp_path / "bundle")
    destination = tmp_path / "Plugins"
    with pytest.raises(musicbee.MusicBeeRunning, match="Close MusicBee and try again"):
        musicbee.install_plugin(source, destination, running=lambda: True)
    assert not destination.exists()


def test_install_plugin_reports_a_missing_bundle(tmp_path):
    with pytest.raises(musicbee.PluginMissing):
        musicbee.install_plugin(tmp_path / "missing", tmp_path / "Plugins",
                                running=lambda: False)


def test_install_plugin_refuses_paths_outside_the_destination(tmp_path):
    destination = tmp_path / "Plugins"
    with pytest.raises(musicbee.MusicBeeError, match="outside"):
        musicbee._safe_target(destination, Path("..") / "evil.txt")


def test_detect_musicbee_reads_the_plugins_folder_and_version(tmp_path, monkeypatch):
    appdata = tmp_path / "Roaming"
    plugins = appdata / "MusicBee" / "Plugins"
    plugins.mkdir(parents=True)
    (plugins / musicbee.PLUGIN_DLL).write_bytes(b"not a real PE")
    monkeypatch.setattr(musicbee, "file_version", lambda path: "2.1.0.0")
    status = musicbee.detect_musicbee(appdata=appdata, program_files=[],
                                      registry_evidence=lambda: [])
    assert status.detected is True
    assert status.plugin_installed is True
    assert status.plugin_version == "2.1.0.0"
    assert "installed" in status.summary


def test_detect_musicbee_uses_registry_and_program_files_marks(tmp_path):
    appdata = tmp_path / "Roaming"
    program_files = tmp_path / "Program Files"
    (program_files / "MusicBee").mkdir(parents=True)
    (program_files / "MusicBee" / musicbee.MUSICBEE_EXE).write_bytes(b"exe")
    status = musicbee.detect_musicbee(appdata=appdata, program_files=[program_files],
                                      registry_evidence=lambda: ["registry Software\\MusicBee"])
    assert status.detected is True
    assert status.plugin_installed is False
    assert any("registry" in item for item in status.evidence)
    assert any("MusicBee.exe" in item for item in status.evidence)


def test_version_comparison_is_numeric():
    assert musicbee.version_tuple("2.1.0.0") == (2, 1, 0, 0)
    assert musicbee.newer_version("2.0.0.0", "1.9.9.9")
    assert not musicbee.newer_version("1.0", "1.0.0.0")
    assert not musicbee.newer_version("", "1.0")
