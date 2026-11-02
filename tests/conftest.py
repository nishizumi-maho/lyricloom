import pytest


@pytest.fixture(autouse=True)
def no_cloud_transcription(tmp_path, monkeypatch):
    """Tests never reach AssemblyAI: a real key in assemblyai.key would otherwise turn it on.
    Tests that need it turn it back on with a fake in place of the network call."""
    monkeypatch.setattr("lyricloom.config.ASSEMBLYAI_ENABLED", False)
    monkeypatch.setattr("lyricloom.config.ASSEMBLYAI_KEY_FILE", tmp_path / "test-assemblyai.key")


@pytest.fixture(autouse=True)
def no_singing_model(monkeypatch):
    """Tests never start the real singing-model venv; tests that route to it use a fake."""
    monkeypatch.setattr("lyricloom.config.MTL_ENABLED", False)


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """The real settings file (chosen library) is never read or written by tests."""
    monkeypatch.setattr("lyricloom.config.SETTINGS_FILE", tmp_path / "test-settings.json")
    monkeypatch.setattr("lyricloom.config.WORK_ROOT", tmp_path / "work")   # caches and scan lists too


@pytest.fixture(autouse=True)
def isolated_vocals(tmp_path, monkeypatch):
    """Kept vocals go to a temporary folder, and separation never starts the WSL distro;
    tests that route to WSL use a fake worker."""
    monkeypatch.setattr("lyricloom.config.DEFAULT_VOCALS", tmp_path / "Vocais")
    monkeypatch.setattr("lyricloom.config.SEPARATOR_WSL_ENABLED", False)
    monkeypatch.setattr("lyricloom.config.ALIGN_WSL_ENABLED", False)
    monkeypatch.setattr("lyricloom.config.MTL_WSL_ENABLED", False)
