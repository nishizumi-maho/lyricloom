# Models

LyricLoom separates vocals, transcribes them and aligns lyrics with several large model files. They are not stored in the Git repository or in the release installers. This page explains what each model does, where it goes, how to download it, how to install it offline, and how to remove it.

The normal Windows installer and the Linux tarball show the **Models window** on first run and offer the missing models. A source or pipx install also has the `lyricloom models` command described below.

## At a glance

| Model | Used for | Approximate size | Default file |
|---|---|---:|---|
| Whisper large-v3 (ggml) | Word-level transcript, anchors, last-resort lyrics | 3.1 GB | `<models>/ggml-large-v3.bin` |
| Mel-Band RoFormer vocals | Isolating the vocal stem | 0.9 GB | `<models>/separator/vocals_mel_band_roformer.ckpt` |
| MMS_FA (torchaudio) | Multilingual CTC forced alignment | 1.2 GB | `<models>/torch/hub/checkpoints/model.pt` |
| LyricsAlignment-MTL | English singing-model word timing | 66 MB | `<models>/mtl/checkpoints/checkpoint_MTL` |
| NLTK data | English grapheme-to-phoneme for MTL | Tens of MB | `<models>/nltk` (or an existing `NLTK_DATA`) |

Suggested alternatives are in the same catalog: Whisper `ggml-large-v3-turbo.bin`, `ggml-medium.bin`
and `ggml-small.bin`; two other vocal separators (a BS-RoFormer model and an MDX-Net `.onnx`
model). Every catalog file has a pinned exact size and SHA-256. List them with
`lyricloom models list`.

Allow about **6 GB** for the models plus working space (the downloads themselves total about 5.3 GB). The kept vocal stems in the vocals cache can add several hundred MB per song if you process a large library.

## What each model does

### Whisper large-v3 (`ggml-large-v3.bin`)

Whisper transcribes the isolated vocals with word timestamps. LyricLoom uses that transcript to:

- find **anchors** — lines it is confident it heard — and split the song into short alignment blocks;
- check that a candidate lyric really matches what is sung;
- provide the lyric text itself when no public source has an acceptable version.

