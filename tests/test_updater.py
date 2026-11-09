import hashlib
from pathlib import Path

import httpx
import pytest

from lyricloom import config, updater

PAYLOAD = b"installer bytes"
SHA = hashlib.sha256(PAYLOAD).hexdigest()
ASSET_URL = "https://github.com/nishizumi-maho/lyricloom/releases/download/v2.1.1/LyricLoom-Setup.exe"


def _info(**overrides) -> updater.UpdateInfo:
    values = {
        "version": "2.1.1",
        "tag": "v2.1.1",
        "page_url": "https://github.com/nishizumi-maho/lyricloom/releases/tag/v2.1.1",
        "notes": "",
        "asset_name": "LyricLoom-Setup.exe",
        "asset_url": ASSET_URL,
        "asset_size": len(PAYLOAD),
        "asset_sha256": SHA,
        "checksum_url": "",
    }
    values.update(overrides)
    return updater.UpdateInfo(**values)


def _mock_client(handler):
    return lambda timeout: httpx.Client(transport=httpx.MockTransport(handler))


def test_version_comparison_handles_tags_and_prereleases():
    assert updater.is_newer("2.1.1")
    assert updater.is_newer("v2.2.0-beta.1")          # next minor, even as a prerelease
    assert not updater.is_newer("2.1.0-beta.1")       # same numeric version as this build
    assert not updater.is_newer("2.1.0")
    assert not updater.is_newer("2.0.9")


def test_checksum_parser_accepts_sha256sum_and_bsd_output():
    text = "abc123  LyricLoom-Setup.exe\n"
    assert updater._checksum_from_text(text, "LyricLoom-Setup.exe") == "abc123"
    assert updater._checksum_from_text("abc123 *LyricLoom-Setup.exe", "LyricLoom-Setup.exe") == "abc123"
    assert updater._checksum_from_text("abc123", "LyricLoom-Setup.exe") == "abc123"


