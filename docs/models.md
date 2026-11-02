# Models

LyricLoom separates vocals, transcribes them and aligns lyrics with several large model files. They are not stored in the Git repository or in the release installers. This page explains what each model does, where it goes, how to download it, how to install it offline, and how to remove it.

The normal Windows installer and the Linux tarball show a **first-run model dialog** that downloads the missing models. A source or pipx install also has the `lyricloom models` command described below.

## At a glance

| Model | Used for | Approximate size | Default file |
|---|---|---:|---|
| Whisper large-v3 (ggml) | Word-level transcript, anchors, last-resort lyrics | 3.1 GB | `<models>/ggml-large-v3.bin` |
| Mel-Band RoFormer vocals | Isolating the vocal stem | 0.9 GB | `<models>/separator/vocals_mel_band_roformer.ckpt` |
| MMS_FA (torchaudio) | Multilingual CTC forced alignment | 1.2 GB | `<models>/torch/hub/checkpoints/*.pth` |
| LyricsAlignment-MTL | English singing-model word timing | 66 MB | `<models>/mtl/checkpoints/checkpoint_MTL` |
| NLTK data | English grapheme-to-phoneme for MTL | Tens of MB | `~/nltk_data` (or `NLTK_DATA`) |

Allow about **6 GB** for the models plus working space (the downloads themselves total about 5.3 GB). The kept vocal stems in the vocals cache can add several hundred MB per song if you process a large library.

## What each model does

### Whisper large-v3 (`ggml-large-v3.bin`)

Whisper transcribes the isolated vocals with word timestamps. LyricLoom uses that transcript to:

- find **anchors** — lines it is confident it heard — and split the song into short alignment blocks;
- check that a candidate lyric really matches what is sung;
- provide the lyric text itself when no public source has an acceptable version.

