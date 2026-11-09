import hashlib
from pathlib import Path

import pytest

from lyricloom import config, models


def test_every_catalog_entry_is_pinned():
    """G4: every catalog file has an exact size and a SHA-256, and every URL is HTTPS."""
    for spec in models.catalog():
        assert spec.files, spec.id
        assert spec.total_size > 0
        for file in spec.files:
            assert file.size > 0, (spec.id, file.filename)
            assert len(file.sha256) == 64 and int(file.sha256, 16) >= 0, (spec.id, file.filename)
            assert file.url.startswith("https://"), (spec.id, file.filename)
        if spec.kind == "hf":
            assert "/resolve/main/" not in spec.url and "/resolve/" in spec.url


def test_catalog_defaults_keep_the_current_filenames():
    assert models.default("transcribe").files[0].filename == "ggml-large-v3.bin"
    assert models.default("separate").files[0].filename == "vocals_mel_band_roformer.ckpt"
    assert models.default("align").files[0].filename == "model.pt"
    assert models.default("singing").files[0].filename == "checkpoint_MTL"


def test_resolve_precedence_track_then_language_then_default_then_catalog():
    models.use("transcribe", "whisper-medium")
    models.use("transcribe", "whisper-small", lang="ja")
    assert config.resolve_model("transcribe", "ja", models={"transcribe": "whisper-large-v3-turbo"}).id \
        == "whisper-large-v3-turbo"
    assert config.resolve_model("transcribe", "ja").id == "whisper-small"
    assert config.resolve_model("transcribe", "pt").id == "whisper-medium"
    # A language with no choice and no default falls back to the catalog default.
    config.set_setting("model_choices", {"languages": {"ja": {"transcribe": "whisper-small"}}})
    assert config.resolve_model("transcribe", "pt").id == "whisper-large-v3"


def test_unknown_or_wrong_stage_id_falls_back(caplog):
    config.set_setting("model_choices", {"default": {"transcribe": "does-not-exist"}})
    assert config.resolve_model("transcribe").id == "whisper-large-v3"
    assert any("not in the catalog" in record.message for record in caplog.records)
    config.set_setting("model_choices", {"default": {"transcribe": "align-mms-fa"}})
    assert config.resolve_model("transcribe").id == "whisper-large-v3"
    assert any("for stage" in record.message for record in caplog.records)


def test_language_specific_model_must_suit_the_language():
    config.set_setting("model_choices", {"languages": {"ja": {"singing": "singing-mtl"}}})
    # singing-mtl is English-only, so Japanese falls back to the catalog default (also English-only,
    # but resolution itself must not raise; the align stage only offers it for English).
    assert config.resolve_model("singing", "ja").id in ("singing-mtl", "singing-nltk-data")


def test_status_truncated_file_is_corrupt(tmp_path):
    file = tmp_path / "model.pt"
    file.write_bytes(b"short")
    spec = models.ModelSpec(
        id="x", stage="transcribe", label="x", description="",
        files=(models.ModelFile("model.pt", "", 100, "0" * 64),), license="test")
    assert models.status(spec, root=tmp_path) == "corrupt"
    assert models.status(spec, root=tmp_path) == "corrupt"


def test_status_uses_a_sidecar_and_verify_rehashes(tmp_path):
    file = tmp_path / "model.pt"
    file.write_bytes(b"abc")
    digest = hashlib.sha256(b"abc").hexdigest()
    spec = models.ModelSpec(
        id="x", stage="transcribe", label="x", description="",
        files=(models.ModelFile("model.pt", "", 3, digest),), license="test")
    assert models.status(spec, root=tmp_path) == "ready"
    sidecar = tmp_path / "model.pt.verified.json"
    assert sidecar.is_file()
    file.write_bytes(b"abd")   # same size, different content
    assert models.status(spec, root=tmp_path) == "corrupt"
    assert models.verify(spec, root=tmp_path) == "corrupt"


