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
    config.set_setting("check_updates", False)
    assert updater.check_choice() is False
    config.set_setting("check_updates", True)
    assert updater.check_choice() is True


def test_startup_check_makes_no_request_until_the_user_opts_in(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    assert updater.should_check_on_startup() is False
    config.set_setting("check_updates", False)
    assert updater.should_check_on_startup() is False
    config.set_setting("check_updates", True)
    assert updater.should_check_on_startup() is True
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert updater.should_check_on_startup() is False


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


def test_launch_installer_refuses_an_unverified_file(tmp_path):
    path = tmp_path / "LyricLoom-Setup.exe"
    path.write_bytes(b"not downloaded by LyricLoom")
    with pytest.raises(RuntimeError, match="did not download and verify"):
        updater.launch_installer(path)