It runs through **whisper.cpp**, not the Python `openai-whisper` package. The Windows build normally includes a Vulkan-enabled `whisper-cli`; on Linux you build or install it yourself (see [docs/install-linux.md](install-linux.md#build-whisper-cli)).

The model is downloaded from the `ggerganov/whisper.cpp` repository on Hugging Face. LyricLoom checks the published SHA-256 when it downloads the file. If Hugging Face's checksum endpoint is unavailable, it falls back to the checksum pinned in the source.

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

This model was trained on sung English and gives better word timing than CTC on many English songs. LyricLoom uses it only for English; other languages use MMS_FA. If the checkpoint or its Python code is missing, English falls back to CTC and the track still completes.

The inference code is vendored under `lyricloom/vendor/mtl` (MIT). The checkpoint is downloaded from the upstream LyricsAlignment-MTL repository (about 66 MB). Its license follows the upstream project; check the upstream repository if you plan to redistribute the weights.

The Windows app runs the model on the CPU by default. With WSL/ROCm enabled it runs inside WSL on the AMD GPU (see [docs/wsl-rocm.md](wsl-rocm.md)). On native Linux in 2.0.0 it runs on the CPU.

### NLTK data

The MTL model uses `g2p_en`, which needs three NLTK corpora:

- `cmudict`
- `averaged_perceptron_tagger`
- `punkt`

They are small compared with the neural models. NLTK downloads them to its own data directory (`~/nltk_data` on Linux, `%USERPROFILE%\nltk_data` on Windows, or `NLTK_DATA` if set). The MTL worker also tries to download missing corpora on first use. For an offline machine, copy the NLTK data directory or set `NLTK_DATA`.

NLTK software is Apache-2.0; the individual data packages have their own terms. See the NLTK data package pages.

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
│   └── vocals_mel_band_roformer.ckpt
├── mtl/
│   └── checkpoints/
│       └── checkpoint_MTL
└── torch/
    └── hub/
        └── checkpoints/
            └── <torchaudio MMS_FA checkpoint>.pth
```

`<models>` is the root from the table above.

NLTK data is separate:

```text
Windows: %USERPROFILE%\nltk_data
Linux:   ~/nltk_data
```

In a source or pipx install, `lyricloom doctor` prints the models root and the status of each model. The GUI's model dialog shows the same readiness information.

## Download

### The first-run dialog

On Windows and in the Linux tarball, start LyricLoom and use the **model dialog** that appears when files are missing. It lists each model, its size and its state, and starts only the downloads you approve. You can close it, process a song that only needs the models you already have, and reopen it later.

The models are not bundled in the installer or tarball. Without network access, use the offline procedure below.

### The command line (source or pipx install)

```bash
lyricloom models status
lyricloom models download all
```

`download all` fetches Whisper, the separator, MMS_FA, MTL and NLTK data. You can fetch one at a time:

```bash
lyricloom models download whisper
lyricloom models download separator
lyricloom models download mms
lyricloom models download mtl
lyricloom models download nltk
```

The packaged Windows and Linux GUI builds are windowed applications and do not expose this console command in 2.0.0; use their model dialog, or a source/pipx install for the CLI.

Downloads are written to a `.part` file and moved into place only after the size/checksum check. LyricLoom does not download the large models in the background; the first-run dialog or the explicit command is the trigger.

### What each download command does

| Command | Source | Notes |
|---|---|---|
| `models download whisper` | Hugging Face `ggerganov/whisper.cpp` | Verifies SHA-256. About 3 GB. |
| `models download separator` | audio-separator's model registry | Runs in a worker so the GUI is not blocked. |
| `models download mms` | torchaudio / PyTorch model host | Writes to `<models>/torch/hub/checkpoints`. |
| `models download mtl` | GitHub `jhuang448/LyricsAlignment-MTL` | Verifies the pinned SHA-256. About 66 MB. |
| `models download nltk` | NLTK data index | Writes to the NLTK data directory, not the models root. |

### If the models are already present

If you copied a models folder from another machine or upgraded an existing install, the model dialog and `models status` show those files as ready and you can skip the download. If a file is reported missing or incomplete, download it again or replace it using the offline layout below.

## Offline install

LyricLoom can run without internet access if the models and a `whisper-cli` binary are already present. Lyric search still needs a network connection unless the lyrics are cached or you paste them manually.

1. On a connected machine, install the same LyricLoom version. Use the model dialog, or a source/pipx install and run:

   ```bash
   lyricloom models download all
   ```

2. Find the models root with the model dialog or `lyricloom doctor` (source/pipx), or use the default path.
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
| `vocals_mel_band_roformer.ckpt` | `<models>/separator/vocals_mel_band_roformer.ckpt` |
| MMS_FA `*.pth` | `<models>/torch/hub/checkpoints/` |
| `checkpoint_MTL` | `<models>/mtl/checkpoints/checkpoint_MTL` |
| NLTK `cmudict`, `averaged_perceptron_tagger`, `punkt` | `~/nltk_data` or `%USERPROFILE%\nltk_data` |

The MMS checkpoint filename is owned by torchaudio. Copy the whole `hub/checkpoints` directory from a working install rather than renaming files.

### Using a different Whisper model

`LYRICLOOM_WHISPER_MODEL` changes the expected file name inside the models root:

```powershell
$env:LYRICLOOM_WHISPER_MODEL = "ggml-large-v3-turbo.bin"
```

The file must be a whisper.cpp-compatible GGML model, and `whisper-cli` must support it. The tested default is `ggml-large-v3.bin`; other models change speed, memory use and accuracy.

## Verify

In a source or pipx install:

```bash
lyricloom doctor
lyricloom models status
```

In the packaged GUI, the model dialog is the readiness view.

`models status` reports:

```text
models directory: ...
  whisper    ready
  separator  ready
  mtl        ready
  mms        ready
  nltk       ready
  ffmpeg     ready
```

A model can be present but unusable (for example, a truncated download). `lyricloom doctor` checks basic file presence and size; if a stage still fails, read the per-track log for the actual error. The GUI model dialog uses the same checks.

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
| Whisper model | Transcription fails until it is downloaded again. |
| Separator model | New separations fail; songs with already-kept vocal stems can still be aligned. |
| MMS_FA | CTC alignment fails; English may still use MTL, but non-English tracks cannot align. |
| MTL checkpoint | English falls back to MMS_FA/CTC; processing continues. |
| NLTK data | MTL may try to download it; offline English MTL may fail and fall back to CTC. |

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
