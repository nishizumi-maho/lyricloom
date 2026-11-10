import pytest

from lyricloom import config, models, runtime


def test_human_size():
    assert runtime.human_size(0) == "0 B"
    assert runtime.human_size(1024) == "1.0 KB"
    assert runtime.human_size(3 * 1024**3) == "3.0 GB"


def test_status_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS", tmp_path)
    assert runtime.status() == {"whisper": False, "separator": False, "mms": False, "mtl": False}


def test_whisper_status_rejects_a_truncated_file(tmp_path, monkeypatch):
    model = tmp_path / "ggml-large-v3.bin"
    model.write_bytes(b"x" * 100)
    monkeypatch.setattr(config, "MODELS", tmp_path)
    assert runtime.whisper_status() is False


def test_whisper_status_has_no_one_gigabyte_threshold(tmp_path, monkeypatch):
    """A small but complete model is ready; the old fixed 1 GB check is gone."""
    import hashlib

    model = tmp_path / "ggml-small.bin"
    model.write_bytes(b"x" * 100)
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    good = models.ModelSpec(
        id="tiny-ready", stage="transcribe", label="Tiny ready", description="",
        files=(models.ModelFile("ggml-small.bin", "", 100, digest),), license="test")
    assert models.status(good, root=tmp_path) == "unverified"
    assert models.verify(good, root=tmp_path) == "ready"


def test_whisper_cli_setting_wins_over_the_bundled_copy(tmp_path, monkeypatch):
    suffix = ".exe" if config.IS_WINDOWS else ""
    bundled = tmp_path / "resources" / "tools" / "bin" / f"whisper-cli{suffix}"
    bundled.parent.mkdir(parents=True)
    bundled.write_text("", encoding="utf-8")
    explicit = tmp_path / "custom" / f"whisper-cli{suffix}"
    explicit.parent.mkdir()
    explicit.write_text("", encoding="utf-8")
    monkeypatch.delenv("LYRICLOOM_WHISPER_CLI", raising=False)
    monkeypatch.setattr(config, "RESOURCE_ROOT", tmp_path / "resources")
    config.set_setting("whisper_cli", str(explicit))
    assert config.whisper_cli() == explicit
    config.set_setting("whisper_cli", "")
    assert config.whisper_cli() == bundled


@pytest.mark.parametrize("download", [
    runtime.download_whisper, runtime.download_separator, runtime.download_mms, runtime.download_mtl,
])
def test_download_helpers_reject_an_unknown_explicit_id(download):
    """FR-A-09: an unknown id never silently downloads the default model instead."""
    with pytest.raises(ValueError, match="unknown model"):
        download(model_id="does-not-exist")


def test_status_accepts_an_unverified_file_without_hashing(tmp_path, monkeypatch):
    """FR-A-07: a size-matching model from a 2.0 install is usable before it is verified."""
    import hashlib

    models_dir = tmp_path / "models"
    models_dir.mkdir()
    model = models_dir / "ggml-small.bin"
    model.write_bytes(b"x" * 100)
    spec = models.ModelSpec(
        id="tiny-unverified", stage="transcribe", label="Tiny", description="",
        files=(models.ModelFile("ggml-small.bin", "", 100,
                                hashlib.sha256(model.read_bytes()).hexdigest()),), license="test")
    monkeypatch.setattr(config, "resolve_model", lambda stage, lang=None, models=None: spec)
    assert runtime.whisper_status() is True
    assert not (models_dir / "ggml-small.bin.verified.json").exists()


def test_torch_home_is_pinned_for_alignment(tmp_path, monkeypatch):
    from pathlib import Path

    from lyricloom.align import ctc
    from lyricloom.align.anchors import Block

    monkeypatch.setattr(config, "MODELS", tmp_path)
    monkeypatch.setenv("TORCH_HOME", str(tmp_path / "elsewhere"))
    seen = {}

    def fake_worker(module, payload, **kw):
        seen["torch_home"] = __import__("os").environ.get("TORCH_HOME")
        return {"blocks": [{"lines": [{"segments": [None]}]}]}

    monkeypatch.setattr(ctc, "run_worker", fake_worker)
    ctc.align_blocks(Path("v.wav"), [Block(0, 1, 0, 1000)], [[["eu"]]])
    assert seen["torch_home"] == str(tmp_path / "torch")
