"""The model catalog, per-language model choices and verified model files.

The engine never downloads a model while it processes a song.  Every heavy stage resolves the
model it is about to use here; the runner asks :func:`ensure_ready` first and turns a
``MissingModels`` exception into a failed track with an actionable message.  Downloads happen
only from the command line (``lyricloom models download ...``) or from the Models dialog.

A ``ModelSpec`` is immutable metadata: the stage it belongs to, the files it needs, a pinned size
and SHA-256 for every file, its license and the languages it suits.  ``kind`` is ``file`` for a
plain HTTPS file, ``hf`` for a file hosted on Hugging Face (its URL uses a pinned commit, never
``main``) and ``builtin`` for data that stays in an existing install layout (the NLTK corpora).

Custom models live in the ``model_choices`` setting, never in this file.  They are added with
``models.add``, record their own size and SHA-256 when added (trust on first use) and are never
overwritten by a catalog download.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

STAGES = ("transcribe", "separate", "align", "singing")
Stage = Literal["transcribe", "separate", "align", "singing"]
Kind = Literal["file", "hf", "builtin"]
Status = Literal["ready", "missing", "corrupt", "unverified"]

# --------------------------------------------------------------------------- catalog data

WHISPER_COMMIT = "5359861c739e955e79d9a303bcbc70fb988958b1"
_WHISPER_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/" + WHISPER_COMMIT + "/"
_SEPARATOR_URL = ("https://github.com/nomadkaraoke/python-audio-separator/releases/download/"
                  "model-configs/")
_MTL_URL = ("https://raw.githubusercontent.com/jhuang448/LyricsAlignment-MTL/"
            "dde51396875c65fd4fd4cc8f0c523fffec1002be/checkpoints/checkpoint_MTL")
_NLTK_COMMIT = "550b6625bcef1f2abff2ff770a5a0d272c9c6b2a"
_NLTK_URL = "https://raw.githubusercontent.com/nltk/nltk_data/" + _NLTK_COMMIT + "/packages/"


@dataclass(frozen=True)
class ModelFile:
    """One file of a model.  ``filename`` is a basename for catalog files and may be an absolute
    path for a custom model.  ``size`` is the exact byte count; ``sha256`` is the lower-case hex
    digest.  ``extract`` entries (NLTK) are zips unpacked under ``subdir`` in the models root."""
    filename: str
    url: str
    size: int
    sha256: str
    subdir: str = ""
    extract: bool = False


# audio-separator reads this registry file on every model load.  Keeping a verified local copy is
# what stops it from fetching the registry from the network during processing.
_SEPARATOR_CHECKS = ModelFile(
    "download_checks.json",
    "https://raw.githubusercontent.com/TRvlvr/application_data/"
    "3826b05b570dbd4fbedbc807758803b35348ba1b/filelists/download_checks.json",
    28_267, "d3622e1fa19c161d3cf704927711b453d593a3f1eb0f2e0838c3136907935151")
_VR_DATA = ModelFile(
    "vr_model_data.json",
    "https://raw.githubusercontent.com/TRvlvr/application_data/"
    "3826b05b570dbd4fbedbc807758803b35348ba1b/vr_model_data/model_data_new.json",
    4_380, "6a2021b9aa355c10f845b68c73944d47bd9e1fdf37b8a584b14ce8f88b09bb2f")
_MDX_DATA = ModelFile(
    "mdx_model_data.json",
    "https://raw.githubusercontent.com/TRvlvr/application_data/"
    "3826b05b570dbd4fbedbc807758803b35348ba1b/mdx_model_data/model_data_new.json",
    15_358, "1aca8f9bcc57233bc714029663a9ec2345d9c7721f91e5e08f46392a879c6a9a")


@dataclass(frozen=True)
class ModelSpec:
    """A selectable model for one stage.

    ``files`` holds one or more :class:`ModelFile` entries.  The convenience properties
    ``filename``, ``url``, ``size`` and ``sha256`` describe the first file (the model itself);
    ``total_size`` sums every file.  ``languages`` is ``None`` when the model suits any language,
    else a set of language codes.  ``default`` marks the catalog entry used when no choice is
    configured.  ``kind`` is ``file``, ``hf`` or ``builtin``.
    """
    id: str
    stage: Stage
    label: str
    description: str
    files: tuple[ModelFile, ...]
    license: str
    languages: frozenset[str] | None = None
    default: bool = False
    kind: Kind = "file"
    custom: bool = False

    @property
    def filename(self) -> str:
        return self.files[0].filename

    @property
    def url(self) -> str:
        return self.files[0].url

    @property
    def size(self) -> int:
        return self.files[0].size

    @property
    def sha256(self) -> str:
        return self.files[0].sha256

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    def dest(self, file: ModelFile, models_dir: Path) -> Path:
        """Where a file of this model lives (an absolute custom path stays absolute)."""
        path = Path(file.filename)
        if path.is_absolute():
            return path
        if file.extract:
            return models_dir / "nltk" / "_packages" / file.filename
        if self.stage == "transcribe":
            return models_dir / file.filename
        if self.stage == "separate":
            return models_dir / "separator" / file.filename
        if self.stage == "align":
            return models_dir / "torch" / "hub" / "checkpoints" / file.filename
        if self.stage == "singing":
            return models_dir / "mtl" / "checkpoints" / file.filename
        raise ValueError(f"unknown stage {self.stage!r}")

    def destinations(self, models_dir: Path) -> list[Path]:
        return [self.dest(f, models_dir) for f in self.files]

    def model_file(self) -> ModelFile:
        """The file a loader needs (the first one; NLTK has no single model file)."""
        return self.files[0]


def _f(filename: str, url: str, size: int, sha256: str, subdir: str = "", extract: bool = False) -> ModelFile:
    return ModelFile(filename, url, size, sha256, subdir, extract)


CATALOG: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="whisper-large-v3", stage="transcribe", label="Whisper large-v3",
        description="The default Whisper model: the best accuracy of the suggested sizes, and the "
                    "model existing installs already have.",
        files=(_f("ggml-large-v3.bin", _WHISPER_URL + "ggml-large-v3.bin",
                  3_095_033_483, "64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2"),),
        license="MIT (OpenAI Whisper; whisper.cpp is MIT)", default=True, kind="hf"),
    ModelSpec(
        id="whisper-large-v3-turbo", stage="transcribe", label="Whisper large-v3-turbo",
        description="Much faster than large-v3 with a small accuracy loss; a good choice for a "
                    "large library or a slower CPU.",
        files=(_f("ggml-large-v3-turbo.bin", _WHISPER_URL + "ggml-large-v3-turbo.bin",
                  1_624_555_275, "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69"),),
        license="MIT (OpenAI Whisper; whisper.cpp is MIT)", kind="hf"),
    ModelSpec(
        id="whisper-medium", stage="transcribe", label="Whisper medium",
        description="About half the size and memory of large-v3; useful on a CPU-only laptop.",
        files=(_f("ggml-medium.bin", _WHISPER_URL + "ggml-medium.bin",
                  1_533_763_059, "6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208"),),
        license="MIT (OpenAI Whisper; whisper.cpp is MIT)", kind="hf"),
    ModelSpec(
        id="whisper-small", stage="transcribe", label="Whisper small",
        description="The smallest suggested model. Fast and light, but noticeably less accurate; "
                    "use it when speed matters more than exact anchors.",
        files=(_f("ggml-small.bin", _WHISPER_URL + "ggml-small.bin",
                  487_601_967, "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b"),),
        license="MIT (OpenAI Whisper; whisper.cpp is MIT)", kind="hf"),
    ModelSpec(
        id="separator-mel-band-roformer", stage="separate", label="Mel-Band RoFormer vocals (Kim)",
        description="The default vocal separator: one of the highest published vocals SDRs in "
                    "audio-separator's registry.",
        files=(
            _f("vocals_mel_band_roformer.ckpt", _SEPARATOR_URL + "vocals_mel_band_roformer.ckpt",
               913_106_900, "87201f4d31afb5bc79993230fc49446918425574db48c01c405e44f365c7559e"),
            _f("vocals_mel_band_roformer.yaml", _SEPARATOR_URL + "vocals_mel_band_roformer.yaml",
               944, "b958b29c8f7195f0d86bee6759a33980db675c4ecaf2fcaa80fa125828e6cd38"),
            _SEPARATOR_CHECKS,
        ),
        license="See the audio-separator model registry", default=True),
    ModelSpec(
        id="separator-bs-roformer-vocals", stage="separate", label="BS-RoFormer vocals (Unwa revive)",
        description="A BS-RoFormer vocal model from audio-separator's registry; a useful "
                    "alternative when the default separator leaves too much backing vocal.",
        files=(
            _f("bs_roformer_vocals_revive_unwa.ckpt", _SEPARATOR_URL + "bs_roformer_vocals_revive_unwa.ckpt",
               639_326_600, "f1d7e4bfdfef07c6b2bc1d65283a7d03c3c38f8c7dbc8d729b785f93c8b8699a"),
            _f("config_bs_roformer_vocals_revive_unwa.yaml",
               _SEPARATOR_URL + "config_bs_roformer_vocals_revive_unwa.yaml",
               2382, "6b9d5fb6aeda6b0941f937e4e4883643e3187331ff403fb820c7aa6af4b02dbb"),
            _SEPARATOR_CHECKS,
        ),
        license="See the audio-separator model registry"),
    ModelSpec(
        id="separator-mdx-voc-ft", stage="separate", label="MDX-Net Voc FT",
        description="A small MDX-Net vocal model. Faster than the RoFormer models and a good "
                    "fallback on a machine with little memory.",
        files=(
            _f("UVR-MDX-NET-Voc_FT.onnx", _SEPARATOR_URL + "UVR-MDX-NET-Voc_FT.onnx",
               66_762_490, "534b2070fcc7df514b13ef660dc8cbb328679c2374d04354a5c42bb14ecce111"),
            _MDX_DATA,
            _SEPARATOR_CHECKS,
        ),
        license="See the audio-separator model registry"),
    ModelSpec(
        id="align-mms-fa", stage="align", label="MMS_FA (torchaudio)",
        description="Meta's multilingual wav2vec2 forced aligner. The default alignment model for "
                    "every language and the fallback for English.",
        files=(_f("model.pt", "https://dl.fbaipublicfiles.com/mms/torchaudio/ctc_alignment_mling_uroman/model.pt",
                  1_262_047_414, "20ef12963ab4924bef49ac4fc7f58ad5da2ee43b2c11bc8c853c9b90ecdbc680"),),
        license="CC-BY-NC 4.0 (non-commercial)", default=True),
    ModelSpec(
        id="singing-mtl", stage="singing", label="LyricsAlignment-MTL (English)",
        description="A model trained on sung English; better word timing than CTC on many English "
                    "songs. Used only for English and only when its checkpoint is ready.",
        files=(_f("checkpoint_MTL", _MTL_URL, 68_900_020,
                  "826559e7e810bf8f90223d8fd5c66525c01ad4dd9cdc19d019f39f784e7ed3c1"),),
        license="MIT", languages=frozenset({"en"}), default=True),
    ModelSpec(
        id="singing-nltk-data", stage="singing", label="NLTK data for the singing model",
        description="The NLTK corpora g2p_en needs to turn English words into phonemes. They are "
                    "small but required for the singing model; without them English uses CTC.",
        files=(
            _f("cmudict.zip", _NLTK_URL + "corpora/cmudict.zip", 896_069,
               "d07cca47fd72ad32ea9d8ad1219f85301eeaf4568f8b6b73747506a71fb5afd6", "corpora", True),
            _f("averaged_perceptron_tagger.zip", _NLTK_URL + "taggers/averaged_perceptron_tagger.zip",
               2_526_731, "e1f13cf2532daadfd6f3bc481a49859f0b8ea6432ccdcd83e6a49a5f19008de9", "taggers", True),
            _f("averaged_perceptron_tagger_eng.zip", _NLTK_URL + "taggers/averaged_perceptron_tagger_eng.zip",
               1_539_115, "6025f530624335c67d6547d44757b357b4e79bae030a0383e9887a92c1718f0b", "taggers", True),
            _f("punkt.zip", _NLTK_URL + "tokenizers/punkt.zip", 13_905_355,
               "51c3078994aeaf650bfc8e028be4fb42b4a0d177d41c012b6a983979653660ec", "tokenizers", True),
            _f("punkt_tab.zip", _NLTK_URL + "tokenizers/punkt_tab.zip", 4_319_076,
               "e57f64187974277726a3417ca6f181ec5403676c717672eef6a748a7b20e0106", "tokenizers", True),
        ),
        license="Per NLTK data package", languages=frozenset({"en"}), default=False, kind="builtin"),
)

_BY_ID = {spec.id: spec for spec in CATALOG}

# --------------------------------------------------------------------------- catalog access


def catalog() -> tuple[ModelSpec, ...]:
    return CATALOG


def get(model_id: str) -> ModelSpec | None:
    return _BY_ID.get(model_id)


def default(stage: str) -> ModelSpec:
    for spec in CATALOG:
        if spec.stage == stage and spec.default:
            return spec
    raise LookupError(f"no default model for stage {stage!r}")


def default_models() -> list[ModelSpec]:
    """Every catalog entry downloaded by ``models download all-defaults``: the default model for
    each stage plus the NLTK data the singing stage needs."""
    return [spec for spec in CATALOG if spec.default or spec.id == "singing-nltk-data"]


def custom_specs() -> list[ModelSpec]:
    """The user's custom models from the ``model_choices`` setting."""
    from . import config
    choices = config.setting("model_choices", {}) or {}
    if not isinstance(choices, dict):
        return []
    out: list[ModelSpec] = []
    for raw in choices.get("custom", []) or []:
        spec = spec_from_dict(raw)
        if spec is not None:
            out.append(spec)
    return out


