# Models

LyricLoom separates vocals, transcribes them and aligns lyrics with several large model files. They
are not stored in the Git repository or in the release installers. This page explains what each model
does, where it goes, how to download or choose it, how to install it offline, and how to verify,
repair or remove it.

The normal Windows installer and the Linux tarball open the **setup assistant** on first start; its
**Models** page offers the suggested files. **Help > Models…** opens the full Models window at any
time. A source or pipx install also has the `lyricloom models` command described below.

## At a glance

Every catalog entry is pinned by exact size and SHA-256. `*` marks the default for its stage.

| Model | Stage | Approximate size | License | Default |
|---|---|---|---:|---|---|
| `whisper-large-v3` — Whisper large-v3 (`ggml-large-v3.bin`) | Transcription | 2.9 GB | MIT (OpenAI Whisper; whisper.cpp is MIT) | * |
| `whisper-large-v3-turbo` | Transcription | 1.5 GB | MIT | |
| `whisper-medium` | Transcription | 1.4 GB | MIT | |
| `whisper-small` | Transcription | 465 MB | MIT | |
| `separator-mel-band-roformer` — Mel-Band RoFormer vocals (Kim) | Vocal separation | 871 MB | Check the audio-separator model registry | * |
| `separator-bs-roformer-vocals` — BS-RoFormer vocals (Unwa revive) | Vocal separation | 610 MB | Check the audio-separator model registry | |
| `separator-mdx-voc-ft` — MDX-Net Voc FT | Vocal separation | 64 MB | Check the audio-separator model registry | |
| `align-mms-fa` — MMS_FA (torchaudio) | Alignment | 1.2 GB | **CC-BY-NC 4.0 (non-commercial)** | * |
| `singing-mtl` — LyricsAlignment-MTL (English) | English singing model | 66 MB | MIT (upstream) | * |
| `singing-nltk-data` — NLTK data for the singing model | English singing model | 22 MB | Per NLTK data package | With MTL |

The suggested set — every default plus the NLTK data — totals about **5.4 GB** (5.0 GiB). Allow
extra working space for the work cache and kept vocal stems; those can add several hundred MB per
song across a large library.

List the exact current catalog, including custom models, with:

```bash
lyricloom models list
```

## What each model does

### Whisper models (`ggml-*.bin`)

Whisper transcribes the isolated vocals with word timestamps. LyricLoom uses that transcript to:

- find **anchors** — lines it is confident it heard — and split the song into short alignment blocks;
- check that a candidate lyric really matches what is sung;
- provide the lyric text itself when no public source has an acceptable version.

