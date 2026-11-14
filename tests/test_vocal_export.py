"""The user's own copy of the isolated vocals: <song>_vocal.flac."""
import os
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricloom import config, runner, vocal_export  # noqa: E402
from lyricloom.app import dialogs  # noqa: E402
from lyricloom.app import main as main_module  # noqa: E402
from lyricloom.app.dialogs import SettingsDialog  # noqa: E402
from lyricloom.app.main import MainWindow  # noqa: E402
from lyricloom.stages import separate as sep_mod  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def library(tmp_path, monkeypatch):
    root = tmp_path / "Library"
    root.mkdir()
    monkeypatch.setattr("lyricloom.config.LIBRARY_ROOT", root)
    return root


def _tone(path: Path, subtype: str = "PCM_16", seconds: float = 0.5) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(44100 * seconds)) / 44100
    sig = 0.3 * np.sin(2 * np.pi * 440 * t)
    sf.write(str(path), np.stack([sig, -sig], axis=1).astype("float32"), 44100, subtype=subtype)
    return path


def _song(library: Path, name: str = "01 - Song.flac") -> Path:
    return _tone(library / "Artist" / "Album" / name)


# --------------------------------------------------------------------------- where it goes


def test_the_export_is_off_by_default(library):
    audio = _song(library)
    assert config.vocal_export_mode() == "off"
    assert vocal_export.target(audio) is None
    assert vocal_export.export(audio, audio) is None
    assert not (audio.parent / "01 - Song_vocal.flac").exists()


def test_beside_puts_the_copy_next_to_the_song(library):
    audio = library / "Artist" / "Album" / "01 - Song.mp3"      # any format; only the name counts
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"mp3")
    config.update_settings({"vocal_export": "beside"})
    assert vocal_export.target(audio) == audio.parent / "01 - Song_vocal.flac"


def test_a_folder_mirrors_the_library_layout_and_takes_outside_songs_flat(library, tmp_path):
    audio = _song(library)
    outside = _tone(tmp_path / "Downloads" / "loose.wav")
    config.update_settings({"vocal_export": "folder",
                            "vocal_export_folder": str(tmp_path / "Vocals out")})
    assert vocal_export.target(audio) == (tmp_path / "Vocals out" / "Artist" / "Album"
                                          / "01 - Song_vocal.flac")
    assert vocal_export.target(outside) == tmp_path / "Vocals out" / "loose_vocal.flac"


def test_the_folder_mode_without_a_folder_exports_nothing(library):
    config.update_settings({"vocal_export": "folder", "vocal_export_folder": ""})
    assert vocal_export.target(_song(library)) is None


def test_an_unknown_mode_is_off(library):
    config.update_settings({"vocal_export": "everywhere"})
    assert config.vocal_export_mode() == "off"


# --------------------------------------------------------------------------- the file


def test_the_copy_is_lossless_flac_tagged_as_ours(library, tmp_path):
    audio = _song(library)
    vocals = _tone(tmp_path / "work" / "vocals.wav", subtype="PCM_24")
    config.update_settings({"vocal_export": "beside"})
    exported = vocal_export.export(audio, vocals)
    assert exported == audio.parent / "01 - Song_vocal.flac"
    info = sf.info(str(exported))
    assert (info.format, info.subtype, info.channels) == ("FLAC", "PCM_24", 2)
    assert np.array_equal(sf.read(str(exported), dtype="int32")[0],
                          sf.read(str(vocals), dtype="int32")[0])
    assert vocal_export.is_ours(exported)
    from mutagen.flac import FLAC

    assert FLAC(str(exported))["title"] == ["01 - Song (vocals)"]
    assert not list(audio.parent.glob("*.part"))


def test_a_file_of_that_name_that_is_not_ours_is_never_replaced(library, tmp_path):
    audio = _song(library)
    mine = audio.parent / "01 - Song_vocal.flac"
    sf.write(str(mine), sf.read(str(audio))[0], 44100, format="FLAC")   # the user's own acapella
    before = mine.read_bytes()
    config.update_settings({"vocal_export": "beside"})
    with pytest.raises(vocal_export.ExportRefused, match="was not written by LyricLoom"):
        vocal_export.export(audio, _tone(tmp_path / "vocals.wav"))
    assert mine.read_bytes() == before