It runs through **whisper.cpp**, not the Python `openai-whisper` package. The Windows installer ships a CPU `whisper-cli`; a locally built Vulkan or CUDA build can replace it for GPU transcription. On Linux you build or install it yourself (see [docs/install-linux.md](install-linux.md#build-whisper-cli)).

The model is downloaded from the `ggerganov/whisper.cpp` repository on Hugging Face. LyricLoom uses
a pinned commit URL and checks the SHA-256 and size pinned in `lyricloom/models.py`; it never takes
the checksum from the same mutable API that serves the file.

### Mel-Band RoFormer (`vocals_mel_band_roformer.ckpt`)

This is the vocal separator. It takes the full mix (or the mix with a same-release instrumental subtracted) and produces a vocal stem. LyricLoom keeps a lossless FLAC copy outside the music library and a 16 kHz mono copy in the work cache for the aligners.

The model is distributed through **audio-separator**'s model registry. The checkpoint's license is not declared consistently in this repository or in every upstream model card. **Check the upstream model card/license before commercial use or redistribution.** The Mel-Band RoFormer architecture and the audio-separator code are separate from the weights.

### MMS_FA

MMS_FA is a multilingual wav2vec2 model from Meta, exposed through `torchaudio.pipelines.MMS_FA`. It performs CTC forced alignment for languages other than English, and it is the fallback for English when the singing model is unavailable. It is also used for Japanese and Portuguese.

**License: CC-BY-NC 4.0 (non-commercial).** This is a restriction on the model weights, not on LyricLoom's GPL source code. If you need commercial use, you must obtain a suitable license or replace this alignment path. See [THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md).

The checkpoint is cached by torchaudio under `$TORCH_HOME/hub/checkpoints`. LyricLoom sets `TORCH_HOME` to `<models>/torch` for its worker, so the default location is:

```text
<models>/torch/hub/checkpoints/
```

### LyricsAlignment-MTL (`checkpoint_MTL`)

This model was trained on sung English and gives better word timing than CTC on many English songs. LyricLoom uses it only for English; other languages use MMS_FA. It is attempted only when its checkpoint and NLTK data are ready, and if the worker still fails, English falls back to CTC and the track completes.

The inference code is vendored under `lyricloom/vendor/mtl` (MIT). The checkpoint is downloaded from the upstream LyricsAlignment-MTL repository (about 66 MB). Its license follows the upstream project; check the upstream repository if you plan to redistribute the weights.

The Windows app runs the model on the CPU by default. With WSL/ROCm enabled it runs inside WSL on the AMD GPU (see [docs/wsl-rocm.md](wsl-rocm.md)). On native Linux in 2.0.0 it runs on the CPU.

### NLTK data

The MTL model uses `g2p_en`, which needs three NLTK corpora:

- `cmudict`
- `averaged_perceptron_tagger` (and `averaged_perceptron_tagger_eng` on newer NLTK)
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
3. A developer checkout's `models/` directory, if it contains at least one `*.bin` file or a `separator/` folder.
4. The per-user default above.

The `LYRICLOOM_MODELS` override is useful for a large SSD, a shared read-only model folder, or an offline install.

### Full default layout

```text
<models>/
├── ggml-large-v3.bin
├── separator/
│   ├── vocals_mel_band_roformer.ckpt
│   └── vocals_mel_band_roformer.yaml
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

`<models>` is the root from the table above.

NLTK data can also live in an existing local NLTK data directory:

```text
Windows: %USERPROFILE%\nltk_data
Linux:   ~/nltk_data
```

In a source or pipx install, `lyricloom doctor` prints the models root and the status of each model. The GUI's Models window shows the same readiness information.

## Choosing models

Every stage's model is customizable, and a choice can differ per language:

```bash
lyricloom models list                                  # id, size, status, which languages choose it
lyricloom models use transcribe whisper-small          # default choice
lyricloom models use transcribe whisper-medium --lang ja
lyricloom models add separate "C:\Models\my-vocals.ckpt"
lyricloom models add separate UVR-MDX-NET-Voc-FT      # any name audio-separator's registry knows
```

Choices live in `settings.json` under `model_choices`:

```json
{
  "default": {"transcribe": "whisper-large-v3"},
  "languages": {"ja": {"transcribe": "whisper-large-v3-turbo"}},
  "custom": []
}
```

Resolution precedence is **per-song override > language choice > default choice > catalog
default**. A per-song override comes from the app's "Process with other models…" action or
`runner.process(..., models={"transcribe": "whisper-small"})`; it applies to that run only. Unknown
ids, a model for another stage, a model that does not suit the language, or a missing custom file
is logged and skipped, never a crash. Missing keys mean the catalog default.

A custom model lives in the settings file, records its own size and SHA-256 when it is added
(trust on first use), and is never overwritten by a catalog download. A custom separator file must
use a filename that audio-separator's registry knows; pass the model name instead if the file is
not present yet.

Changing a model invalidates the cached stages that used it and the stages after them, so only
the affected work is redone. A finished `.lrc` is not marked pending: the `.lrc` records what was
used in its [`#models` tag](lrc-format.md#about-models), and the app can show that a song was made
with other models.

## Download

### The first-run dialog

On Windows and in the Linux tarball, start LyricLoom and use the **Models window** that appears when files are missing. It lists each model, its size and its state, and starts only the downloads you approve. You can close it, process a song that only needs the models you already have, and reopen it from **Help > Models**.

The models are not bundled in the installer or tarball. Without network access, use the offline procedure below.

### The command line (source or pipx install)

```bash
lyricloom models list
lyricloom models download all-defaults
```

`download all-defaults` fetches the default model for each stage plus the NLTK data. It continues
with the remaining models if one download fails and prints a per-model result. You can fetch one
model by id, or use the old short names:

```bash
lyricloom models download whisper-large-v3-turbo
lyricloom models download separator-bs-roformer-vocals
lyricloom models download whisper      # old name: the default Whisper model
lyricloom models download separator   # old name: the default separator
lyricloom models download mms         # old name: MMS_FA
lyricloom models download mtl         # old name: the singing model
lyricloom models download nltk        # old name: the NLTK data
```

The packaged Windows and Linux GUI builds are windowed applications and do not expose this console command in 2.0.0; use the Models window (Help > Models), or a source/pipx install for the CLI.

Downloads are HTTPS only. Each file is written to a `.part` file, resumed with an HTTP `Range`
request when the server supports it, retried with a short backoff, and moved into place only
after its exact size and pinned SHA-256 match. A checksum mismatch deletes the `.part` file.
LyricLoom never downloads a model while processing a song: before a heavy stage it checks the
resolved files and fails the track with an actionable message naming the missing models and the
`lyricloom models download` command.

### What each download command does

| Command | Source | Notes |
|---|---|---|
| `models download whisper-large-v3` (or `whisper`) | Hugging Face `ggerganov/whisper.cpp`, pinned commit | Verifies the pinned SHA-256 and size. About 3 GB. |
| `models download separator-mel-band-roformer` (or `separator`) | audio-separator's model registry on GitHub, downloaded by LyricLoom | Verifies every file, including the YAML config. About 0.9 GB. |
| `models download align-mms-fa` (or `mms`) | PyTorch model host | Writes `model.pt` to `<models>/torch/hub/checkpoints`. |
| `models download singing-mtl` (or `mtl`) | GitHub `jhuang448/LyricsAlignment-MTL`, pinned commit | Verifies the pinned SHA-256. About 66 MB. |
| `models download singing-nltk-data` (or `nltk`) | NLTK data repository, pinned commit | Extracts the corpora under `<models>/nltk`. |

### If the models are already present

If you copied a models folder from another machine or upgraded an existing install, the Models window and `models status` show those files as ready and you can skip the download. If a file is reported missing or incomplete, download it again or replace it using the offline layout below.

## Offline install

LyricLoom can run without internet access if the models and a `whisper-cli` binary are already present. Lyric search still needs a network connection unless the lyrics are cached or you paste them manually.

1. On a connected machine, install the same LyricLoom version. Use the Models window, or a source/pipx install and run:

   ```bash
   lyricloom models download all
   ```

2. Find the models root with the Models window or `lyricloom doctor` (source/pipx), or use the default path.
3. Copy the entire models root to the offline machine, preserving the layout shown above.
4. Copy the NLTK data directory (`~/nltk_data` or `%USERPROFILE%\nltk_data`) if you want the English singing model to work offline.
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
| `ggml-large-v3.bin` | `<models>/ggml-large-v3.bin` |
| `vocals_mel_band_roformer.ckpt` and `.yaml` | `<models>/separator/` |
| `download_checks.json` | `<models>/separator/` (the audio-separator registry snapshot) |
| MMS_FA `model.pt` | `<models>/torch/hub/checkpoints/model.pt` |
| `checkpoint_MTL` | `<models>/mtl/checkpoints/checkpoint_MTL` |
| NLTK zips or extracted corpora | `<models>/nltk/` or an existing `NLTK_DATA` directory |

The MMS checkpoint filename is the one torchaudio expects; keep it named `model.pt`.

### Choosing whisper-cli

The `whisper_cli` setting points at a specific whisper.cpp binary, for example a Vulkan or CUDA
build. The `LYRICLOOM_WHISPER_CLI` environment variable does the same. Precedence is:

1. the `whisper_cli` setting (or `LYRICLOOM_WHISPER_CLI`),
2. the bundled `whisper-cli`,
3. a developer checkout's `tools/bin`,
4. `%LOCALAPPDATA%\LyricLoom\bin` (`~/.local/share/lyricloom/bin` on Linux),
5. `PATH`.

The binary must exist and support the model file. `lyricloom doctor` prints the path in use and
whether it exists. `LYRICLOOM_WHISPER_MODEL` is still honoured as a 2.0 compatibility override: a
catalog model id, a catalog file name in the models folder, or another existing `.bin` file there
selects the transcribe model for every track. Prefer the model catalog for new installs:

```bash
lyricloom models use transcribe whisper-large-v3-turbo
```

Any whisper.cpp-compatible GGML `.bin` file can be registered as a custom model with `lyricloom
models add transcribe <path>`.

## Verify

In a source or pipx install:

```bash
lyricloom doctor
lyricloom models list
lyricloom models verify whisper-large-v3
```

In the packaged GUI, the Models window is the readiness view.

`models list` reports the stage, id, exact size, state and the languages that choose each model:

```text
stage      id                                      size  status     chosen for
transcribe whisper-large-v3 *                    2.9 GB  ready      default (implicit)
...
```

`models verify [id]` recomputes the full SHA-256 (the normal status check trusts a small
`<file>.verified.json` sidecar with the file's size, mtime and digest, so start-up does not hash
several gigabytes every time). A file whose pinned size matches but that has no sidecar is
`unverified`: processing accepts it, and the Models window offers Verify; only an explicit
Verify/Repair or a download hashes it. A state is one of `ready`, `missing`, `corrupt` or
`unverified`.
If a model is corrupt, repair it without touching the others:

```bash
lyricloom models download <id>          # downloads it again after you delete the old file
```

To repair in one step, delete the file and its `.verified.json` sidecar and run the download
command again. The per-track log names the exact missing file when a stage cannot start.

For WSL, remember that MMS and MTL can live inside the Linux filesystem. The Windows `doctor` check does not see the WSL-only files. See [docs/wsl-rocm.md](wsl-rocm.md#8-verify).

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
| Separator model | New separations fail; songs with already-kept vocal stems can still be aligned only when the kept-stem manifest matches. |
| MMS_FA | CTC alignment fails; English may still use MTL, but non-English tracks cannot align. |
| MTL checkpoint | English falls back to MMS_FA/CTC; processing continues. |
| NLTK data | English falls back to CTC; processing continues. |

Deleting the models does **not** delete your `.lrc` files, the kept vocal stems, or the work cache. It also does not affect the audio files.

To free space without losing the models, delete the work cache and the kept vocal stems instead; they can be recreated. See [docs/install-windows.md](install-windows.md#where-settings-and-caches-live) and [docs/privacy.md](privacy.md#local-data).

## Licenses and commercial use

| Component | License | Notes |
|---|---|---|
| Whisper large-v3 weights | MIT (OpenAI Whisper) | whisper.cpp is MIT. |
| Mel-Band RoFormer checkpoint | Check the upstream model card | Not declared consistently; verify before commercial use. |
| MMS_FA weights | **CC-BY-NC 4.0** | **Non-commercial.** Replacing this path is required for commercial use. |
| LyricsAlignment-MTL code | MIT | Check the upstream checkpoint's terms. |
| NLTK data | Per package | See the NLTK data index. |

LyricLoom's GPL-3.0-or-later license covers LyricLoom's source, not the model weights. The non-commercial MMS_FA restriction applies even if you use LyricLoom under the GPL. Read [THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md) for the full list and source links.

This page is not legal advice. If you plan to use LyricLoom commercially or redistribute a build with models, review the model licenses yourself.
