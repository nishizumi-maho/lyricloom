from lyricloom import runner


def test_forget_sync_deletes_only_what_lyrics_boca_wrote(tmp_path):
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"")
    (tmp_path / "song.lrc").write_text("[re:LyricLoom 1.0.0]\n[00:01.00]<00:01.00>a<00:02.00>\n", encoding="utf-8")
    (tmp_path / "song.japanese.lrc").write_text("x", encoding="utf-8")
    (tmp_path / "song.romaji.lrc").write_text("x", encoding="utf-8")
    (tmp_path / "song.original.lrc").write_text("[00:01.00]a\n", encoding="utf-8")

    removed = runner.forget_sync(audio)

    assert {p.name for p in removed} == {"song.lrc", "song.japanese.lrc", "song.romaji.lrc"}
    assert (tmp_path / "song.original.lrc").exists()


def test_forget_sync_keeps_lrc_from_elsewhere(tmp_path):
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"")
    lrc = tmp_path / "song.lrc"
    lrc.write_text("[re:Acervo]\n[00:01.00]a\n", encoding="utf-8")
    assert runner.forget_sync(audio) == []
    assert lrc.exists()
