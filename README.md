# LyricLoom

**Word-by-word synced lyrics for the songs you already own.**

LyricLoom takes the official lyrics of a song, aligns them against the isolated vocals, and writes an enhanced `.lrc` file next to the audio. Every word gets its own start and end time, so the lyrics can light up word by word in the built-in karaoke player or in MusicBee with the optional [Starry Karaoke](https://github.com/nishizumi-maho/MusicBee-StarryKaraoke) plugin.

LyricLoom 2.0.0 is free software under the **GNU GPL v3 or later**. The interface is English-only. Windows and Linux are the supported platforms.

[![CI](https://github.com/nishizumi-maho/lyricloom/actions/workflows/ci.yml/badge.svg)](https://github.com/nishizumi-maho/lyricloom/actions/workflows/ci.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)](LICENSE)
![Version](https://img.shields.io/badge/version-2.0.0-informational)
![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey)

<!-- Release badge: add the latest-release badge after the first public GitHub Release is published. -->

- **Repository:** <https://github.com/nishizumi-maho/lyricloom>
- **Releases and downloads:** <https://github.com/nishizumi-maho/lyricloom/releases>
- **Starry Karaoke for MusicBee:** <https://github.com/nishizumi-maho/MusicBee-StarryKaraoke>

## Contents

- [What it does](#what-it-does)
- [Screenshots](#screenshots)
- [Features](#features)
- [Quick start on Windows](#quick-start-on-windows)
- [Quick start on Linux](#quick-start-on-linux)
- [Command line](#command-line)
- [GPU options](#gpu-options)
- [Models and download sizes](#models-and-download-sizes)
- [Output format](#output-format)
- [Privacy](#privacy)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [License and credits](#license-and-credits)

## What it does

LyricLoom is not a lyrics downloader that stops at line-level timing. It builds a karaoke-grade timing track:

1. Reads the artist, title, album and duration from your audio tags.
2. Finds the official lyric on public lyrics sites. A lyric that already has word timing is also checked against the audio.
3. Separates the vocals from the instrumental with Mel-Band RoFormer. If the same folder has the song's own instrumental or off-vocal track, LyricLoom can subtract it first to give the separator a cleaner starting point.
4. Transcribes the isolated vocals with Whisper large-v3 through whisper.cpp. The transcript is used to find reliable anchors and to check which lyric candidate really matches what is sung.
5. Aligns every word of the official lyric against the audio, using the LyricsAlignment-MTL singing model for English and MMS forced alignment for other languages.
6. Writes `<song>.lrc` in enhanced LRC format, with one timestamp per word.

The audio file is only read, never modified. The official lyric is kept as `<song>.original.lrc`, and an existing `.lrc` is backed up before it is replaced.

The app can process one song or a whole library, mark uncertain lines for review, and lets you fix timings by hand. A source or pipx install also exposes the same engine as a command line for scripts and servers.

## Screenshots

![LyricLoom main window](docs/images/main-window.png)

*The main window: library status, lyric source and confidence, the preview player and the word editor.*

![LyricLoom Karaoke view](docs/images/karaoke.png)

*The built-in karaoke player. No MusicBee or browser is needed; the current word is highlighted as it is sung.*

The MusicBee option uses the separate [Starry Karaoke](https://github.com/nishizumi-maho/MusicBee-StarryKaraoke) plugin, which has its own screenshots and documentation.

## Features

### Lyrics and timing

- Word-level timestamps written as enhanced LRC `<mm:ss.xx>` tags.
- Official lyrics are preferred. Whisper transcription is used as the lyric only when every public source fails, and that track is marked for review.
- Lyric search across LRCLIB, NetEase, QQ Music, Uta-Net, Genius, and a DuckDuckGo web fallback. Sites that block scripted requests are skipped, not worked around.
- Ready-made word timing from a source (for example NetEase YRC) is compared with the audio; a line is only accepted when it agrees closely, otherwise LyricLoom's own alignment is used.
- Whisper anchors keep a single alignment mistake from drifting across the whole song.
- Per-line confidence and a `review` status for uncertain lines.
- Japanese lyrics are split with MeCab/IPADic, including inline furigana. Both `<song>.japanese.lrc` and `<song>.romaji.lrc` are kept; the main `.lrc` uses the script you choose.
- Songs with no official lyric can be aligned from lyrics you paste into the app, as long as the song has been processed once before.

### Processing and library

- Library scanner with All, Review, Pending, Failed, Other and Done filters.
- Process selected, process pending, stop after the current track, force reprocessing.
- Redo selected: deletes only LyricLoom's word timing and re-aligns using the cached vocals and transcript.
- Per-stage cache, so changing one stage does not repeat the expensive separation and transcription work.
- Atomic writes. An existing `.lrc` becomes `.lrc.bak`, then `.lrc.bak1`, and so on.
- Batch runs continue when one track fails; the error is shown in the table and written to that track's log.
- Built-in **Karaoke** window: a full-screen starry player with word-by-word highlighting, previous/next line context, seek, volume and "Vocals only". Keyboard: Space, arrows, F11, Esc.
- Main-window player and word editor: play-line, nudge ±10/50 ms, add/delete/insert words and lines, merge, paste-and-realign, save.
- Optional AssemblyAI transcription for difficult tracks or Japanese songs, only when you turn on cloud transcription and add a key.

### Platforms and hardware

- Windows installer and a portable ZIP.
- Native Linux packages/source install.
- Windows default is CPU for separation and forced alignment; whisper.cpp can use Vulkan when the bundled build supports it.
- AMD GPUs on Windows can run separation, forced alignment and the English singing model inside WSL 2 with ROCm. The app stays on Windows.
- Linux can use CUDA or ROCm PyTorch for separation and MMS alignment. In 2.0.0 the English singing model runs on the CPU on Linux.
- No telemetry, no account, and no audio upload unless you explicitly configure AssemblyAI.

## Quick start on Windows

These are the short steps. The full walkthrough, including SmartScreen, portable mode, updates and uninstall, is in **[docs/install-windows.md](docs/install-windows.md)**.

### 1. Install

1. Open the [Releases page](https://github.com/nishizumi-maho/lyricloom/releases) and download `LyricLoom-Setup-2.0.0.exe` (installer) or `LyricLoom-2.0.0-win64.zip` (portable).
2. For the installer, run it and follow the wizard. It installs per-user under `%LOCALAPPDATA%\Programs\LyricLoom`, needs no administrator rights, and creates a Start-menu shortcut (a desktop shortcut is optional).
3. For the portable ZIP, extract it to a folder you can write to, for example `D:\Apps\LyricLoom`, and run `LyricLoom.exe` from there.
4. If Windows SmartScreen says "Windows protected your PC", choose **More info > Run anyway** only after checking that the file came from the official Releases page.

You do not need Python, CUDA or a separate Whisper installation for the normal Windows build. The installer includes the app, the worker and `whisper-cli`; it does **not** include the large models.

### 2. First run

1. Start **LyricLoom**.
2. Click **Library…** and choose the folder that contains your music. Subfolders are included.
3. The first-run model dialog lists the missing models and downloads them to `%LOCALAPPDATA%\LyricLoom\models`. The download is about 5.3 GB, so keep the app open on a normal connection. You can skip a model and fetch it later from the same dialog. See [docs/models.md](docs/models.md).
4. Choose the Japanese script you want in the main `.lrc`: **Japanese: 日本語** or **Japanese: romaji**. Both script variants are always kept as separate files.
5. Optional: click **AssemblyAI key…** to store a key. Cloud transcription stays off by default: a stored key alone never uploads audio, and the separate cloud-transcription option must also be turned on. Leave everything off to keep the app fully local. See [Privacy](docs/privacy.md).

### 3. Process songs

1. Select one or more rows in the library table.
2. Click **Process selected**, or **Process pending** to run everything that has no LyricLoom `.lrc` yet.
3. Watch the status column. `review` means at least one line was uncertain; `failed` means the track could not be completed and the error is in its tooltip and log.
4. Leave **Force** off for normal runs. Turn it on only when you want to redo a song even though the same engine version already wrote its `.lrc`.
5. **Redo selected** is the gentler option: it removes the word timing LyricLoom wrote and aligns again, reusing the cached separation and transcript.

A CPU-only run is slow because vocal separation is the heavy stage. Start with a few songs before queueing a large library.

### 4. Listen and fix

1. Select a track to load it in the player.
2. Press **Play** for the compact player, or click **Karaoke** for the full-screen starry view. The current line is highlighted word by word; **Vocals only** plays the cached isolated vocal instead of the full mix.
3. In the Karaoke window: **Space** plays/pauses, **←/→** seek 5 seconds, **↑/↓** change volume, **F11** toggles fullscreen, **Esc** leaves fullscreen or closes the window.
4. In the main window, double-click a line to seek to it, or use **Play line**.
5. To fix a word, select its row and use the **−50 / −10 / +10 / +50 ms** buttons. Hold **Shift** while clicking to move the end instead of the start.
6. **Add word…**, **Delete word**, **Insert line…**, **Merge with line above** and **Delete line** edit the lyric structure.
7. **Paste lyrics…** replaces the lyric text and re-aligns it. The song must have been processed once so the cached vocals and transcript exist.
8. Click **Save**. The previous `.lrc` is kept as a `.bak` file.

### 5. Use it in MusicBee (optional)

The built-in player needs no extra software. If you use MusicBee, install the separate **Starry Karaoke** plugin and open it from **View > Starry Karaoke**. LyricLoom writes the word timing the plugin reads.

See **[docs/musicbee.md](docs/musicbee.md)** for installation and troubleshooting.

## Quick start on Linux

The full package list, desktop entry, whisper-cli build and GPU notes are in **[docs/install-linux.md](docs/install-linux.md)**.

### Option 1: release tarball (recommended)

```bash
tar -xzf LyricLoom-2.0.0-linux-x86_64.tar.gz
cd LyricLoom-2.0.0-linux-x86_64
./install.sh
```

This installs per-user to `~/.local/opt/LyricLoom`, creates the launcher `~/.local/bin/lyricloom`, and adds a menu entry. No `sudo` is needed. The tarball bundles `whisper-cli` but not the models; the first-run model dialog downloads them. Start **LyricLoom** from the menu, or run `lyricloom`.

Uninstall with:

```bash
~/.local/opt/LyricLoom/install.sh --uninstall
```

### Option 2: source or pipx

```bash
# Debian/Ubuntu package names; adapt for your distribution.
sudo apt install python3.11 python3.11-venv ffmpeg \
  libgl1 libegl1 libxkbcommon-x11-0 libxcb-cursor0 \
  libgstreamer1.0-0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav

git clone https://github.com/nishizumi-maho/lyricloom.git
cd lyricloom
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install "torch==2.4.1" "torchaudio==2.4.1" \
  --index-url https://download.pytorch.org/whl/cpu
python -m pip install -e .

# Build whisper.cpp (see docs/install-linux.md for CUDA/Vulkan options)
# Then put whisper-cli in ~/.local/share/lyricloom/bin or on PATH.

lyricloom models download all
lyricloom doctor
lyricloom-app
```

A source or pipx install also provides `lyricloom process <file-or-folder>`, which runs the same pipeline without the GUI. The path must be inside the library selected in the app (or the default `~/Music`). The packaged tarball's `lyricloom` launcher is the windowed app, not the full CLI.

`lyricloom cache status` reports the work-cache size and `lyricloom cache clean [--max-gb N]` deletes the oldest track caches first (never a track that is running). `lyricloom process` exits 0 when every track is done, review or skipped, 1 when any track failed, and 2 on a usage error.

## Command line

The GUI can also be started by another program:

```text
LyricLoom.exe --process "<file>" [<file> ...] [--redo]
LyricLoom.exe --open "<file>"
```

`--process` queues files (or folders) in the running window without taking focus, `--redo` redoes
their word timing, and `--open` selects a file in the library and brings the window forward. Paths
that do not exist or are not supported audio are ignored and reported. See
**[docs/command-line.md](docs/command-line.md)** for the single-instance behaviour, MusicBee
registry values and examples.

## GPU options

| Platform | Separation (Mel-Band RoFormer) | Forced alignment (MMS_FA) | English singing model (MTL) | Whisper transcription |
|---|---|---|---|---|
| **Windows, default** | CPU | CPU | CPU | whisper.cpp; Vulkan GPU if the bundled build supports it, otherwise CPU |
| **Windows + WSL 2 / ROCm (AMD)** | AMD GPU in WSL | AMD GPU in WSL | AMD GPU in WSL | whisper.cpp on Windows (Vulkan if available) |
| **Linux + CUDA or ROCm** | GPU | GPU | CPU in 2.0.0 | whisper.cpp as built (CPU, CUDA or Vulkan) |

- Native AMD GPU acceleration on Windows is not provided by LyricLoom. Use the WSL 2 path: **[docs/wsl-rocm.md](docs/wsl-rocm.md)**.
- If a WSL stage fails, LyricLoom falls back to the CPU and keeps processing. The status bar turns orange and the reason is written to the track log.
- In a source or pipx install, `lyricloom doctor` shows the paths, model status, `whisper-cli`, ffmpeg, and whether PyTorch can see CUDA/ROCm. The packaged Windows and Linux GUI builds are windowed applications; use the model dialog, the status bar and the direct WSL/PyTorch checks in the GPU docs if your build does not include the console command.

## Models and download sizes

The release artifacts do not include the large models. The first-run model dialog downloads them explicitly; they are not stored in git. Exact paths and offline instructions are in **[docs/models.md](docs/models.md)**.

| Model | Purpose | Approximate size | License |
|---|---|---:|---|
| Whisper large-v3 (`ggml-large-v3.bin`) | Anchors, transcript checks, last-resort lyrics | 3.1 GB | MIT |
| Mel-Band RoFormer vocals (`vocals_mel_band_roformer.ckpt`) | Isolates the vocal stem | 0.9 GB | Check the upstream model card |
| MMS_FA (torchaudio) | Multilingual CTC forced alignment | 1.2 GB | **CC-BY-NC 4.0 (non-commercial)** |
| LyricsAlignment-MTL (`checkpoint_MTL`) | Word timing for English singing | 66 MB | MIT (upstream) |
| NLTK data (`cmudict`, `averaged_perceptron_tagger`, `punkt`) | English grapheme-to-phoneme for MTL | Tens of MB | See the NLTK data packages |

Allow about **6 GB** for the models and extra space for the work cache and kept vocal stems. The MMS_FA weights are non-commercial; see **[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)** before commercial use.

## Output format

For `01 - Synthetic Song.flac`, LyricLoom writes `01 - Synthetic Song.lrc` next to the audio:

```lrc
[ti:Synthetic Song]
[ar:Demo Artist]
[re:LyricLoom 2.0.0]
[#source:uta-net conf:0.94]
[#engine:7]
[00:22.98]<00:22.98>こ<00:23.10>れ<00:23.30>は<00:23.50>合<00:24.05>成<00:24.30>の<00:24.62>歌<00:24.90>詞<00:25.12>で<00:25.30>す<00:25.62>
[00:26.10]<00:26.10>例<00:26.30>で<00:26.55>す<00:27.10>
- `[mm:ss.xx]` is the line start.
- Each `<mm:ss.xx>` is the start of the word or segment that follows it.
- A final `<mm:ss.xx>` with no text marks the end of the last segment.
- Text between tags is kept exactly as written: Japanese stays unspaced, Latin text carries its own spaces.
- Tags such as `[re:]`, `[#source:]`, `[#engine:]` and `[#review:]` are metadata. Ordinary LRC players ignore them and still show line-synced lyrics.

The full contract, including `.original.lrc`, the Japanese script variants and backup names, is in **[docs/lrc-format.md](docs/lrc-format.md)**.

## Privacy

LyricLoom has **no telemetry, no analytics and no account system**.

- Searching for lyrics sends the artist and title (and sometimes album/duration) to public lyrics providers over HTTPS.
- Model downloads contact GitHub, Hugging Face, PyTorch's model host, NLTK and the audio-separator model registry.
- Audio is processed locally by Whisper, the separator and the aligners.
- **Optional:** cloud transcription is off by default. It runs only when you turn on the separate cloud-transcription setting, keep an AssemblyAI API key, and allow cloud use for the run; any of those being off keeps the audio local. When it runs, LyricLoom uploads only the isolated vocal track (for example for Japanese songs, or tracks where local transcription is unusable). Remove the key or turn the setting off to disable it; the CLI also accepts `--no-cloud`.
- Settings, logs, caches and models stay in your per-user data folder.

Read **[docs/privacy.md](docs/privacy.md)** for the exact hosts, data and local paths. The short version is in **[PRIVACY.md](PRIVACY.md)**.

## Troubleshooting

In a source or pipx install, start with `lyricloom doctor`. It prints the data folder, library, model paths, whisper-cli/ffmpeg status, model readiness and PyTorch device availability. The packaged GUI is windowed; use its model dialog and status bar if your build does not include the console command.

| Problem | Where to look |
|---|---|
| No lyrics found | [docs/troubleshooting.md](docs/troubleshooting.md#no-lyrics-found) |
| `whisper-cli` or model missing | [docs/troubleshooting.md](docs/troubleshooting.md#whisper-cli-or-model-missing) |
| ffmpeg / separation errors | [docs/troubleshooting.md](docs/troubleshooting.md#ffmpeg) |
| No sound in the built-in player | [docs/troubleshooting.md](docs/troubleshooting.md#qt-multimedia-and-sound) |
| CUDA / ROCm not used | [docs/troubleshooting.md](docs/troubleshooting.md#cuda-or-rocm-not-used) |
| WSL setup or CPU fallback | [docs/wsl-rocm.md](docs/wsl-rocm.md) and [docs/troubleshooting.md](docs/troubleshooting.md#wsl) |
| SmartScreen, antivirus or permissions | [docs/troubleshooting.md](docs/troubleshooting.md#windows-smartscreen-and-antivirus) |
| Japanese shows the wrong script | [docs/troubleshooting.md](docs/troubleshooting.md#japanese-script) |
| MusicBee plugin shows nothing | [docs/musicbee.md](docs/musicbee.md#troubleshooting) |

Per-track logs are in `%LOCALAPPDATA%\LyricLoom\work\<hash>\log.txt` on Windows and `~/.local/share/lyricloom/work/<hash>/log.txt` on Linux.

## Development

Requirements: Python **3.11** (the project requires `>=3.11,<3.12`), Git, and ffmpeg for some stages. GPU work is optional.

Windows:

```powershell
git clone https://github.com/nishizumi-maho/lyricloom.git
cd lyricloom
.\scripts\setup-dev.ps1
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m lyricloom doctor
```

Linux:

```bash
git clone https://github.com/nishizumi-maho/lyricloom.git
cd lyricloom
bash scripts/setup-dev.sh
. .venv/bin/activate
pytest
ruff check .
```

Both setup scripts create a Python 3.11 environment with CPU-only PyTorch by default, which is what the public builds use. For CUDA/ROCm development, install the GPU wheels after the setup; see [docs/install-linux.md](docs/install-linux.md#cuda-and-rocm-pytorch).

The default test run deselects tests marked `gpu`; those need real models or a GPU toolchain. See **[CONTRIBUTING.md](CONTRIBUTING.md)** for the project layout, the lyric-source interface and pull-request guidelines. The pipeline and cache layout are documented in **[docs/architecture.md](docs/architecture.md)**.

## License and credits

LyricLoom is licensed under the **GNU General Public License, version 3 or later**. See **[LICENSE](LICENSE)**. Third-party components, model licenses and the non-commercial MMS_FA weights are listed in **[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)**.

LyricLoom builds on the work of many open-source projects and researchers, including:

- **OpenAI Whisper** and **whisper.cpp** by Georgi Gerganov and contributors.
- **LyricsAlignment-MTL** by Jiawen Huang and contributors.
- **Mel-Band RoFormer** and **audio-separator**.
- **PySide6 / Qt**, **PyTorch**, **torchaudio**, **librosa**, **mutagen**, **pykakasi**, **fugashi**, **ipadic**, **soxr**, **soundfile** and the other dependencies listed in `pyproject.toml`.
- **MusicBee** and the separate **Starry Karaoke** plugin, which is not part of LyricLoom and has its own MIT license.

The project was previously called **Lyrics Boca**. LyricLoom 2.0.0 keeps reading `.lrc` files and settings written by that name; see **[CHANGELOG.md](CHANGELOG.md)**.
