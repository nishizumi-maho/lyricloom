import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricloom import config  # noqa: E402
from lyricloom.app import dialogs  # noqa: E402
from lyricloom.app.dialogs import SettingsDialog, validate_folder  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _warnings(monkeypatch):
    seen = []
    monkeypatch.setattr(dialogs.QMessageBox, "warning",
                        lambda parent, title, text: seen.append((title, text)))
    return seen


def test_folder_text_must_not_be_empty():
    path, error = validate_folder("Music library", "   ", must_exist=True)
    assert path is None and "Music library" in error and "empty" in error


def test_dot_is_not_a_library(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path, error = validate_folder("Music library", ".", must_exist=True)
    assert path is None and "Music library" in error


def test_a_file_is_not_a_folder(tmp_path):
    file = tmp_path / "song.flac"
    file.write_bytes(b"x")
    path, error = validate_folder("Vocals cache", str(file), must_exist=False, create=True)
    assert path is None and "not a folder" in error


def test_missing_folders_are_created_only_when_allowed(tmp_path):
    missing = tmp_path / "Vocals"
    path, error = validate_folder("Vocals cache", str(missing), must_exist=False, create=False)
    assert path is None and "does not exist" in error
    path, error = validate_folder("Vocals cache", str(missing), must_exist=False, create=True)
    assert error is None and path == missing.resolve() and missing.is_dir()


def test_unwritable_folder_is_rejected_with_its_name(tmp_path, monkeypatch):
    def denied(self, *args, **kwargs):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(Path, "write_text", denied)
    path, error = validate_folder("Music library", str(tmp_path), must_exist=True)
    assert path is None and "Music library" in error and "not writable" in error


def test_settings_dialog_rejects_an_empty_library(app, tmp_path, monkeypatch):
    seen = _warnings(monkeypatch)
    dialog = SettingsDialog()
    dialog.library.setText("   ")
    dialog.vocals.setText(str(tmp_path / "Vocals"))
    dialog.work.setText(str(tmp_path / "Work"))
    dialog._save()
    assert seen and seen[0][0] == "Music library"
    assert not config.SETTINGS_FILE.exists()
    dialog.close()


def test_settings_dialog_rejects_an_empty_vocals_field(app, tmp_path, monkeypatch):
    seen = _warnings(monkeypatch)
    dialog = SettingsDialog()
    dialog.library.setText(str(tmp_path))
    dialog.vocals.setText("  ")
    dialog.work.setText(str(tmp_path / "Work"))
    dialog._save()
    assert seen and seen[0][0] == "Vocals cache"
    assert not config.SETTINGS_FILE.exists()
    dialog.close()


def test_settings_dialog_saves_valid_folders_and_creates_the_caches(app, tmp_path, monkeypatch):
    seen = _warnings(monkeypatch)
    library = tmp_path / "Library"
    library.mkdir()
    vocals, work = tmp_path / "Vocals", tmp_path / "Work"
    dialog = SettingsDialog()
    dialog.library.setText(str(library))
    dialog.vocals.setText(str(vocals))
    dialog.work.setText(str(work))
    dialog._save()
    assert not seen
    assert config.library_root() == library.resolve()
    assert config.vocals_root() == vocals.resolve()
    assert vocals.is_dir() and work.is_dir()
    dialog.close()


def test_a_write_error_saving_settings_is_shown(app, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(dialogs.QMessageBox, "critical",
                        lambda parent, title, text: seen.append((title, text)))
    library = tmp_path / "Library"
    library.mkdir()
    dialog = SettingsDialog()
    dialog.library.setText(str(library))
    dialog.vocals.setText(str(tmp_path / "Vocals"))
    dialog.work.setText(str(tmp_path / "Work"))

    def denied(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(dialogs.config, "update_settings", denied)
    dialog._save()
    assert seen and "No space left on device" in seen[0][1]
    dialog.close()
