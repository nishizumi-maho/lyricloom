import pytest


@pytest.fixture(autouse=True)
def no_cloud_transcription(tmp_path, monkeypatch):
    """Tests never reach AssemblyAI: an isolated settings file keeps cloud transcription off, and
    a real key in the user's data folder is never read. Tests that need it turn it back on with a
    fake in place of the network call."""
    monkeypatch.setattr("lyricloom.config.ASSEMBLYAI_KEY_FILE", tmp_path / "test-assemblyai.key")
    monkeypatch.delenv("ASSEMBLYAI_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def no_singing_model(monkeypatch):
    """Tests never start the real singing-model venv; tests that route to it use a fake."""
    monkeypatch.setattr("lyricloom.config.MTL_ENABLED", False)


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """The real settings file (chosen library) is never read or written by tests."""
    monkeypatch.setattr("lyricloom.config.SETTINGS_FILE", tmp_path / "test-settings.json")
    monkeypatch.setattr("lyricloom.config.WORK_ROOT", tmp_path / "work")   # caches and scan lists too
    # A test machine may have the real models configured in settings.json.  Point every catalog
    # path at an empty temp folder so a test never depends on (or reads) multi-gigabyte files.
    monkeypatch.setattr("lyricloom.config.MODELS", tmp_path / "models")


@pytest.fixture(autouse=True)
def isolated_vocals(tmp_path, monkeypatch):
    """Kept vocals go to a temporary folder, and separation never starts the WSL distro;
    tests that route to WSL use a fake worker."""
    monkeypatch.setattr("lyricloom.config.DEFAULT_VOCALS", tmp_path / "Vocais")
    monkeypatch.setattr("lyricloom.config.SEPARATOR_WSL_ENABLED", False)
    monkeypatch.setattr("lyricloom.config.ALIGN_WSL_ENABLED", False)
    monkeypatch.setattr("lyricloom.config.MTL_WSL_ENABLED", False)