def test_update_check_choice_is_absent_until_the_user_decides(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    assert updater.check_choice() is None
    assert updater.check_enabled() is True          # absent means the owner's default: on
    config.set_setting("check_updates", False)
    assert updater.check_choice() is False
    assert updater.check_enabled() is False
    config.set_setting("check_updates", True)
    assert updater.check_choice() is True
    assert updater.check_enabled() is True


def test_startup_check_is_on_by_default_and_false_turns_it_off(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    assert updater.should_check_on_startup() is True
    config.set_setting("check_updates", False)
    assert updater.should_check_on_startup() is False
    config.set_setting("check_updates", True)
    assert updater.should_check_on_startup() is True
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert updater.should_check_on_startup() is False
    assert updater.should_check_automatically() is False


def test_install_mode_defaults_to_auto_and_rejects_unknown_values(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    assert updater.install_mode() == "auto"
    config.set_setting("update_install", "ask")
    assert updater.install_mode() == "ask"
    config.set_setting("update_install", "notify")
    assert updater.install_mode() == "notify"
    config.set_setting("update_install", "nonsense")
    assert updater.install_mode() == "auto"


def test_a_skipped_version_is_not_offered_again_until_a_newer_one(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    assert updater.is_skipped("2.1.1") is False
    updater.skip_version("2.1.1")
    assert updater.skipped_version() == "2.1.1"
    assert updater.is_skipped("2.1.1") is True
    assert updater.is_skipped("2.1.0") is True
    assert updater.is_skipped("2.1.2") is False


def test_stale_update_files_are_deleted_on_start(tmp_path, monkeypatch):
    updates = tmp_path / "updates"
    updates.mkdir()
    stale = updates / "LyricLoom-Setup.exe"
    stale.write_bytes(b"left over")
    part = updates / "download.part"
    part.write_bytes(b"partial")
    keep_dir = updates / "not-a-file"
    keep_dir.mkdir()
    monkeypatch.setattr(updater, "UPDATE_DIR", updates)
    monkeypatch.setattr(updater, "_VERIFIED", {})
    updater.cleanup_stale_downloads()
    assert not stale.exists() and not part.exists()
    assert keep_dir.is_dir()


def test_download_refuses_a_url_that_is_not_our_release(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "UPDATE_DIR", tmp_path / "updates")
    info = _info(asset_url="https://evil.example/LyricLoom-Setup.exe")
    with pytest.raises(RuntimeError, match="not this project's GitHub release"):
        updater.download(info)
    assert not (tmp_path / "updates" / info.asset_name).exists()


def test_download_refuses_a_missing_checksum_without_a_request(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "UPDATE_DIR", tmp_path / "updates")

    def no_request(timeout):
        raise AssertionError("no request may be made when the checksum is missing")

    monkeypatch.setattr(updater, "_client", no_request)
    with pytest.raises(RuntimeError, match="does not publish a SHA-256"):
        updater.download(_info(asset_sha256=""))
    assert not (tmp_path / "updates" / "LyricLoom-Setup.exe").exists()


def test_download_refuses_a_checksum_from_another_location(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "UPDATE_DIR", tmp_path / "updates")
    info = _info(asset_sha256="", checksum_url="https://evil.example/LyricLoom-Setup.exe.sha256")
    with pytest.raises(RuntimeError, match="checksum from outside"):
        updater.download(info)


def test_download_refuses_a_wrong_checksum(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "UPDATE_DIR", tmp_path / "updates")
    monkeypatch.setattr(updater, "_client", _mock_client(lambda request: httpx.Response(200, content=PAYLOAD)))
    with pytest.raises(RuntimeError, match="checksum does not match"):
        updater.download(_info(asset_sha256="0" * 64))
    assert not (tmp_path / "updates" / "LyricLoom-Setup.exe").exists()
    assert not (tmp_path / "updates" / "LyricLoom-Setup.exe.part").exists()


def test_download_does_not_reuse_a_predictable_part_name(tmp_path, monkeypatch):
    updates = tmp_path / "updates"
    updates.mkdir()
    planted = updates / "LyricLoom-Setup.exe.part"
    planted.write_bytes(b"planted earlier")
    monkeypatch.setattr(updater, "UPDATE_DIR", updates)
    monkeypatch.setattr(updater, "_client", _mock_client(lambda request: httpx.Response(200, content=PAYLOAD)))
    path = updater.download(_info())
    assert path.read_bytes() == PAYLOAD
    assert planted.read_bytes() == b"planted earlier"
    assert sorted(p.name for p in updates.iterdir()) == ["LyricLoom-Setup.exe", "LyricLoom-Setup.exe.part"]


def test_download_does_not_follow_a_planted_part_symlink(tmp_path, monkeypatch):
    updates = tmp_path / "updates"
    updates.mkdir()
    victim = tmp_path / "victim.bin"
    victim.write_bytes(b"do not touch")
    planted = updates / "LyricLoom-Setup.exe.part"
    try:
        planted.symlink_to(victim)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available here")
    monkeypatch.setattr(updater, "UPDATE_DIR", updates)
    monkeypatch.setattr(updater, "_client", _mock_client(lambda request: httpx.Response(200, content=PAYLOAD)))
    path = updater.download(_info())
    assert path.read_bytes() == PAYLOAD
    assert victim.read_bytes() == b"do not touch"


def test_download_accepts_a_matching_published_checksum(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "UPDATE_DIR", tmp_path / "updates")
    monkeypatch.setattr(updater, "_client", _mock_client(lambda request: httpx.Response(200, content=PAYLOAD)))
    path = updater.download(_info())
    assert path.read_bytes() == PAYLOAD
    assert updater._VERIFIED[path.resolve()] == SHA


def test_download_accepts_the_checksum_asset_from_the_same_release(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "UPDATE_DIR", tmp_path / "updates")
    checksum_url = ASSET_URL + ".sha256"

    def handler(request):
        if str(request.url) == checksum_url:
            return httpx.Response(200, text=f"{SHA}  LyricLoom-Setup.exe\n")
        return httpx.Response(200, content=PAYLOAD)

    monkeypatch.setattr(updater, "_client", _mock_client(handler))
    path = updater.download(_info(asset_sha256="", checksum_url=checksum_url))
    assert path.read_bytes() == PAYLOAD


def test_download_follows_only_github_asset_redirects(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "UPDATE_DIR", tmp_path / "updates")
    cdn = "https://objects.githubusercontent.com/release-assets/12345"

    def handler(request):
        if str(request.url) == ASSET_URL:
            return httpx.Response(302, headers={"location": cdn})
        assert str(request.url) == cdn
        return httpx.Response(200, content=PAYLOAD)

    monkeypatch.setattr(updater, "_client", _mock_client(handler))
    assert updater.download(_info()).read_bytes() == PAYLOAD


def test_download_refuses_a_redirect_outside_github(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "UPDATE_DIR", tmp_path / "updates")
    monkeypatch.setattr(updater, "_client", _mock_client(
        lambda request: httpx.Response(302, headers={"location": "https://evil.example/file.exe"})))
    with pytest.raises(RuntimeError, match="refusing to fetch"):
        updater.download(_info())


def test_check_refuses_an_asset_outside_the_release(monkeypatch):
    release = {
        "tag_name": "v2.1.1",
        "html_url": "https://github.com/nishizumi-maho/lyricloom/releases/tag/v2.1.1",
        "body": "",
        "assets": [{"name": "LyricLoom-Setup.exe", "browser_download_url": "https://evil.example/setup.exe",
                    "size": 1, "digest": "sha256:" + SHA}],
    }
    monkeypatch.setattr(updater, "_get_json", lambda url: release)
    with pytest.raises(RuntimeError, match="outside its own release assets"):
        updater.check()


def test_check_returns_the_linux_tarball_when_there_is_no_installer(monkeypatch):
    release = {
        "tag_name": "v2.1.1",
        "html_url": "https://github.com/nishizumi-maho/lyricloom/releases/tag/v2.1.1",
        "body": "notes",
        "assets": [{"name": "LyricLoom-2.1.1-linux-x86_64.tar.gz",
                    "browser_download_url": "https://github.com/nishizumi-maho/lyricloom/releases/"
                                            "download/v2.1.1/LyricLoom-2.1.1-linux-x86_64.tar.gz",
                    "size": 1}],
    }
    monkeypatch.setattr(updater, "_get_json", lambda url: release)
    monkeypatch.setattr(updater.sys, "platform", "linux")
    info = updater.check()
    assert info is not None
    assert info.asset_url == ""
    assert info.tarball_name == "LyricLoom-2.1.1-linux-x86_64.tar.gz"


def test_release_page_url_falls_back_to_this_projects_release_page():
    evil = _info(page_url="https://evil.example/release")
    assert updater.release_page_url(evil) == updater.RELEASES_PAGE
    good = _info(page_url="https://github.com/nishizumi-maho/lyricloom/releases/tag/v2.1.1")
    assert updater.release_page_url(good) == good.page_url


def test_whats_new_opens_only_the_validated_release_url(monkeypatch):
    opened = []
    monkeypatch.setattr(updater.webbrowser, "open", lambda url: opened.append(url))
    updater.open_release_page(_info(page_url="https://evil.example/release"))
    updater.open_release_page(_info())
    assert opened == [updater.RELEASES_PAGE,
                      "https://github.com/nishizumi-maho/lyricloom/releases/tag/v2.1.1"]


def test_musicbee_process_detection_reads_tasklist(monkeypatch):
    class Result:
        stdout = '"MusicBee.exe","4242","Console","1","120,000 K"\r\n'

    monkeypatch.setattr(updater.sys, "platform", "win32")
    monkeypatch.setattr(updater.subprocess, "run", lambda *args, **kwargs: Result())
    assert updater.musicbee_running() is True

    Result.stdout = "INFO: No tasks are running which match the specified criteria.\r\n"
    assert updater.musicbee_running() is False


def _verified_installer(tmp_path, monkeypatch):
    path = tmp_path / "LyricLoom-Setup.exe"
    path.write_bytes(PAYLOAD)
    monkeypatch.setattr(updater, "_VERIFIED", {path.resolve(): SHA})
    calls = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda argv, **kwargs: calls.append((argv, kwargs)))
    return path, calls


def test_silent_installer_argv_relaunches_and_skips_plugins(tmp_path, monkeypatch):
    path, calls = _verified_installer(tmp_path, monkeypatch)
    monkeypatch.setattr(updater, "musicbee_running", lambda: False)
    updater.launch_installer(path, silent=True, relaunch=True, skip_plugin=False)
    assert calls == [([str(path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELAUNCH=1"],
                      {"close_fds": True})]


def test_silent_installer_argv_never_closes_musicbee(tmp_path, monkeypatch):
    path, calls = _verified_installer(tmp_path, monkeypatch)
    monkeypatch.setattr(updater, "musicbee_running", lambda: True)
    updater.launch_installer(path, silent=True, relaunch=False, skip_plugin=False)
    argv, _kwargs = calls[0]
    assert argv == [str(path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                    "/NOCLOSEAPPLICATIONS", "/SKIPPLUGIN=1"]
    assert updater.take_plugin_skip_notice() is True
    assert updater.take_plugin_skip_notice() is False


def test_silent_installer_argv_can_skip_the_plugin_without_musicbee(tmp_path, monkeypatch):
    path, calls = _verified_installer(tmp_path, monkeypatch)
    monkeypatch.setattr(updater, "musicbee_running", lambda: False)
    updater.launch_installer(path, silent=True, relaunch=False, skip_plugin=True)
    assert calls[0][0][-1] == "/SKIPPLUGIN=1"


def test_launch_installer_refuses_an_unverified_file(tmp_path):
    path = tmp_path / "LyricLoom-Setup.exe"
    path.write_bytes(b"not downloaded by LyricLoom")
    with pytest.raises(RuntimeError, match="did not download and verify"):
        updater.launch_installer(path, silent=True, relaunch=True, skip_plugin=False)


def test_silent_installer_refuses_an_unverified_file_before_any_process(tmp_path, monkeypatch):
    path = tmp_path / "LyricLoom-Setup.exe"
    path.write_bytes(b"not downloaded by LyricLoom")

    def no_process(*args, **kwargs):
        raise AssertionError("an unverified installer must never be launched")

    monkeypatch.setattr(updater.subprocess, "Popen", no_process)
    with pytest.raises(RuntimeError, match="did not download and verify"):
        updater.launch_installer(path, silent=True, relaunch=False, skip_plugin=False)