It runs through **whisper.cpp**, not the Python `openai-whisper` package. The Windows installer ships
a CPU `whisper-cli`; the setup assistant can install a faster official build, and a locally built
Vulkan or CUDA build can replace it. On Linux you build or install it yourself (see
[docs/install-linux.md](install-linux.md#build-whisper-cli)).

| Model | When it is a good choice |
|---|---|
| `whisper-large-v3` | Best accuracy; the default and what existing installs already have. |
| `whisper-large-v3-turbo` | Much faster with a small accuracy loss; good for a large library or a slower CPU. |
| `whisper-medium` | About half the size and memory of large-v3; useful on a CPU-only laptop. |
| `whisper-small` | Fastest and lightest, but noticeably less accurate; use it when speed matters more than exact anchors. |

The files come from the `ggerganov/whisper.cpp` repository on Hugging Face at a pinned commit.
LyricLoom checks the SHA-256 and size pinned in `lyricloom/models.py`; it never takes the checksum
from the same mutable API that serves the file.

### Vocal separators

The separator takes the full mix (or the mix with a same-release instrumental subtracted) and
produces a vocal stem. LyricLoom keeps a lossless FLAC copy outside the music library and a 16 kHz
mono copy in the work cache for the aligners.

- **Mel-Band RoFormer vocals (Kim)** is the default, with one of the highest published vocals SDRs
  in audio-separator's registry.
- **BS-RoFormer vocals (Unwa revive)** is an alternative when the default leaves too much backing
  vocal.
- **MDX-Net Voc FT** is much smaller and faster, and a good fallback on a machine with little memory.

The files are distributed through **audio-separator**'s model registry. The checkpoint licenses are
not declared consistently in every upstream model card. **Check the upstream model card/license
before commercial use or redistribution.** The separator architecture and the audio-separator code
are separate from the weights.

### MMS_FA (`align-mms-fa`)

MMS_FA is a multilingual wav2vec2 model from Meta, exposed through `torchaudio.pipelines.MMS_FA`. It
performs CTC forced alignment for languages other than English, and it is the fallback for English
when the singing model is unavailable. It is also used for Japanese and Portuguese.

**License: CC-BY-NC 4.0 (non-commercial).** This is a restriction on the model weights, not on
LyricLoom's GPL source code. If you need commercial use, you must obtain a suitable license or
replace this alignment path. See [THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md).

The checkpoint is cached by torchaudio under `$TORCH_HOME/hub/checkpoints`. LyricLoom sets
`TORCH_HOME` to `<models>/torch` for its worker, so the default Windows location is:

```text
<models>/torch/hub/checkpoints/model.pt
```

### LyricsAlignment-MTL (`singing-mtl`)

This model was trained on sung English and gives better word timing than CTC on many English songs.
LyricLoom uses it only for English; other languages use MMS_FA. It is attempted only when its
checkpoint and NLTK data are ready, and if the worker still fails, English falls back to CTC and the
track completes.

The inference code is vendored under `lyricloom/vendor/mtl` (MIT). The checkpoint is downloaded from
the upstream LyricsAlignment-MTL repository (about 66 MB). Its license follows the upstream project;
check the upstream repository if you plan to redistribute the weights.

The Windows app runs the model on the CPU by default. With WSL enabled it can run inside WSL on the
GPU (see [docs/wsl-rocm.md](wsl-rocm.md)). On native Linux in 2.1.0 it runs on the CPU.

### NLTK data (`singing-nltk-data`)

The MTL model uses `g2p_en`, which needs these NLTK corpora:

- `cmudict`
- `averaged_perceptron_tagger` and `averaged_perceptron_tagger_eng`
- `punkt` and `punkt_tab`

They are small compared with the neural models and are part of the model catalog. LyricLoom
downloads the pinned zips into `<models>/nltk` and extracts them there; the MTL worker reads that
folder through `NLTK_DATA`. If an existing `NLTK_DATA` directory already has all the corpora,
LyricLoom uses it instead and does not download anything. The worker never downloads NLTK data on
its own.

NLTK software is Apache-2.0; the individual data packages have their own terms. See the NLTK data
package pages.

## Where the models live

The default root is:

| Platform | Models root |
|---|---|
| Windows | `%LOCALAPPDATA%\LyricLoom\models` |
| Linux | `~/.local/share/lyricloom/models` (or `$XDG_DATA_HOME/lyricloom/models`) |

You can override it with, in order of priority:

1. The `LYRICLOOM_MODELS` environment variable.
2. The `models` setting in `settings.json`.
3. A developer checkout's `models/` directory, if it contains at least one `*.bin` file or a
   `separator/` folder.
4. The per-user default above.

The `LYRICLOOM_MODELS` override is useful for a large SSD, a shared read-only model folder or an
offline install.

### Full default layout

```text
<models>/
├── ggml-large-v3.bin
├── separator/
│   ├── vocals_mel_band_roformer.ckpt
│   ├── vocals_mel_band_roformer.yaml
│   └── download_checks.json
├── mtl/
│   └── checkpoints/
│       └── checkpoint_MTL
├── nltk/
│   ├── corpora/
│   ├── taggers/
│   └── tokenizers/
└── torch/
    └── hub/
        └── checkpoints/
            └── model.pt
```

`<models>` is the root from the table above. A verified file also gets a small
`<file>.verified.json` sidecar with its size, modification time and digest, so start-up does not hash
several gigabytes on every run.

NLTK data can also live in an existing local NLTK data directory:

```text
Windows: %USERPROFILE%\nltk_data
Linux:   ~/nltk_data
```

In a source or pipx install, `lyricloom doctor` prints the models root and the status of each model.
The GUI's Models window shows the same readiness information.

## Choosing models

Every stage is customizable, and a choice can differ per language and per song.

### Command line (source or pipx install)

```bash
lyricloom models list                                  # id, size, status, which languages choose it
lyricloom models use transcribe whisper-small          # default choice for every song
lyricloom models use transcribe whisper-medium --lang ja
lyricloom models use separate separator-mdx-voc-ft --lang en
lyricloom models add separate "C:\Models\my-vocals.ckpt"
lyricloom models add separate UVR-MDX-NET-Voc-FT      # a name audio-separator's registry knows
```

A default choice can be removed by editing `model_choices` in `settings.json`; the catalog default
is used whenever no explicit choice exists.

### The Models window (packaged app)

**Help > Models…** has two tabs:

- **Models** lists every catalog and custom model per stage with size, status, where it is used and
  its license. Select a row and use **Download**, **Cancel**, **Verify**, **Repair**, **Use as
  default** or **Use for a language…**. **Add custom model…** and **Remove custom model** manage
  your own registrations; removing one never deletes the model file.
- **Language overrides** sets a model per stage for a language code. The changes are written as soon
  as you change a box.

The library's context menu has **Process with other models…** for one song or a selected batch. That
dialog sets the language and one model per stage for that queue only. The resulting `.lrc` records
those ids in `[#models:…]`, and the library shows the song under **Made with other models**. **Redo
with current models** reprocesses it with the current choices.

### Settings format and precedence

Choices live in `settings.json` under `model_choices`:

```json
{
  "default": {"transcribe": "whisper-large-v3"},
  "languages": {"ja": {"transcribe": "whisper-large-v3-turbo"}},
  "custom": []
}
```

Resolution precedence is **per-song override > language choice > default choice > catalog default**.
A per-song override comes from **Process with other models…**, the dialog's language shortcut or
`runner.process(..., models={"transcribe": "whisper-small"})`; it applies to that run only. Unknown
ids, a model for another stage, a model that does not suit the language, or a missing custom file is
logged and skipped, never a crash. Missing keys mean the catalog default.

Changing a model invalidates the cached stages that used it and the stages after them, so only the
affected work is redone. A finished `.lrc` is not marked pending: the file records what was used in
its [`#models` tag](lrc-format.md#about-models), and the app can show that a song was made with other
models.

## Custom models

A custom model is a registration, not a copy. It lives in the `model_choices` setting and records
the file's size and SHA-256 when it is added (**trust on first use**). LyricLoom never moves, changes
or deletes the file, and a catalog download never overwrites it.

- **A local file:** use `lyricloom models add <stage> <path>` or **Add custom model…** in the Models
  window. The stage rules are:
  - `transcribe`: a `.bin` GGML file;
  - `separate`: a `.ckpt`, `.onnx` or `.pth` file whose filename audio-separator's registry knows;
  - `align`: a `.pt` or `.pth` checkpoint;
  - `singing`: a file named `checkpoint_MTL` inside a `checkpoints` folder.
- **A separator registry name:** pass the name instead of a path, for example
  `lyricloom models add separate UVR-MDX-NET-Voc-FT`. LyricLoom asks audio-separator for the files
  and downloads them when you add the model. The name and file must be one audio-separator knows.

A custom model gets an id such as `custom-separate-my-vocals`. Choose it with `models use` or the
Models window. Removing a custom registration forgets the id and every choice that pointed at it,
but leaves the file alone. A separator file whose name audio-separator does not know will be refused
by its loader; pass the registry name instead when the file is not present yet.

## Download

### The setup assistant and Models window

On Windows and in the Linux tarball, the first-run setup assistant lists the suggested models and
their total size. **Download now** fetches only the missing or incomplete files. The full Models
window (**Help > Models…**) can download, cancel, verify and repair individual models later.

The models are not bundled in the installer or tarball. Without network access, use the offline
procedure below.

### The command line (source or pipx install)

```bash
lyricloom models list
lyricloom models download all-defaults
```

`download all-defaults` fetches the default model for each stage plus the NLTK data. `download all`
is accepted as an alias. It continues with the remaining models if one download fails and prints a
per-model result. You can fetch one model by id, or use the old short names:

```bash
lyricloom models download whisper-large-v3-turbo
lyricloom models download separator-bs-roformer-vocals
lyricloom models download whisper      # old name: the default Whisper model
lyricloom models download separator   # old name: the default separator
lyricloom models download mms         # old name: MMS_FA
lyricloom models download mtl         # old name: the singing model
lyricloom models download nltk        # old name: the NLTK data
```

The packaged Windows and Linux GUI builds are windowed applications and do not expose this console
command; use the Models window or the setup assistant, or a source/pipx install for the CLI.

Downloads are HTTPS only. Each file is written to a `.part` file, resumed with an HTTP `Range`
request when the server supports it, retried with a short backoff, and moved into place only after
its exact size and pinned SHA-256 match. A checksum mismatch deletes the `.part` file. A resumed
download keeps its partial file when you cancel.

LyricLoom never downloads a model while processing a song: before a heavy stage it checks the
resolved files and fails the track with an actionable message naming the missing models and the
`lyricloom models download` command. A queue also checks its models first and offers to download
what is missing before it starts.

### What each download source is

| Model | Source | Notes |
|---|---|---|
| Whisper models | Hugging Face `ggerganov/whisper.cpp`, pinned commit | Verifies the pinned SHA-256 and size. |
| Vocal separators | audio-separator's model registry on GitHub, downloaded by LyricLoom | Verifies every file, including the YAML/data files and `download_checks.json`. |
| MMS_FA | PyTorch/FAIR model host | Writes `model.pt` to `<models>/torch/hub/checkpoints`. |
| LyricsAlignment-MTL | GitHub `jhuang448/LyricsAlignment-MTL`, pinned commit | Verifies the pinned SHA-256. |
| NLTK data | NLTK data repository, pinned commit | Extracts the corpora under `<models>/nltk`. |
| whisper.cpp BLAS/cuBLAS | `ggml-org/whisper.cpp` v1.9.2 release assets | Setup assistant only; pinned size and SHA-256, tested with `--help`. |

The exact hosts and what each request contains are in [docs/privacy.md](privacy.md#model-downloads).

### If the models are already present

If you copied a models folder from another machine, upgraded an existing install or installed a
model by hand, the Models window and `models status` show those files as ready and you can skip the
download. If a file is reported missing or incomplete, download it again or replace it using the
offline layout below.

## Offline install

LyricLoom can run without internet access if the models and a `whisper-cli` binary are already
present. Lyric search still needs a network connection unless the lyrics are cached or you paste
them manually.

1. On a connected machine, install the same LyricLoom version. Use the Models window, or a source/pipx
   install and run:

   ```bash
   lyricloom models download all-defaults
   ```

2. Find the models root with the Models window or `lyricloom doctor` (source/pipx), or use the default
   path.
3. Copy the entire models root to the offline machine, preserving the layout shown above.
4. Copy the NLTK data directory (`~/nltk_data` or `%USERPROFILE%\nltk_data`) if you want the English
   singing model to work offline.
5. Make sure `whisper-cli` is present on the offline machine:
   - bundled with the Windows build, or
   - in `~/.local/share/lyricloom/bin` / `%LOCALAPPDATA%\LyricLoom\bin`, or
   - on `PATH`.
6. Point the offline machine at the copied folder if it is not the default:

   ```powershell
   # Windows, current PowerShell session
   $env:LYRICLOOM_MODELS = "E:\LyricLoomModels"
   lyricloom doctor
   ```

   ```bash
   # Linux
   export LYRICLOOM_MODELS=/mnt/models/lyricloom
   lyricloom doctor
   ```

7. Run a single test song before processing a library.

### Manual file placement

If you cannot use the download command, put the files here:

| File | Destination |
|---|---|
| `ggml-large-v3.bin` (or another `ggml-*.bin`) | `<models>/ggml-large-v3.bin` |
| Separator checkpoint and YAML | `<models>/separator/` |
| `download_checks.json` | `<models>/separator/` (the audio-separator registry snapshot) |
| MMS_FA `model.pt` | `<models>/torch/hub/checkpoints/model.pt` |
| `checkpoint_MTL` | `<models>/mtl/checkpoints/checkpoint_MTL` |
| NLTK zips or extracted corpora | `<models>/nltk/` or an existing `NLTK_DATA` directory |

The MMS checkpoint filename is the one torchaudio expects; keep it named `model.pt`. Files placed by
hand have no `.verified.json` sidecar yet. When the size matches they show as `unverified` and are
used at once; **Verify** in the Models window (or `lyricloom models verify`) hashes them once and
marks them `ready`.

### Choosing whisper-cli

The `whisper_cli` setting points at a specific whisper.cpp binary, for example a Vulkan or CUDA
build. The `LYRICLOOM_WHISPER_CLI` environment variable does the same. Precedence is:

1. the `whisper_cli` setting (or `LYRICLOOM_WHISPER_CLI`),
2. the bundled `whisper-cli`,
3. a developer checkout's `tools/bin`,
4. `%LOCALAPPDATA%\LyricLoom\bin` (`~/.local/share/lyricloom/bin` on Linux),
5. `PATH`.

The setup assistant's **Faster transcription** choice points `whisper_cli` at an installed BLAS or
cuBLAS build. **Use the bundled whisper.cpp** clears the setting again. The binary must exist and
support the model file. `lyricloom doctor` prints the path in use and whether it exists.

`LYRICLOOM_WHISPER_MODEL` still works as a 2.0 compatibility override. A catalog model id, a
catalog file name in the models folder, or the path of another existing `.bin` file selects the
transcription model for every song without a per-song choice, ahead of the per-language choices.
An unusable value is ignored with a warning in the log. Prefer the model catalog for new setups.

Any whisper.cpp-compatible GGML `.bin` file can be registered as a custom model with
`lyricloom models add transcribe <path>`.

## Verify and repair

In a source or pipx install:

```bash
lyricloom doctor
lyricloom models list
lyricloom models verify whisper-large-v3
lyricloom models repair whisper-large-v3
```

`models verify [id ...]` recomputes the full SHA-256 of every file. Without an id it verifies the
whole catalog and every custom model. The normal status check trusts the small `<file>.verified.json`
sidecar when the file's size and modification time still match, so start-up does not hash several
gigabytes every time. A state is one of:

- `ready`: the file is present and verified;
- `missing`: the file is not there;
- `corrupt`: the size or digest does not match;
- `unverified`: the file has the expected size but its digest has not been checked yet (for example
  a file copied by hand, or a model downloaded by LyricLoom 2.0). Processing accepts it; verifying
  it hashes it once and makes it `ready`.

`models repair <id>` deletes that catalog model's files, sidecar and partial download, then downloads
them again. It refuses custom models because those are your own files.

In the packaged GUI, the Models window shows the same states and has **Verify** and **Repair**
buttons. If a model is corrupt, repair it without touching the others. The per-track log names the
exact missing file when a stage cannot start.

For WSL, remember that MMS and MTL can live inside the Linux filesystem. The Windows doctor check
does not see the WSL-only files. See [docs/wsl-rocm.md](wsl-rocm.md#6-models-copy-or-point).

## The `[#models:...]` tag and "made with other models"

Every successful `.lrc` records the models that produced its timing:

```text
[#models:transcribe=whisper-large-v3;separate=separator-mel-band-roformer;align=align-mms-fa;singing=singing-mtl]
```

- `transcribe` is the Whisper model used for the transcript and anchors.
- `separate` is the vocal separator.
- `align` is the forced-alignment model (MMS_FA by default).
- `singing` appears only when the English singing model timed the words. When English falls back to
  CTC, or the song is another language, the tag has no `singing` entry.

The ids match `lyricloom models list`, the Models window and the `model_choices` setting. A per-song
**Process with other models…** run records its own ids. The library compares the tag with the current
choices and shows the song under **Made with other models**, with a tooltip listing the differences.
The `.lrc` is **not** marked pending just because a model changed; **Redo with current models**
reprocesses it deliberately. See [docs/lrc-format.md](lrc-format.md#about-models).

## Upgrading from 2.0

Upgrading keeps existing work:

- Settings, the library choice, the kept vocal stems and the work cache stay in the same per-user
  folders.
- A stage cache written by 2.0 has no model fingerprint. It is accepted and rewritten with the
  current fingerprint when that stage still uses the catalog default models and the song has no
  per-song override. If you changed the model, the affected stage is recomputed.
- A kept vocal stem written by 2.0 has no manifest. It is reused when it is newer than the audio
  file and the separator is still the catalog default; LyricLoom then writes the manifest. If the
  audio changed or you chose another separator, the old stem is moved aside and separation runs
  again.
- 2.0 model files are found in the same models root and shown as ready.
- Existing `.lrc` files are kept. A new engine version can still cause a song to be processed again
  when you run it normally; the previous `.lrc` is backed up first.

In WSL, LyricLoom prefers copies of the separator, MMS and MTL files inside the Linux filesystem
(`wsl_models_dir`, `wsl_torch_home`, `wsl_mtl_checkpoint`) when their size matches, and falls back to
the Windows files through `/mnt`. See [docs/wsl-rocm.md](wsl-rocm.md#6-models-copy-or-point).

## Deleting models

Close LyricLoom first. Then delete the model files or the whole models root:

```powershell
# Windows
Remove-Item -LiteralPath "$env:LOCALAPPDATA\LyricLoom\models" -Recurse -Force
```

```bash
# Linux
rm -rf ~/.local/share/lyricloom/models
```

You can also delete only one model:

```powershell
Remove-Item "$env:LOCALAPPDATA\LyricLoom\models\ggml-large-v3.bin"
```

What happens next:

| Deleted | Effect |
|---|---|
| Whisper model | Transcription fails with a message naming the file and the download command. |
| Separator model | New separations fail; songs with already-kept vocal stems can still be aligned only when their manifest matches. |
| MMS_FA | CTC alignment fails; English may still use MTL, but non-English tracks cannot align. |
| MTL checkpoint | English falls back to MMS_FA/CTC; processing continues. |
| NLTK data | English falls back to CTC; processing continues. |

Deleting the models does **not** delete your `.lrc` files, the kept vocal stems or the work cache. It
also does not affect the audio files.

To free space without losing the models, delete the work cache and the kept vocal stems instead; they
can be recreated. See
[docs/install-windows.md](install-windows.md#where-settings-and-caches-live) and
[docs/privacy.md](privacy.md#local-data).

## Licenses and commercial use

| Component | License | Notes |
|---|---|---|
| Whisper large-v3 weights | MIT (OpenAI Whisper) | whisper.cpp is MIT. |
| Mel-Band RoFormer checkpoint | Check the upstream model card | Not declared consistently; verify before commercial use. |
| BS-RoFormer and MDX-Net checkpoints | Check the audio-separator registry | Each upstream model has its own terms. |
| MMS_FA weights | **CC-BY-NC 4.0** | **Non-commercial.** Replacing this path is required for commercial use. |
| LyricsAlignment-MTL code | MIT | Check the upstream checkpoint's terms. |
| NLTK data | Per package | See the NLTK data index. |

LyricLoom's GPL-3.0-or-later license covers LyricLoom's source, not the model weights. The
non-commercial MMS_FA restriction applies even if you use LyricLoom under the GPL. Read
[THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md) for the full list and source links.

This page is not legal advice. If you plan to use LyricLoom commercially or redistribute a build with
models, review the model licenses yourself.
