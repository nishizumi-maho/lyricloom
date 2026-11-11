# Install LyricLoom on Linux

LyricLoom 2.1.1 runs natively on 64-bit Linux. It needs **Python 3.11** (the project requires `>=3.11,<3.12`), Qt 6 runtime libraries, GStreamer for the built-in player, and ffmpeg for the audio stages.

The commands below use Debian/Ubuntu package names. Fedora, Arch and other distributions have equivalents; the important pieces are Qt 6, the XCB platform plugins, GStreamer with the usual codec plugins, ffmpeg, and Python 3.11.

This page covers:

- [Install the release tarball](#install-the-release-tarball)
- [Install the system packages](#install-the-system-packages)
- [Get Python 3.11](#get-python-311)
- [Install from source with a virtual environment](#install-from-source-with-a-virtual-environment)
- [Install with pipx](#install-with-pipx)
- [Run LyricLoom](#run-lyricloom)
- [Add a desktop entry](#add-a-desktop-entry)
- [Download the models](#download-the-models)
- [Build whisper-cli](#build-whisper-cli)
- [CUDA and ROCm PyTorch](#cuda-and-rocm-pytorch)
- [Troubleshooting](#troubleshooting)

## Install the release tarball

The release page provides a prebuilt Linux bundle:

```text
LyricLoom-2.1.1-linux-x86_64.tar.gz
```

It is built on Ubuntu 22.04 and contains the application, `LyricLoomWorker`, `whisper-cli`, Qt, and a per-user installer. It does not contain the large models.

```bash
tar -xzf LyricLoom-2.1.1-linux-x86_64.tar.gz
cd LyricLoom-2.1.1-linux-x86_64
./install.sh
```

By default the installer:

- installs the app to `~/.local/opt/LyricLoom`;
- creates the launcher `~/.local/bin/lyricloom`;
- adds `~/.local/share/applications/lyricloom.desktop` with an absolute `Exec` path;
- needs no `sudo` and writes nothing outside your home directory (or `$XDG_DATA_HOME`).

Override the prefix with `PREFIX=/some/prefix ./install.sh`, or the app directory with `LYRICLOOM_INSTALL_DIR=/some/dir ./install.sh`.

Start **LyricLoom** from the menu, or run:

```bash
lyricloom
```

The tarball's `lyricloom` launcher opens the GUI. For the engine command line (`doctor`, `models`, `process`), use a source or pipx install.

Uninstall:

```bash
~/.local/opt/LyricLoom/install.sh --uninstall
```

Uninstalling removes the app, launcher and menu entry, then asks once (default **No**) whether to also remove LyricLoom's data folders: settings and logs, work cache, kept vocals, models and the AssemblyAI key. Use `--purge` to remove that data without asking. The music library and the `.lrc` files next to your music are never deleted. Custom `models`, `vocals` or `work` locations from `settings.json`, and environment-provided locations, are listed for you to remove by hand.

The release binary targets the glibc of its build runner. On an older distribution, use the source install instead.

## Install the system packages

The tarball bundles Qt and its Python runtime, but it still uses the system GStreamer plugins for playback and the system audio libraries. Install this section even if you use the tarball, or at least the GStreamer and `libsndfile` rows.

```bash
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-dev \
  build-essential git cmake ninja-build pkg-config \
  libgl1 libegl1 libxkbcommon0 libxkbcommon-x11-0 \
  libxcb1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 \
  libgstreamer1.0-0 gstreamer1.0-tools gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly \
  gstreamer1.0-libav \
  ffmpeg libsndfile1
```

Why these groups:

| Group | Used for |
|---|---|
| `libgl1`, `libegl1`, `libxkbcommon*`, `libxcb-*` | Qt 6 / PySide6 platform plugin. Missing XCB libraries are the most common reason the app does not start. |
| `gstreamer1.0-*` | Qt Multimedia playback and the built-in karaoke player. Without the codec plugins, the app opens but there is no sound. |
| `ffmpeg`, `libsndfile1` | Audio decoding, vocal separation and format conversion. |
| `cmake`, `ninja-build`, `build-essential` | Building whisper.cpp. |
| `python3.11`, `python3.11-venv`, `python3.11-dev` | LyricLoom and its Python dependencies. |

For CUDA or Vulkan whisper.cpp builds, also install the matching toolchain:

```bash
# NVIDIA CUDA: install the NVIDIA driver and CUDA toolkit from your distribution or NVIDIA.
# Vulkan (optional):
sudo apt install -y libvulkan1 vulkan-tools glslc
```

## Get Python 3.11

Check what you have:

```bash
python3 --version
python3.11 --version
```

If `python3.11` is missing, you have two straightforward options.

### Option A: uv (works across distributions)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.11
uv python find 3.11
```

Then create the environment with `uv venv --python 3.11` as shown below. You do not need to activate the environment if you use `uv run`.

### Option B: distribution packages

On Ubuntu 22.04 and 23.10, add the deadsnakes PPA:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev
```

On distributions that already provide Python 3.11, install it with the normal package manager. Do not use Python 3.12 or newer for 2.1.1; the project intentionally pins `>=3.11,<3.12`.

## Install from source with a virtual environment

```bash
git clone https://github.com/nishizumi-maho/lyricloom.git
cd lyricloom

python3.11 -m venv .venv
. .venv/bin/activate

python -m pip install --upgrade pip wheel
# CPU-only wheels, matching the public builds. GPU users replace these later.
python -m pip install "torch==2.4.1" "torchaudio==2.4.1" \
  --index-url https://download.pytorch.org/whl/cpu
python -m pip install -e .
```

With `uv`:

```bash
git clone https://github.com/nishizumi-maho/lyricloom.git
cd lyricloom
uv venv --python 3.11
uv pip install "torch==2.4.1" "torchaudio==2.4.1" \
  --index-url https://download.pytorch.org/whl/cpu
uv pip install -e .
```

You can also run the repository's setup script, which does the same thing and adds the `dev` extra:

```bash
bash scripts/setup-dev.sh
```

The editable install exposes two commands inside the environment:

- `lyricloom` — engine and command line.
- `lyricloom-app` — desktop application.

The CPU-first install is intentional: the public builds use CPU wheels, and a Linux PyPI wheel can pull a large CUDA runtime even if you do not have an NVIDIA GPU. If you need a specific CUDA or ROCm build, install it **after** the project and keep torch and torchaudio versions matched. See [CUDA and ROCm PyTorch](#cuda-and-rocm-pytorch).

## Install with pipx

pipx keeps LyricLoom in its own environment and puts the commands on your `PATH`:

```bash
sudo apt install -y pipx
pipx ensurepath

git clone https://github.com/nishizumi-maho/lyricloom.git
cd lyricloom
pipx install --python python3.11 .
# Keep the public-build CPU wheels unless you are setting up a GPU:
pipx runpip lyricloom install --force-reinstall "torch==2.4.1" "torchaudio==2.4.1" \
  --index-url https://download.pytorch.org/whl/cpu
```

Open a new terminal after `pipx ensurepath`, then run:

```bash
lyricloom-app
```

To update a pipx install later:

```bash
cd lyricloom
git pull
pipx install --force --python python3.11 .
```

If you need to replace PyTorch inside the pipx environment with a CUDA/ROCm build:

```bash
pipx runpip lyricloom install --force-reinstall torch torchaudio \
  --index-url https://download.pytorch.org/whl/cpu
```

Use the index URL for your GPU instead of the CPU example. The pipx environment path is shown by `pipx list`.

## Run LyricLoom

From the release tarball:

```bash
lyricloom
```

From an activated virtual environment:

```bash
lyricloom-app
# or
python -m lyricloom
```

The first window asks you to choose a library with **Library…**. The default is `~/Music` if no library has been chosen. Lyrics are written next to the audio files.

A source or pipx install also provides the engine command line, which uses the same library setting:

```bash
lyricloom doctor
lyricloom models status
lyricloom process /path/to/song.flac
lyricloom process /path/to/library --force
```

`lyricloom process` only accepts paths inside the library chosen in the app. If you need a separate test profile, point `LYRICLOOM_DATA_DIR` at a different data folder, choose the library there, and run the command.

The release tarball's `lyricloom` launcher is the windowed app, not the full CLI. Use a source/pipx install when you need `doctor`, `models` or `process`.

## Add a desktop entry

The release tarball's `install.sh` creates the menu entry for you. This section is for source and pipx installs.

Create `~/.local/share/applications/lyricloom.desktop`:

```ini
[Desktop Entry]
Type=Application
Version=1.0
Name=LyricLoom
GenericName=Lyrics Synchronizer
Comment=Create word-by-word synced LRC lyrics
Exec=/home/YOUR_USER/.local/share/pipx/venvs/lyricloom/bin/lyricloom-app
TryExec=/home/YOUR_USER/.local/share/pipx/venvs/lyricloom/bin/lyricloom-app
Icon=audio-x-generic
Terminal=false
Categories=AudioVideo;Audio;Utility;
Keywords=lyrics;karaoke;lrc;alignment;subtitles;
StartupNotify=true
```

Replace `YOUR_USER` with your user name. For a source checkout, use the absolute path to the environment's launcher, for example:

```ini
Exec=/home/YOUR_USER/lyricloom/.venv/bin/lyricloom-app
TryExec=/home/YOUR_USER/lyricloom/.venv/bin/lyricloom-app
```

Then make it executable and refresh the menu:

```bash
chmod +x ~/.local/share/applications/lyricloom.desktop
update-desktop-database ~/.local/share/applications
```

The icon name `audio-x-generic` is a standard themed icon. LyricLoom does not ship its own icon in 2.1.1; if your theme does not provide that name, pick another installed icon or leave the `Icon=` line out.

## Download the models

The release tarball and the source/pipx app open the setup assistant on first start; its **Models** page offers the missing files and downloads them to `~/.local/share/lyricloom/models` by default. **Help > Models…** opens the full Models window later. The suggested download is about 5 GB:

| Model | Size |
|---|---:|
| Whisper large-v3 | 2.9 GB |
| Mel-Band RoFormer vocals | 0.9 GB |
| MMS_FA | 1.2 GB |
| LyricsAlignment-MTL | 66 MB |
| NLTK data | 22 MB |

A source or pipx install can also use the command line:

```bash
lyricloom models status
lyricloom models download all-defaults
```

The release tarball's `lyricloom` launcher is the GUI, so use the setup assistant or **Help > Models…** there.

See [docs/models.md](models.md) for paths, offline installation and licenses. The MMS_FA weights are non-commercial; read [THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md) before commercial use.

## Build whisper-cli

The release tarball already contains `whisper-cli` (a CPU build from the release runner). Build it yourself for a source checkout, or if you want a CUDA/Vulkan build.

LyricLoom calls a `whisper-cli` binary. It looks in:

1. The bundled `tools/bin` directory (source checkout or release bundle).
2. `~/.local/share/lyricloom/bin`.
3. Your `PATH`.

It does **not** use the Python `openai-whisper` package.

### CPU build

```bash
git clone --depth 1 --branch v1.9.5 https://github.com/ggml-org/whisper.cpp
cmake -S whisper.cpp -B whisper.cpp/build -DCMAKE_BUILD_TYPE=Release
cmake --build whisper.cpp/build -j --config Release

mkdir -p ~/.local/share/lyricloom/bin
cp whisper.cpp/build/bin/whisper-cli ~/.local/share/lyricloom/bin/
```

### CUDA build (NVIDIA)

Install the CUDA toolkit and driver first, then:

```bash
cmake -S whisper.cpp -B whisper.cpp/build-cuda \
  -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=1
cmake --build whisper.cpp/build-cuda -j --config Release
cp whisper.cpp/build-cuda/bin/whisper-cli ~/.local/share/lyricloom/bin/
```

### Vulkan build (AMD or other GPUs)

```bash
sudo apt install -y libvulkan1 vulkan-tools glslc
cmake -S whisper.cpp -B whisper.cpp/build-vulkan \
  -DCMAKE_BUILD_TYPE=Release -DGGML_VULKAN=1
cmake --build whisper.cpp/build-vulkan -j --config Release
cp whisper.cpp/build-vulkan/bin/whisper-cli ~/.local/share/lyricloom/bin/
```

### Verify

```bash
~/.local/share/lyricloom/bin/whisper-cli --help
lyricloom doctor
```

`lyricloom doctor` prints the path it found and whether the file exists. If whisper.cpp was built with shared libraries, install them or set `LD_LIBRARY_PATH` so `whisper-cli` can start outside the build tree.

### Use another whisper.cpp build

Put `whisper-cli` on `PATH` or in `~/.local/share/lyricloom/bin`, or set the `whisper_cli` setting (or `LYRICLOOM_WHISPER_CLI`) to its full path. The default model is `ggml-large-v3.bin` in the LyricLoom models folder; choose another catalog model with `lyricloom models use transcribe <id>`. See [docs/models.md](models.md).

## CUDA and ROCm PyTorch

LyricLoom uses PyTorch for vocal separation and MMS_FA alignment. whisper.cpp is separate and does not use PyTorch.

### NVIDIA CUDA

1. Install a supported NVIDIA driver (`nvidia-smi` must work).
2. Install a CUDA PyTorch build. Use the index URL that matches your driver and the torch version; for example:

```bash
python -m pip install --force-reinstall torch torchaudio \
  --index-url https://download.pytorch.org/whl/cu124
```

3. Verify:

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
lyricloom doctor
```

`cuda=True` in `lyricloom doctor` means PyTorch can see the GPU.

### AMD ROCm

1. Install a ROCm version supported by your distribution and GPU. Check AMD's ROCm compatibility matrix first.
2. Verify the GPU is visible:

```bash
rocminfo
rocm-smi
```

3. Install a ROCm PyTorch build from the index for your ROCm version, for example:

```bash
python -m pip install --force-reinstall torch torchaudio \
  --index-url https://download.pytorch.org/whl/rocm6.2
```

4. Verify:

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Some RDNA2 cards need an architecture override. For example, for `gfx1030`:

```bash
export HSA_OVERRIDE_GFX_VERSION=10.3.0
lyricloom-app
```

Use the value that matches your GPU (`rocminfo | grep gfx`). Do not set an override for a card that ROCm already recognizes unless the ROCm documentation says to.

### What runs on the GPU on Linux

| Stage | Device in 2.1.1 |
|---|---|
| Vocal separation (Mel-Band RoFormer) | CUDA or ROCm when PyTorch sees the GPU; `LYRICLOOM_SEPARATOR_DEVICE=cpu` forces CPU. |
| MMS_FA forced alignment | CUDA or ROCm when `LYRICLOOM_ALIGN_DEVICE=auto` (the default on Linux). |
| English singing model (MTL) | **CPU** in 2.1.1. The Linux path does not pass `cuda=True` to the MTL worker. |
| Whisper transcription | whisper.cpp, depending on how you built it (CPU, CUDA or Vulkan). |

If a GPU stage fails, LyricLoom can fall back to the CPU. Check the status bar in the app and the per-track log.

## Troubleshooting

### The app does not start: Qt platform plugin "xcb"

Install the XCB and OpenGL libraries listed above. To see the missing library:

```bash
QT_DEBUG_PLUGINS=1 lyricloom-app
```

On Wayland, try the X11 platform plugin:

```bash
QT_QPA_PLATFORM=xcb lyricloom-app
```

### The app opens but there is no sound

Qt Multimedia uses GStreamer. Install the base, good, bad, ugly and libav plugin packages, then check:

```bash
gst-inspect-1.0 playbin
gst-inspect-1.0 flacdec
```

If a plugin is missing, install the package that provides it. Test the same file in another player to separate a codec problem from a LyricLoom problem.

### `whisper-cli` not found

Check the search paths:

```bash
command -v whisper-cli
ls -l ~/.local/share/lyricloom/bin/whisper-cli
lyricloom doctor   # source or pipx install
```

If the binary starts but cannot find a shared library, run `ldd ~/.local/share/lyricloom/bin/whisper-cli` and install the missing package, or rebuild with static libraries.

### `ffmpeg` not found

```bash
sudo apt install ffmpeg
ffmpeg -version
```

`audio-separator` and some alignment paths expect ffmpeg on `PATH`. LyricLoom's Python package also bundles an ffmpeg through `imageio-ffmpeg`, but the worker's external calls still benefit from a system ffmpeg.

### CUDA/ROCm is installed but `torch.cuda.is_available()` is false

- Check the driver: `nvidia-smi` or `rocminfo`.
- Check that the installed torch build matches the driver/ROCm version.
- Make sure you are running the same Python environment that LyricLoom uses (`which python`, `python -c "import torch; print(torch.__file__)"`).
- For ROCm, check your user's groups (`video`, `render`) and the `HSA_OVERRIDE_GFX_VERSION` value.
- Reinstall torch and torchaudio together; mismatched versions are a common cause of import failures.

### Permission errors writing `.lrc`

The folder containing the audio must be writable by your user, not just the audio file. Check:

```bash
touch "/path/to/music/folder/.lyricloom-write-test" && rm "/path/to/music/folder/.lyricloom-write-test"
```

Flatpak/Snap sandboxes, read-only mounts and network shares can block writes. Use a local library folder or adjust the mount permissions.

### Desktop entry does not appear

```bash
desktop-file-validate ~/.local/share/applications/lyricloom.desktop
update-desktop-database ~/.local/share/applications
```

Make sure the `Exec=` path is absolute and points to an existing launcher.

### Where the logs are

Per-track logs:

```text
~/.local/share/lyricloom/work/<hash>/log.txt
```

`lyricloom doctor` prints the data folder in use. For the full troubleshooting guide, see [docs/troubleshooting.md](troubleshooting.md).
