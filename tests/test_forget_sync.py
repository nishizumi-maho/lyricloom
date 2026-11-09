from lyricloom import runner


def test_forget_sync_deletes_only_what_lyrics_boca_wrote(tmp_path):
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"")
    (tmp_path / "song.lrc").write_text("[re:LyricLoom 1.0.0]\n[00:01.00]<00:01.00>a<00:02.00>\n", encoding="utf-8")
    (tmp_path / "song.japanese.lrc").write_text("[re:LyricLoom 1.0.0]\n[00:01.00]a\n", encoding="utf-8")
    (tmp_path / "song.romaji.lrc").write_text("[re:LyricLoom 1.0.0]\n[00:01.00]a\n", encoding="utf-8")
    (tmp_path / "song.original.lrc").write_text("[00:01.00]a\n", encoding="utf-8")

    moved = runner.forget_sync(audio)

    assert {p.name for p in moved} == {"song.lrc", "song.japanese.lrc", "song.romaji.lrc"}
    assert not (tmp_path / "song.lrc").exists()
    assert all(backup.exists() for backup in moved.values())
    assert (tmp_path / "song.original.lrc").exists()
    runner.restore_sync(moved)
    assert (tmp_path / "song.lrc").read_text(encoding="utf-8").startswith("[re:LyricLoom")


def test_forget_sync_keeps_lrc_from_elsewhere(tmp_path):
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"")
    lrc = tmp_path / "song.lrc"
    lrc.write_text("[re:Acervo]\n[00:01.00]a\n", encoding="utf-8")
    assert runner.forget_sync(audio) == {}
    assert lrc.exists()


def test_forget_sync_keeps_a_romaji_sidecar_from_another_tool(tmp_path):
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"")
    (tmp_path / "song.lrc").write_text("[re:LyricLoom 1.0.0]\n[00:01.00]a\n", encoding="utf-8")
    other = tmp_path / "song.romaji.lrc"
    other.write_text("[re:Some other tool]\n[00:01.00]a\n", encoding="utf-8")
    moved = runner.forget_sync(audio)
    assert {p.name for p in moved} == {"song.lrc"}
    assert other.exists()