def test_our_own_copy_is_replaced_after_a_new_separation_and_kept_when_only_reused(library,
                                                                                    tmp_path):
    audio = _song(library)
    config.update_settings({"vocal_export": "beside"})
    first = vocal_export.export(audio, _tone(tmp_path / "a.wav", seconds=0.5))
    longer = _tone(tmp_path / "b.wav", seconds=1.0)
    # The vocals were only read back from the cache: the existing copy is current.
    assert vocal_export.export(audio, longer, fresh=False) == first
    assert sf.info(str(first)).duration == pytest.approx(0.5, abs=0.01)
    # A new separation replaces it.
    vocal_export.export(audio, longer, fresh=True)
    assert sf.info(str(first)).duration == pytest.approx(1.0, abs=0.01)


def test_a_copy_older_than_the_song_is_rewritten_even_when_reused(library, tmp_path):
    audio = _song(library)
    config.update_settings({"vocal_export": "beside"})
    exported = vocal_export.export(audio, _tone(tmp_path / "a.wav", seconds=0.5))
    stamp = exported.stat()
    os.utime(audio, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 5_000_000_000))   # song edited
    vocal_export.export(audio, _tone(tmp_path / "b.wav", seconds=1.0), fresh=False)
    assert sf.info(str(exported)).duration == pytest.approx(1.0, abs=0.01)


# --------------------------------------------------------------------------- the library


def test_the_library_does_not_list_an_exported_vocal_as_a_song(library, tmp_path):
    audio = _song(library)
    config.update_settings({"vocal_export": "beside"})
    vocal_export.export(audio, _tone(tmp_path / "vocals.wav"))
    lone = _tone(library / "Artist" / "Album" / "Lead_vocal.flac")     # a real song of that name
    assert runner.find_audio(library) == sorted([audio, lone])
    assert runner.find_audio(audio.parent / "01 - Song_vocal.flac") == []
    assert runner.find_audio(lone) == [lone]


@pytest.mark.parametrize("name, siblings, expected", [
    ("Song_vocal.flac", {"song.mp3", "song_vocal.flac"}, True),
    ("SONG_VOCAL.FLAC", {"song.flac"}, True),
    ("Song_vocal.flac", {"other.mp3"}, False),
    ("Song_vocal.mp3", {"song.mp3"}, False),          # only our FLAC copies are skipped
    ("_vocal.flac", {".flac"}, False),
    ("Song.flac", {"song.flac"}, False),
])
def test_export_names_are_recognised_only_next_to_their_song(name, siblings, expected):
    assert vocal_export.is_export_name(name, siblings, runner.AUDIO_EXT) is expected


def test_an_export_folder_inside_the_library_is_not_scanned(library):
    audio = _song(library)
    config.update_settings({"vocal_export": "folder",
                            "vocal_export_folder": str(library / "_vocals")})
    vocal_export.export(audio, audio)
    assert (library / "_vocals" / "Artist" / "Album" / "01 - Song_vocal.flac").is_file()
    assert runner.find_audio(library) == [audio]


# --------------------------------------------------------------------------- the stage


def _separator(calls):
    def run(module, payload, python=None, **kw):
        calls.append(payload)
        raw = Path(payload["out_dir"]) / "vocals_raw.wav"
        raw.write_bytes(Path(payload["audio"]).read_bytes())
        return {"vocals": str(raw)}
    return run


def test_separating_a_song_saves_the_copy_and_reusing_the_cache_restores_it(library, tmp_path,
                                                                           monkeypatch):
    audio = _song(library, "01 - Song.wav")
    config.update_settings({"vocal_export": "beside"})
    calls = []
    monkeypatch.setattr(sep_mod, "run_worker", _separator(calls))
    out = sep_mod.separate(audio, tmp_path / "work")
    copy = audio.parent / "01 - Song_vocal.flac"
    assert out["exported"] == str(copy) and copy.is_file() and "export_error" not in out
    # The user deleted the copy; the next run reuses the kept vocals and writes it again.
    copy.unlink()
    again = sep_mod.separate(audio, tmp_path / "work2")
    assert again["device"] == "kept" and len(calls) == 1
    assert again["exported"] == str(copy) and copy.is_file()


def test_a_copy_that_cannot_be_written_never_loses_the_track(library, tmp_path, monkeypatch):
    audio = _song(library, "01 - Song.wav")
    foreign = audio.parent / "01 - Song_vocal.flac"
    sf.write(str(foreign), sf.read(str(audio))[0], 44100, format="FLAC")
    config.update_settings({"vocal_export": "beside"})
    monkeypatch.setattr(sep_mod, "run_worker", _separator([]))
    out = sep_mod.separate(audio, tmp_path / "work")
    assert "was not written by LyricLoom" in out["export_error"] and "exported" not in out
    assert Path(out["vocals"]).is_file() and Path(out["vocals16k"]).is_file()