def test_custom_model_is_recorded_and_resolved(tmp_path):
    custom = tmp_path / "my-model.bin"
    custom.write_bytes(b"custom whisper bytes")
    spec = models.add("transcribe", str(custom))
    assert spec.custom and spec.files[0].size == custom.stat().st_size
    assert spec.files[0].sha256 == hashlib.sha256(custom.read_bytes()).hexdigest()
    assert models.status(spec) == "ready"
    models.use("transcribe", spec.id)
    assert config.resolve_model("transcribe").id == spec.id
    # A vanished custom file is invalid: resolution falls back instead of crashing.
    custom.unlink()
    assert config.resolve_model("transcribe").id == "whisper-large-v3"


def test_catalog_download_never_overwrites_a_custom_model(tmp_path, monkeypatch):
    models_dir = tmp_path / "models"
    monkeypatch.setattr(config, "MODELS", models_dir)
    target = models_dir / "ggml-large-v3.bin"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"my own model")
    models.add("transcribe", str(target))
    called = []
    monkeypatch.setattr("lyricloom.downloads.download_verified",
                        lambda *a, **k: called.append(a) or Path(a[1]))
    with pytest.raises(Exception, match="custom model"):
        models.download(models.get("whisper-large-v3"))
    assert called == []
    assert target.read_bytes() == b"my own model"


def test_add_rejects_a_wrong_file_type(tmp_path):
    wrong = tmp_path / "model.txt"
    wrong.write_text("x")
    with pytest.raises(ValueError):
        models.add("transcribe", str(wrong))


def test_repair_deletes_and_downloads_again(tmp_path, monkeypatch):
    dest = tmp_path / "model.bin"
    dest.write_bytes(b"old")
    spec = models.ModelSpec(
        id="repair-me", stage="transcribe", label="x", description="",
        files=(models.ModelFile("model.bin", "https://example.invalid/model.bin", 3, "0" * 64),),
        license="test")

    def fake(file, target, progress=None, cancel=None):
        target.write_bytes(b"new")
        return target

    monkeypatch.setattr("lyricloom.downloads.download_verified", fake)
    assert models.repair(spec, root=tmp_path) == [dest]
    assert dest.read_bytes() == b"new"


def test_clear_removes_only_the_requested_choice():
    models.use("transcribe", "whisper-medium")
    models.use("transcribe", "whisper-small", lang="ja")
    assert models.clear("transcribe", lang="ja") is True
    assert config.resolve_model("transcribe", "ja").id == "whisper-medium"
    assert models.clear("transcribe") is True
    assert config.resolve_model("transcribe").id == "whisper-large-v3"
    assert models.clear("transcribe") is False
    assert config.model_choices() == {}


def test_remove_only_forgets_a_custom_registration(tmp_path):
    custom = tmp_path / "my-model.bin"
    custom.write_bytes(b"custom")
    spec = models.add("transcribe", str(custom))
    models.use("transcribe", spec.id)
    models.use("transcribe", spec.id, lang="ja")
    assert models.find(spec.id) is not None

    models.remove(spec.id)

    assert models.find(spec.id) is None
    assert custom.read_bytes() == b"custom"      # the user's file is never deleted
    assert config.resolve_model("transcribe").id == "whisper-large-v3"
    assert config.resolve_model("transcribe", "ja").id == "whisper-large-v3"
    assert all(raw.get("id") != spec.id for raw in config.model_choices().get("custom", []))


def test_remove_refuses_a_catalog_model():
    with pytest.raises(ValueError, match="catalog"):
        models.remove("whisper-large-v3")


def test_download_writes_a_verification_sidecar(tmp_path, monkeypatch):
    payload = b"verified model bytes"
    digest = hashlib.sha256(payload).hexdigest()
    spec = models.ModelSpec(
        id="sidecar", stage="transcribe", label="x", description="",
        files=(models.ModelFile("model.bin", "https://example.invalid/model.bin", len(payload),
                                digest),),
        license="test")

    def fake(file, target, progress=None, cancel=None):
        target.write_bytes(payload)
        return target

    monkeypatch.setattr("lyricloom.downloads.download_verified", fake)
    assert models.download(spec, root=tmp_path) == [tmp_path / "model.bin"]
    assert (tmp_path / "model.bin.verified.json").is_file()
    assert models.status(spec, root=tmp_path) == "ready"