def all_specs() -> list[ModelSpec]:
    return [*CATALOG, *custom_specs()]


def find(model_id: str) -> ModelSpec | None:
    return get(model_id) or next((s for s in custom_specs() if s.id == model_id), None)


def spec_from_dict(raw: dict) -> ModelSpec | None:
    """Rebuild a custom model from the settings representation.  Invalid entries are ignored."""
    try:
        stage = str(raw["stage"])
        if stage not in STAGES:
            return None
        files = tuple(
            ModelFile(
                filename=str(f["filename"]),
                url=str(f.get("url") or ""),
                size=int(f.get("size") or 0),
                sha256=str(f.get("sha256") or "").lower(),
                subdir=str(f.get("subdir") or ""),
                extract=bool(f.get("extract")),
            )
            for f in raw["files"]
        )
        if not files:
            return None
        languages = raw.get("languages")
        return ModelSpec(
            id=str(raw["id"]), stage=stage, label=str(raw.get("label") or raw["id"]),
            description=str(raw.get("description") or "Custom model added by the user."),
            files=files, license=str(raw.get("license") or "User-provided"),
            languages=frozenset(languages) if languages else None,
            default=False, kind="file", custom=True,
        )
    except (KeyError, TypeError, ValueError):
        return None


def spec_to_dict(spec: ModelSpec) -> dict:
    return {
        "id": spec.id, "stage": spec.stage, "label": spec.label,
        "description": spec.description, "license": spec.license,
        "languages": sorted(spec.languages) if spec.languages else None,
        "files": [{"filename": f.filename, "url": f.url, "size": f.size, "sha256": f.sha256,
                   "subdir": f.subdir, "extract": f.extract} for f in spec.files],
    }


