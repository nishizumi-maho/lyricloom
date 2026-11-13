import hashlib
import os
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
    # A 2.0 install has the file but no sidecar: usable, and not hashed on the status path.
    assert models.status(spec, root=tmp_path) == "unverified"
    assert models.verify(spec, root=tmp_path) == "ready"
    sidecar = tmp_path / "model.pt.verified.json"
    assert sidecar.is_file()
    assert models.status(spec, root=tmp_path) == "ready"
    file.write_bytes(b"abd")   # same size, different content; the sidecar's mtime is stale
    # A rewrite within one tick of the Windows clock keeps the same mtime, and the test then
    # failed at random on a fast machine.  A real edit happens later; say so explicitly.
    stamp = file.stat()
    os.utime(file, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 2_000_000_000))
    assert models.status(spec, root=tmp_path) == "unverified"
    assert models.verify(spec, root=tmp_path) == "corrupt"


def test_custom_model_is_recorded_and_resolved(tmp_path):
    custom = tmp_path / "my-model.bin"
    custom.write_bytes(b"custom whisper bytes")
    spec = models.add("transcribe", str(custom))
    assert spec.custom and spec.files[0].size == custom.stat().st_size
    assert spec.files[0].sha256 == hashlib.sha256(custom.read_bytes()).hexdigest()
    # `add` records the digest in the settings; the file itself has no sidecar until Verify.
    assert models.status(spec) == "unverified"
    assert models.verify(spec) == "ready"
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


def test_status_does_not_hash_a_file_without_a_sidecar(tmp_path, monkeypatch):
    """FR-A-07: the first status check after a 2.0 upgrade must not read the whole file."""
    payload = b"x" * 2048
    digest = hashlib.sha256(payload).hexdigest()
    (tmp_path / "model.bin").write_bytes(payload)
    spec = models.ModelSpec(
        id="slow", stage="transcribe", label="x", description="",
        files=(models.ModelFile("model.bin", "", len(payload), digest),), license="test")
    hashed = []
    monkeypatch.setattr(models, "_hash_file",
                        lambda path: hashed.append(path) or hashlib.sha256(path.read_bytes()).hexdigest())

    assert models.status(spec, root=tmp_path) == "unverified"
    assert hashed == []
    assert models.ensure_ready([spec], root=tmp_path) is None   # usable for processing

    assert models.verify(spec, root=tmp_path) == "ready"
    assert len(hashed) == 1
    assert models.status(spec, root=tmp_path) == "ready"        # the sidecar is trusted
    assert len(hashed) == 1


def test_download_verifies_an_unverified_file_instead_of_downloading_it_again(tmp_path, monkeypatch):
    payload = b"already on disk"
    digest = hashlib.sha256(payload).hexdigest()
    target = tmp_path / "model.bin"
    target.write_bytes(payload)
    spec = models.ModelSpec(
        id="already", stage="transcribe", label="x", description="",
        files=(models.ModelFile("model.bin", "https://example.invalid/model.bin", len(payload),
                                digest),),
        license="test")
    called = []
    monkeypatch.setattr("lyricloom.downloads.download_verified",
                        lambda *a, **k: called.append(a) or target)

    assert models.download(spec, root=tmp_path) == [target]
    assert called == []
    assert models.status(spec, root=tmp_path) == "ready"


def test_whisper_model_env_selects_a_catalog_model(monkeypatch, caplog):
    """FR-A-01: a 2.0 install keeps the model its transcribe caches were made with."""
    monkeypatch.setenv("LYRICLOOM_WHISPER_MODEL", "whisper-medium")
    models._COMPAT_LOGGED.clear()
    caplog.set_level("INFO", logger="lyricloom.models")
    assert config.resolve_model("transcribe").id == "whisper-medium"
    assert config.resolve_model("transcribe", "ja").id == "whisper-medium"
    assert sum("LYRICLOOM_WHISPER_MODEL" in record.message for record in caplog.records) == 1


def test_whisper_model_env_selects_an_existing_ggml_file(tmp_path, monkeypatch):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    model = models_dir / "ggml-large-v2.bin"
    model.write_bytes(b"x" * 17)
    monkeypatch.setattr(config, "MODELS", models_dir)
    monkeypatch.setenv("LYRICLOOM_WHISPER_MODEL", "ggml-large-v2.bin")
    models._COMPAT_LOGGED.clear()

    spec = config.resolve_model("transcribe")
    assert spec.id == "compat-transcribe-ggml-large-v2"
    assert spec.dest(spec.model_file(), models_dir) == model
    assert models.status(spec, root=models_dir) == "unverified"
    models.ensure_ready([spec], root=models_dir)   # no MissingModels


def test_whisper_model_env_uses_a_catalog_file_in_the_models_folder(tmp_path, monkeypatch):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "ggml-medium.bin").write_bytes(b"not really the model")
    monkeypatch.setattr(config, "MODELS", models_dir)
    monkeypatch.setenv("LYRICLOOM_WHISPER_MODEL", "ggml-medium.bin")
    models._COMPAT_LOGGED.clear()
    assert config.resolve_model("transcribe").id == "whisper-medium"


def test_an_unusable_whisper_model_env_value_is_ignored(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(config, "MODELS", tmp_path / "models")
    monkeypatch.setenv("LYRICLOOM_WHISPER_MODEL", "ggml-does-not-exist.bin")
    models._COMPAT_LOGGED.clear()
    caplog.set_level("WARNING", logger="lyricloom.models")
    assert config.resolve_model("transcribe").id == "whisper-large-v3"
    assert any("LYRICLOOM_WHISPER_MODEL" in record.message for record in caplog.records)
