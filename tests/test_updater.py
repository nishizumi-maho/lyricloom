from lyricloom import updater


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