# --------------------------------------------------------------------------- verification


def _models_dir(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    from . import config
    return Path(config.MODELS)


def _sidecar(path: Path) -> Path:
    return path.with_name(path.name + ".verified.json")


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_sidecar(path: Path) -> dict | None:
    try:
        data = json.loads(_sidecar(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_sidecar(path: Path, st: os.stat_result, digest: str) -> None:
    data = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": digest}
    side = _sidecar(path)
    try:
        side.parent.mkdir(parents=True, exist_ok=True)
        tmp = side.with_name(side.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, side)
    except OSError:
        pass   # a read-only models folder is still usable; only the fast path is lost


def _nltk_package_dir(file: ModelFile, root: Path) -> Path:
    name = Path(file.filename).stem
    return root / "nltk" / file.subdir / name


def nltk_ready(root: Path | None = None) -> bool:
    """True when every pinned NLTK package is present in our models folder or in the user's
    normal NLTK data path (so an existing install keeps working)."""
    root = _models_dir(root)
    spec = get("singing-nltk-data")
    if spec is None:
        return False
    if all(_nltk_package_dir(f, root).is_dir() for f in spec.files):
        return True
    try:
        import nltk

        for file in spec.files:
            try:
                nltk.data.find(f"{file.subdir}/{Path(file.filename).stem}")
            except LookupError:
                return False
        return True
    except Exception:  # noqa: BLE001 - no NLTK installed: the pinned packages are not there
        return False


def status(spec: ModelSpec, root: Path | None = None, verify: bool = False) -> Status:
    """``ready``, ``missing``, ``corrupt`` or ``unverified``.

    The size is always checked, so a missing or truncated file is caught without reading it.  A
    matching size and a matching ``.verified.json`` sidecar (size, mtime and digest) make a file
    ``ready``.  Without a sidecar the file is ``unverified``: usable for processing, and the Models
    window offers Verify.  The full SHA-256 is computed only when ``verify`` is true (explicit
    Verify/Repair) or by a download, so the first status check after a 2.0 upgrade does not hash
    several gigabytes on the GUI path (FR-A-07).
    """
    root = _models_dir(root)
    if spec.kind == "builtin":
        return "ready" if nltk_ready(root) else "missing"
    saw_unverified = False
    for file in spec.files:
        dest = spec.dest(file, root)
        try:
            st = dest.stat()
        except OSError:
            return "missing"
        if file.size and st.st_size != file.size:
            return "corrupt"
        if not file.sha256:
            saw_unverified = True
            continue
        if verify:
            try:
                digest = _hash_file(dest)
            except OSError:
                return "unverified"
            _write_sidecar(dest, st, digest)
            if digest.lower() != file.sha256:
                return "corrupt"
            continue
        side = _read_sidecar(dest)
        if side and side.get("size") == st.st_size and side.get("mtime_ns") == st.st_mtime_ns:
            digest = str(side.get("sha256") or "")
            if digest and digest != file.sha256:
                return "corrupt"
            if digest:
                continue
        saw_unverified = True
    return "unverified" if saw_unverified else "ready"


def verify(spec: ModelSpec, root: Path | None = None) -> Status:
    """Recomputes the SHA-256 of every file instead of trusting the sidecar."""
    return status(spec, root=root, verify=True)


def fingerprint(spec: ModelSpec, root: Path | None = None) -> str:
    """A short stable fingerprint of the model's files for a stage cache key.

    It includes the pinned identity *and* the file's size and mtime, so replacing a custom model
    in place (or re-downloading a catalog file) invalidates only the stages that used it.
    """
    root = _models_dir(root)
    parts = [spec.id]
    for file in spec.files:
        dest = spec.dest(file, root)
        try:
            st = dest.stat()
            parts.append(f"{file.filename}|{file.sha256}|{st.st_size}|{st.st_mtime_ns}")
        except OSError:
            parts.append(f"{file.filename}|{file.sha256}|missing")
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- 2.0 compatibility

# 2.0 read LYRICLOOM_WHISPER_MODEL as a file name under the models folder and passed it straight to
# whisper-cli.  2.1 resolves models through the catalog; honouring the variable keeps an upgraded
# install on the model its legacy caches were made with (FR-A-01).
_COMPAT_LOGGED: set[str] = set()


def whisper_compatibility_model() -> ModelSpec | None:
    """The 2.0 ``LYRICLOOM_WHISPER_MODEL`` override as a spec, or ``None`` when it is not usable.

    The value may be a catalog model id, a catalog file name present in the models folder, or any
    other existing ``.bin`` file (an absolute path works too).  A file outside the catalog becomes
    a custom spec with a pinned size but no digest: it is reported ``unverified`` and hashed only
    by an explicit Verify or a download, never on the status path.
    """
    value = os.environ.get("LYRICLOOM_WHISPER_MODEL", "").strip()
    if not value:
        return None
    catalog_spec = get(value)
    if catalog_spec is not None and catalog_spec.stage == "transcribe":
        selected = catalog_spec
    else:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = _models_dir() / value
        try:
            st = path.stat()
        except OSError:
            st = None
        if st is None or path.suffix.lower() != ".bin" or not path.is_file():
            if value not in _COMPAT_LOGGED:
                _COMPAT_LOGGED.add(value)
                log.warning("LYRICLOOM_WHISPER_MODEL=%r is neither a catalog model id nor an "
                            "existing .bin file in %s; ignoring it", value, _models_dir())
            return None
        selected = next(
            (spec for spec in CATALOG if spec.stage == "transcribe"
             and spec.files[0].filename.lower() == path.name.lower()
             and spec.dest(spec.files[0], _models_dir()) == path), None)
        if selected is None:
            stem = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-") or "model"
            selected = ModelSpec(
                id=f"compat-transcribe-{stem}", stage="transcribe",
                label=f"Whisper model from LYRICLOOM_WHISPER_MODEL ({path.name})",
                description="The 2.0 LYRICLOOM_WHISPER_MODEL compatibility override.",
                files=(ModelFile(str(path.resolve()), "", st.st_size, ""),),
                license="User-provided", custom=True)
    if value not in _COMPAT_LOGGED:
        _COMPAT_LOGGED.add(value)
        log.info("LYRICLOOM_WHISPER_MODEL=%r overrides the transcription model: using %s",
                 value, selected.id)
    return selected


def legacy_whisper_model() -> ModelSpec | None:
    """The model a 2.0 install would have transcribed with: the environment override, else
    ``ggml-large-v3.bin``.  ``None`` means the variable is set but unusable, so no legacy cache can
    be attributed to a known model."""
    if os.environ.get("LYRICLOOM_WHISPER_MODEL", "").strip():
        return whisper_compatibility_model()
    return get("whisper-large-v3")


# --------------------------------------------------------------------------- resolution

_MISSING_SINGING_MESSAGE = (
    "the singing model is optional: English uses CTC when it or its NLTK data is missing"
)


class MissingModels(RuntimeError):
    """Raised before a heavy stage when one or more of its model files are absent or corrupt."""

    def __init__(self, specs: list[ModelSpec]):
        self.models = list(specs)
        details = "; ".join(
            f"{s.label} ({s.id}, {_human_size(s.total_size)})" for s in self.models)
        ids = " ".join(s.id for s in self.models)
        super().__init__(
            f"missing models: {details}. The song was not processed, and no model was downloaded. "
            f"Run `lyricloom models download {ids}` or open Help > Models, then retry.")


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _candidate_id(choices: dict, stage: str, lang: str | None,
                  overrides: dict[str, str]) -> tuple[str | None, str]:
    """The id to try and a description of where it came from (for the warning)."""
    if stage in overrides:
        return overrides[stage], f"per-track override for {stage}"
    languages = choices.get("languages") if isinstance(choices.get("languages"), dict) else {}
    if lang and isinstance(languages.get(lang), dict) and stage in languages[lang]:
        return str(languages[lang][stage]), f"language {lang!r} choice for {stage}"
    default_map = choices.get("default") if isinstance(choices.get("default"), dict) else {}
    if stage in default_map:
        return str(default_map[stage]), f"default choice for {stage}"
    return None, "catalog default"


def resolve(stage: str, lang: str | None = None, overrides: dict[str, str] | None = None,
            choices: dict | None = None, root: Path | None = None) -> ModelSpec:
    """The model a stage uses, with the binding precedence.

    Per-track override > ``LYRICLOOM_WHISPER_MODEL`` (transcribe only, 2.0 compatibility) > language
    choice > default choice > catalog default.  An unknown id, a model for another stage, a model
    that does not suit ``lang`` or a custom file that is missing or corrupt is logged and skipped;
    resolution then continues with the next level and never raises because of a bad choice.
    """
    if stage not in STAGES:
        raise ValueError(f"unknown model stage {stage!r}")
    if choices is None:
        from . import config
        choices = config.setting("model_choices", {}) or {}
    if not isinstance(choices, dict):
        choices = {}
    if overrides is None:
        from . import config
        overrides = config.active_models()
    merged = dict(overrides or {})
    if stage == "transcribe" and stage not in merged:
        compatibility = whisper_compatibility_model()
        if compatibility is not None:
            return compatibility
    custom = {s.id: s for s in custom_specs()}
    tried: set[str] = set()
    while True:
        model_id, origin = _candidate_id(choices, stage, lang, merged)
        if model_id is None:
            return default(stage)
        if model_id in tried:   # a setting that points back to a rejected id
            return default(stage)
        tried.add(model_id)
        spec = get(model_id) or custom.get(model_id)
        if spec is None:
            log.warning("model %r (%s) is not in the catalog or the custom models; using the "
                        "catalog default for %s", model_id, origin, stage)
        elif spec.stage != stage:
            log.warning("model %r is for stage %r, not %r (%s); using the catalog default",
                        model_id, spec.stage, stage, origin)
        elif spec.languages is not None and lang is not None and lang not in spec.languages:
            log.warning("model %r does not suit language %r (%s); using the catalog default",
                        model_id, lang, origin)
        elif spec.custom and status(spec, root=root) not in ("ready", "unverified"):
            log.warning("custom model %r is %s (%s); using the catalog default",
                        model_id, status(spec, root=root), origin)
        else:
            return spec
        # Fall through: remove this level and try the next one.
        if model_id == merged.get(stage) and stage in merged:
            merged.pop(stage, None)
        elif lang and isinstance(choices.get("languages"), dict) \
                and isinstance(choices["languages"].get(lang), dict) \
                and choices["languages"][lang].get(stage) == model_id:
            choices = {**choices, "languages": {**choices["languages"],
                                                lang: {k: v for k, v in choices["languages"][lang].items()
                                                       if k != stage}}}
        else:
            default_map = choices.get("default") if isinstance(choices.get("default"), dict) else {}
            choices = {**choices, "default": {k: v for k, v in default_map.items() if k != stage}}


def ensure_ready(specs: list[ModelSpec] | tuple[ModelSpec, ...], root: Path | None = None) -> None:
    """Raises :class:`MissingModels` when any spec is not ready.  Call before a heavy stage."""
    missing = [spec for spec in specs if status(spec, root=root) not in ("ready", "unverified")]
    if missing:
        raise MissingModels(missing)


def singing_ready(lang: str | None = "en", root: Path | None = None) -> bool:
    """True when the selected singing model *and* its NLTK data are ready.

    R1-25: the vendored wrapper alone is not enough; a fresh install must go straight to CTC
    instead of starting a worker that fails to load a missing checkpoint.
    """
    from . import config

    if not config.MTL_ENABLED:
        return False
    try:
        spec = resolve("singing", lang, root=root)
    except LookupError:
        return False
    if spec.kind == "builtin" or spec.id == "singing-nltk-data":
        return nltk_ready(root)
    return status(spec, root=root) in ("ready", "unverified") and nltk_ready(root)


def used_ids(specs: dict[str, ModelSpec]) -> dict[str, str]:
    return {stage: spec.id for stage, spec in specs.items() if spec is not None}


def tag_value(specs: dict[str, str]) -> str:
    """A safe value for the ``[#models:...]`` tag: ``stage=id`` pairs, catalog order."""
    order = {stage: i for i, stage in enumerate(STAGES)}
    items = sorted(specs.items(), key=lambda kv: order.get(kv[0], 99))
    return ";".join(f"{_safe(k)}={_safe(v)}" for k, v in items)


def _safe(value: str) -> str:
    return re.sub(r"[;=\]\r\n]", "_", str(value))


# --------------------------------------------------------------------------- downloads / repair


def download(spec: ModelSpec, progress=None, cancel=None, root: Path | None = None) -> list[Path]:
    """Downloads every file of ``spec`` with :func:`lyricloom.downloads.download_verified`.

    NLTK entries are unpacked into the models root after verification.  A catalog download
    refuses to write over a file that belongs to a custom model.
    """
    from . import downloads

    root = _models_dir(root)
    if status(spec, root=root) == "ready":
        return [spec.dest(file, root) for file in spec.files]
    # An explicit download may hash: a file from a 2.0 install has no sidecar but can still be the
    # right one, and re-downloading several gigabytes to discover that would be wasteful (FR-A-07).
    if status(spec, root=root, verify=True) == "ready":
        return [spec.dest(file, root) for file in spec.files]
    custom = {p.resolve() for s in custom_specs() for p in s.destinations(root) if p.exists()}
    written: list[Path] = []
    for file in spec.files:
        dest = spec.dest(file, root)
        try:
            if dest.resolve() in custom:
                raise downloads.DownloadError(
                    f"refusing to overwrite {dest}: it belongs to a custom model. "
                    "Remove or rename the custom model first, or choose a catalog filename.")
        except OSError:
            pass
        if not file.url:
            raise downloads.DownloadError(
                f"{spec.id} is a custom local model; it cannot be downloaded. "
                "Choose its file with `lyricloom models add` instead.")
        written.append(downloads.download_verified(file, dest, progress=progress, cancel=cancel))
        if file.sha256:
            try:
                _write_sidecar(dest, dest.stat(), file.sha256)
            except OSError:
                pass   # the fast path is lost; the next status check hashes the verified file
        if file.extract:
            _extract_zip(dest, root)
    return written


def _extract_zip(archive: Path, root: Path) -> None:
    import zipfile

    spec = get("singing-nltk-data")
    file = next((f for f in spec.files if f.filename == archive.name), None) if spec else None
    if file is None or not file.subdir:
        return
    target = root / "nltk" / file.subdir
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        z.extractall(target)


def repair(spec: ModelSpec, progress=None, cancel=None, root: Path | None = None) -> list[Path]:
    """Deletes the spec's files and downloads them again."""
    from . import downloads

    if spec.custom or not any(file.url for file in spec.files):
        raise downloads.DownloadError(
            f"{spec.id} is a custom local model: LyricLoom will not delete it. "
            "Replace the file and run `lyricloom models verify` again.")
    root = _models_dir(root)
    for file in spec.files:
        dest = spec.dest(file, root)
        for p in (dest, _sidecar(dest), dest.with_name(dest.name + ".part")):
            try:
                p.unlink()
            except OSError:
                pass
    return download(spec, progress=progress, cancel=cancel, root=root)


# --------------------------------------------------------------------------- choices and custom models


def _read_choices() -> dict:
    from . import config
    choices = config.setting("model_choices", {})
    return choices if isinstance(choices, dict) else {}


def _write_choices(choices: dict) -> None:
    from . import config
    config.set_setting("model_choices", choices)


def clear(stage: str, lang: str | None = None) -> bool:
    """Removes a default or language choice so resolution falls back to the next level.

    Returns True when a choice was removed.  The catalog default is never written, so an empty
    setting and a missing key mean the same thing.
    """
    if stage not in STAGES:
        raise ValueError(f"unknown model stage {stage!r}")
    choices = _read_choices()
    removed = False
    if lang:
        languages = dict(choices.get("languages") or {})
        entry = dict(languages.get(lang) or {})
        if stage in entry:
            entry.pop(stage)
            removed = True
            if entry:
                languages[lang] = entry
            else:
                languages.pop(lang, None)
            if languages:
                choices["languages"] = languages
            else:
                choices.pop("languages", None)
    else:
        default_map = dict(choices.get("default") or {})
        if stage in default_map:
            default_map.pop(stage)
            removed = True
            if default_map:
                choices["default"] = default_map
            else:
                choices.pop("default", None)
    if removed:
        _write_choices(choices)
    return removed


def use(stage: str, model_id: str, lang: str | None = None) -> None:
    """Records a model choice.  ``lang`` writes a language override instead of the default."""
    if stage not in STAGES:
        raise ValueError(f"unknown model stage {stage!r}")
    spec = find(model_id)
    if spec is None:
        raise ValueError(f"unknown model {model_id!r}; use `lyricloom models list`")
    if model_id == "singing-nltk-data":
        raise ValueError("singing-nltk-data is a required dependency of the singing model, "
                         "not a selectable model; it is downloaded with the singing stage")
    if spec.stage != stage:
        raise ValueError(f"model {model_id!r} is for stage {spec.stage!r}, not {stage!r}")
    choices = _read_choices()
    if lang:
        languages = dict(choices.get("languages") or {})
        entry = dict(languages.get(lang) or {})
        entry[stage] = model_id
        languages[lang] = entry
        choices["languages"] = languages
    else:
        default_map = dict(choices.get("default") or {})
        default_map[stage] = model_id
        choices["default"] = default_map
    _write_choices(choices)


def choices_for(spec: ModelSpec) -> list[str]:
    """Human-readable places where this model is chosen: ``default`` and/or language codes."""
    choices = _read_choices()
    out: list[str] = []
    default_map = choices.get("default") if isinstance(choices.get("default"), dict) else {}
    if default_map.get(spec.stage) == spec.id:
        out.append("default")
    languages = choices.get("languages") if isinstance(choices.get("languages"), dict) else {}
    for lang, entry in sorted(languages.items()):
        if isinstance(entry, dict) and entry.get(spec.stage) == spec.id:
            out.append(str(lang))
    return out


def add(stage: str, source: str, label: str | None = None, root: Path | None = None) -> ModelSpec:
    """Registers a custom model: a local file, or a separator name audio-separator knows.

    The file's size and SHA-256 are recorded now (trust on first use).  Custom entries live in the
    ``model_choices`` setting and are never touched by a catalog download.
    """
    if stage not in STAGES:
        raise ValueError(f"unknown model stage {stage!r}")
    root = _models_dir(root)
    path = Path(source).expanduser()
    files: list[ModelFile] = []
    if stage == "separate" and not path.is_file():
        files = _separator_registry_files(source, root)
    elif stage == "separate":
        if path.suffix.lower() not in (".ckpt", ".onnx", ".pth"):
            raise ValueError("a separator model must be a .ckpt, .onnx or .pth file")
        _check_separator_name(path.name, root)
        files = [_local_file(path)]
        config_file = _separator_config(path)
        if config_file is not None:
            files.append(_local_file(config_file))
        files.append(_ensure_separator_checks(path.parent, root))
        if path.suffix.lower() == ".pth":
            files.append(_ensure_separator_file(path.parent, root, _VR_DATA))
        if path.suffix.lower() == ".onnx":
            files.append(_ensure_separator_file(path.parent, root, _MDX_DATA))
    else:
        if not path.is_file():
            raise FileNotFoundError(f"model file not found: {path}")
        if stage == "transcribe" and path.suffix.lower() != ".bin":
            raise ValueError("a whisper.cpp model must be a .bin (GGML) file")
        if stage == "align" and path.suffix.lower() not in (".pt", ".pth"):
            raise ValueError("an alignment model must be a .pt or .pth checkpoint")
        if stage == "singing" and path.name != "checkpoint_MTL":
            raise ValueError("the singing model file must be named checkpoint_MTL")
        if stage == "singing" and path.parent.name != "checkpoints":
            raise ValueError("the singing model must be inside a `checkpoints` folder (the MTL "
                             "loader reads `checkpoints/checkpoint_MTL` relative to its working dir)")
        files = [_local_file(path)]
    stem = re.sub(r"[^a-z0-9]+", "-", (label or Path(files[0].filename).stem).lower()).strip("-") or "model"
    model_id = f"custom-{stage}-{stem}"
    taken = {s.id for s in all_specs()}
    n = 2
    base = model_id
    while model_id in taken:
        model_id = f"{base}-{n}"
        n += 1
    spec = ModelSpec(
        id=model_id, stage=stage,
        label=label or f"Custom {stage}: {Path(files[0].filename).stem}",
        description="Custom model added by the user (trust on first use).",
        files=tuple(files), license="User-provided", default=False, kind="file", custom=True,
    )
    choices = _read_choices()
    custom = list(choices.get("custom") or [])
    custom.append(spec_to_dict(spec))
    choices["custom"] = custom
    _write_choices(choices)
    return spec


def remove(model_id: str) -> None:
    """Removes a custom model's registration and every choice that pointed at it.

    The model's files are never deleted: a custom model is the user's own file, and this action only
    forgets how LyricLoom found it.  Catalog models cannot be removed.
    """
    spec = find(model_id)
    if spec is None:
        raise ValueError(f"unknown model {model_id!r}")
    if not spec.custom:
        raise ValueError(f"{model_id!r} is a catalog model; only custom models can be removed")
    choices = _read_choices()
    custom = [raw for raw in choices.get("custom") or []
              if not (isinstance(raw, dict) and str(raw.get("id")) == model_id)]
    if custom:
        choices["custom"] = custom
    else:
        choices.pop("custom", None)
    default_map = {stage: model for stage, model in (choices.get("default") or {}).items()
                   if model != model_id}
    if default_map:
        choices["default"] = default_map
    else:
        choices.pop("default", None)
    languages = {}
    for lang, entry in (choices.get("languages") or {}).items():
        if not isinstance(entry, dict):
            continue
        kept = {stage: model for stage, model in entry.items() if model != model_id}
        if kept:
            languages[lang] = kept
    if languages:
        choices["languages"] = languages
    else:
        choices.pop("languages", None)
    _write_choices(choices)


def _local_file(path: Path) -> ModelFile:
    return ModelFile(str(path.resolve()), "", path.stat().st_size, _hash_file(path))


def _check_separator_name(name: str, root: Path) -> None:
    """A separator file must be a filename audio-separator's registry knows; otherwise its loader
    refuses it anyway.  The registries are read locally (no network, no model load)."""
    try:
        from importlib import resources
        import json

        with resources.open_text("audio_separator", "models.json") as f:
            registry = json.load(f)
        known = _separator_names(registry)
        local_checks = root / "separator" / "download_checks.json"
        if local_checks.is_file():
            known |= _separator_names(json.loads(local_checks.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001 - a source checkout without the optional heavy dependency
        return
    if name not in known:
        raise ValueError(
            f"audio-separator does not know a separator model named {name!r}; pass a known name "
            "from its registry, or a file whose name is in that registry")


def _separator_names(registry: dict) -> set[str]:
    names: set[str] = set()
    for section in ("vr_download_list", "mdx_download_list", "mdx_download_vip_list",
                    "mdx23c_download_list", "mdx23c_download_vip_list", "roformer_download_list"):
        for group in registry.get(section, {}) or {}:
            value = registry[section][group]
            if isinstance(value, str):
                names.add(value)
            elif isinstance(value, dict):
                names.update(str(k) for k in value)
                names.update(Path(str(v)).name for v in value.values())
    return names


def _separator_config(path: Path) -> Path | None:
    for suffix in (".yaml", ".yml", ".json"):
        candidate = path.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


def _ensure_separator_checks(directory: Path, root: Path) -> ModelFile:
    """Makes sure audio-separator's registry file is local, so loading a model never fetches it."""
    return _ensure_separator_file(directory, root, _SEPARATOR_CHECKS)


def _ensure_separator_file(directory: Path, root: Path, pinned: ModelFile) -> ModelFile:
    dest = directory / pinned.filename
    if not dest.is_file():
        source = root / "separator" / pinned.filename
        try:
            if source.is_file() and source.resolve() != dest.resolve():
                shutil.copy2(source, dest)
            else:
                from . import downloads

                downloads.download_verified(pinned, dest)
        except (OSError, RuntimeError) as exc:
            raise ValueError(
                f"cannot place audio-separator's {pinned.filename} next to {directory}: {exc}. "
                "Copy it there yourself (it is the file the catalog uses) and retry.") from exc
    return _local_file(dest)


def _separator_registry_files(name: str, root: Path) -> list[ModelFile]:
    """Resolve a separator registry name and (when needed) download it, then record its hash."""
    from audio_separator.separator import Separator

    model_dir = root / "separator"
    model_dir.mkdir(parents=True, exist_ok=True)
    _ensure_separator_checks(model_dir, root)   # local registry, so the next call stays offline
    sep = Separator(model_file_dir=str(model_dir))
    listing = sep.list_supported_model_files()
    entry = None
    for models in listing.values():
        for info in models.values():
            names = [info["filename"], *(Path(p).name for p in info.get("download_files", [])
                                         if not p.startswith("http"))]
            if name in names:
                entry = (info["filename"], info)
                break
        if entry:
            break
    if entry is None:
        raise ValueError(f"audio-separator does not know a model named {name!r}")
    filename, info = entry
    sep.download_model_and_data(filename)
    files = []
    for item in info.get("download_files", []):
        fname = Path(item).name if not item.startswith("http") else Path(item).name
        p = model_dir / fname
        if p.is_file():
            files.append(_local_file(p))
    if not files:
        raise RuntimeError(f"audio-separator did not produce the files for {filename!r}")
    files.append(_ensure_separator_checks(model_dir, root))
    if filename.lower().endswith(".pth"):
        files.append(_ensure_separator_file(model_dir, root, _VR_DATA))
    if filename.lower().endswith(".onnx"):
        files.append(_ensure_separator_file(model_dir, root, _MDX_DATA))
    return files
