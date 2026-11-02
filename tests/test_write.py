from lyricloom.lrc import parse_lrc
from lyricloom.model import Line, LrcDoc, Segment
from lyricloom.stages.write import write_lrc

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
