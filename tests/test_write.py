import os

import pytest

from lyricloom.lrc import parse_lrc
from lyricloom.model import Candidate, Line, LrcDoc, Segment
from lyricloom.stages import write as write_mod
from lyricloom.stages.write import write_lrc, write_lyrics, write_original

DOC = LrcDoc({"re": "LyricLoom 1.0"}, [Line(1000, [Segment("試験", 1000, 1400)])])


def test_backup_never_overwrites(tmp_path):
    audio = tmp_path / "x.flac"
    audio.write_bytes(b"a")
    (tmp_path / "x.lrc").write_text("handmade", encoding="utf-8")
    (tmp_path / "x.lrc.bak").write_text("older backup", encoding="utf-8")
    out = write_lrc(audio, DOC)
    assert out == tmp_path / "x.lrc"
    assert (tmp_path / "x.lrc.bak").read_text(encoding="utf-8") == "older backup"
    assert (tmp_path / "x.lrc.bak1").read_text(encoding="utf-8") == "handmade"
    assert parse_lrc(out.read_text(encoding="utf-8")).lines[0].text == "試験"


def test_first_backup_is_bak(tmp_path):
    audio = tmp_path / "x.flac"
    audio.write_bytes(b"a")
    (tmp_path / "x.lrc").write_text("old", encoding="utf-8")
    write_lrc(audio, DOC)
    assert (tmp_path / "x.lrc.bak").read_text(encoding="utf-8") == "old"


def test_write_is_utf8_no_bom(tmp_path):
    audio = tmp_path / "x.flac"
    audio.write_bytes(b"a")
    raw = write_lrc(audio, DOC).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert "試験".encode("utf-8") in raw
    assert not list(tmp_path.glob("*.tmp"))


def test_a_kill_between_backup_and_replace_leaves_the_old_lrc(tmp_path, monkeypatch):
    """The previous .lrc is copied, not moved, so a crash at the replace still leaves a valid file."""
    audio = tmp_path / "x.flac"
    audio.write_bytes(b"a")
    lrc = tmp_path / "x.lrc"
    old = "handmade, not ours\n"
    lrc.write_text(old, encoding="utf-8")

    def crash(src, dst):
        assert str(src).endswith(".tmp") and dst == lrc      # only the final replace fails
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(write_mod.os, "replace", crash)
    with pytest.raises(OSError):
        write_lrc(audio, DOC)

    assert lrc.read_text(encoding="utf-8") == old
    assert (tmp_path / "x.lrc.bak").read_text(encoding="utf-8") == old
    assert os.path.exists(tmp_path / "x.lrc.tmp")


def test_write_original_keeps_a_hand_corrected_copy_as_bak(tmp_path):
    """FR-A-05: the official lyric is user-editable, so a rewrite must not destroy it."""
    audio = tmp_path / "x.flac"
    audio.write_bytes(b"a")
    official = Candidate("letras", "old words")
    write_original(audio, {"ti": "T", "ar": "A"}, official)
    original = tmp_path / "x.original.lrc"
    original.write_text("hand-corrected words\n", encoding="utf-8")

    write_original(audio, {"ti": "T", "ar": "A"}, official)
    assert (tmp_path / "x.original.lrc.bak").read_text(encoding="utf-8") == "hand-corrected words\n"


def test_japanese_variants_keep_a_backup(tmp_path):
    """FR-A-05: the script variants are user-visible files and get the same .bak copy."""
    audio = tmp_path / "x.flac"
    audio.write_bytes(b"a")
    doc = LrcDoc({"re": "LyricLoom 2.1", "#language": "ja"},
                 [Line(1000, [Segment("試験", 1000, 1400)])])
    write_lyrics(audio, doc, lang="ja")
    old_japanese = (tmp_path / "x.japanese.lrc").read_bytes()
    old_romaji = (tmp_path / "x.romaji.lrc").read_bytes()

    write_lyrics(audio, doc, lang="ja")
    assert (tmp_path / "x.japanese.lrc.bak").read_bytes() == old_japanese
    assert (tmp_path / "x.romaji.lrc.bak").read_bytes() == old_romaji


def test_write_original_sanitizes_title_and_artist(tmp_path):
    """FR-A-06: a newline or ] in the tags must not turn into phantom lyric lines."""
    audio = tmp_path / "x.flac"
    audio.write_bytes(b"a")
    path = write_original(audio, {"ti": "Line\n[00:01.00]fake]", "ar": "Artist]X"},
                          Candidate("letras", "words"))
    doc = parse_lrc(path.read_text(encoding="utf-8"))
    assert "\n" not in doc.meta["ti"] and "]" not in doc.meta["ti"]
    assert doc.meta["ar"] == "Artist X"
    assert doc.lines == []