def test_nothing_is_exported_while_the_option_is_off(library, tmp_path, monkeypatch):
    audio = _song(library, "01 - Song.wav")
    monkeypatch.setattr(sep_mod, "run_worker", _separator([]))
    out = sep_mod.separate(audio, tmp_path / "work")
    assert "exported" not in out and "export_error" not in out
    assert sorted(p.name for p in audio.parent.iterdir()) == ["01 - Song.wav"]


# --------------------------------------------------------------------------- the app


def test_settings_save_the_mode_and_create_the_folder(app, library, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(dialogs.QMessageBox, "warning",
                        lambda parent, title, text: seen.append((title, text)))
    dialog = SettingsDialog()
    try:
        dialog.library.setText(str(library))
        dialog.vocals.setText(str(tmp_path / "Vocals"))
        dialog.work.setText(str(tmp_path / "Work"))
        assert dialog.vocal_export.currentData() == "off" and not dialog.vocal_folder.isEnabled()
        dialog.vocal_export.setCurrentIndex(dialog.vocal_export.findData("folder"))
        assert dialog.vocal_folder.isEnabled()
        dialog._save()                                   # the folder field is still empty
        assert seen and seen[0][0] == "Vocal copies folder"
        assert config.vocal_export_mode() == "off"       # nothing was saved
        dialog.vocal_folder.setText(str(tmp_path / "My vocals"))
        dialog._save()
        assert config.vocal_export_mode() == "folder"
        assert config.vocal_export_folder() == (tmp_path / "My vocals").resolve()
        assert (tmp_path / "My vocals").is_dir()
    finally:
        dialog.close()


def test_settings_save_beside_without_needing_a_folder(app, library, tmp_path):
    dialog = SettingsDialog()
    try:
        dialog.library.setText(str(library))
        dialog.vocals.setText(str(tmp_path / "Vocals"))
        dialog.work.setText(str(tmp_path / "Work"))
        dialog.vocal_export.setCurrentIndex(dialog.vocal_export.findData("beside"))
        dialog._save()
        assert config.vocal_export_mode() == "beside"
    finally:
        dialog.close()


def test_the_menu_action_saves_the_vocals_of_processed_songs(app, library, tmp_path, monkeypatch):
    done = _song(library, "01 - Done.flac")
    pending = _song(library, "02 - Pending.flac")
    vocals = _tone(tmp_path / "kept" / "done.vocals.flac", seconds=0.5)
    monkeypatch.setattr(main_module, "vocal_source",
                        lambda audio: vocals if audio == done else None)
    config.update_settings({"vocal_export": "beside"})
    window = MainWindow(library)
    try:
        window.save_isolated_vocals([done, pending])
        copy = done.parent / "01 - Done_vocal.flac"
        assert copy.is_file() and vocal_export.is_ours(copy)
        assert not (pending.parent / "02 - Pending_vocal.flac").exists()
        message = window.statusBar().currentMessage()
        assert "Saved 1 vocal file(s)" in message
        assert "1 song(s) have no isolated vocals yet" in message
    finally:
        window.dirty = False
        window.close()


def test_the_menu_action_asks_for_a_folder_when_the_copies_are_off(app, library, tmp_path,
                                                                   monkeypatch):
    done = _song(library, "01 - Done.flac")
    vocals = _tone(tmp_path / "kept" / "done.vocals.flac")
    monkeypatch.setattr(main_module, "vocal_source", lambda audio: vocals)
    chosen = tmp_path / "Picked"
    chosen.mkdir()
    monkeypatch.setattr(main_module.QFileDialog, "getExistingDirectory",
                        lambda *args, **kwargs: str(chosen))
    window = MainWindow(library)
    try:
        window.save_isolated_vocals([done])
        assert (chosen / "Artist" / "Album" / "01 - Done_vocal.flac").is_file()
        assert config.vocal_export_mode() == "off"       # a one-off, the setting is unchanged
        # Cancelling the folder dialog does nothing.
        monkeypatch.setattr(main_module.QFileDialog, "getExistingDirectory",
                            lambda *args, **kwargs: "")
        window.save_isolated_vocals([done])
    finally:
        window.dirty = False
        window.close()
