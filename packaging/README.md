# LyricLoom packaging and releases

This directory contains the public-release scaffolding for LyricLoom 2.0.0. It
builds the Windows installer and portable zip, the Linux tarball, and the
GitHub Actions workflows that attach those files to a release.

Nothing in this directory adds models or helper binaries to the repository.
`tools/bin/` and `models/` remain ignored; `dist/` and `build/` are generated
locally.

## Release artifacts

| Platform | File | Notes |
| --- | --- | --- |
| Windows | `LyricLoom-Setup-2.0.0.exe` | Inno Setup 6 per-user installer |
| Windows | `LyricLoom-Setup.exe` | stable copy used by the auto-updater |
| Windows | `LyricLoom-2.0.0-win64.zip` | portable PyInstaller one-folder bundle |
| Linux | `LyricLoom-2.0.0-linux-x86_64.tar.gz` | bundle + `.desktop` + install script |
| All | `*.sha256` | one checksum file per artifact |

The release workflow also creates an aggregate `SHA256SUMS` asset.

## Layout

```text
packaging/
  README.md                     this document
  pyinstaller/
    LyricLoom.spec              one Analysis, two executables, one COLLECT
    entry.py                    dispatches GUI vs worker by executable name
  windows/
    LyricLoom.iss               Inno Setup 6 script
    version_info.txt            Windows version resource (keep in sync)
  linux/
    LyricLoom.desktop           desktop-entry template
    install.sh                  per-user Linux installer/uninstaller
.github/workflows/
  ci.yml                        tests on windows-latest + ubuntu-latest
  release.yml                   tag/dispatch builds and GitHub Release
scripts/
  setup-dev.ps1                 Windows Python 3.11 dev environment
  setup-dev.sh                  Linux Python 3.11 dev environment
  build-windows.ps1             whisper.cpp + PyInstaller + zip + installer
  build-linux.sh                whisper.cpp + PyInstaller + tarball
```

## Prerequisites

### Windows build host

* Windows 10/11 x64.
* Python 3.11 x64. The project intentionally requires `>=3.11,<3.12`.
* Visual Studio 2022 Build Tools with the **Desktop development with C++**
  workload. The script uses the `Visual Studio 17 2022` CMake generator, so a
  normal Developer Command Prompt is not required.
* Inno Setup 6 (`ISCC.exe`). The build script searches `PATH`,
  `%ProgramFiles(x86)%\Inno Setup 6`, `%ProgramFiles%\Inno Setup 6` and
  `%LOCALAPPDATA%\Programs\Inno Setup 6`.
* Optional: Vulkan SDK. When `VULKAN_SDK` points at an SDK, or an SDK is found
  under the standard `VulkanSDK` directories, whisper.cpp is built with
  `GGML_VULKAN=ON`; otherwise the script builds the CPU variant. Use `-CpuOnly`
  to force CPU or `-Vulkan` to require Vulkan.
* Optional: 7-Zip. It makes the portable zip much faster; otherwise the script
  falls back to `Compress-Archive`.
* About 15 GB of free disk space for the PyInstaller work directory, the
  one-folder bundle and the archives.

### Linux build host

* Python 3.11 and a C++ toolchain.
* `cmake`, `ninja`, `git`, `tar`, `sha256sum`.
* `patchelf` and `binutils` for PyInstaller's ELF handling.
* Optional: a Vulkan SDK (`VULKAN_SDK` and `glslc`). Without it whisper.cpp is
  built for CPU.
* Runtime libraries for the GUI: a normal desktop with Qt/X11 or Wayland
  support, `libsndfile`, and the usual OpenGL/EGL libraries. `imageio-ffmpeg`
  supplies a static ffmpeg; a system ffmpeg is optional.

## Development environment

From the repository root:

```powershell
# Windows
pwsh -File scripts/setup-dev.ps1
```

```bash
# Linux
bash scripts/setup-dev.sh
```

Both scripts:

1. create `.venv` with Python 3.11;
2. install CPU-only `torch==2.4.1` and `torchaudio==2.4.1`;
3. install the project editable with the `dev` extras (pytest, pytest-qt,
   sounddevice, PyInstaller, ruff);
4. run `pip check`;
5. expose `imageio-ffmpeg`'s static ffmpeg in the venv when practical.

They deliberately do not download models. Start the app and use the first-run
model dialog, or use the CLI's `models` command.

## Building on Windows

From the repository root:

```powershell
pwsh -File scripts/build-windows.ps1
```

Useful switches:

| Switch | Effect |
| --- | --- |
| `-Vulkan` | require a Vulkan SDK and fail if it is absent |
| `-CpuOnly` | ignore an installed Vulkan SDK and build whisper.cpp for CPU |
| `-ForceWhisper` | rebuild whisper.cpp even when `tools/bin/whisper-cli.exe` exists |
| `-SkipWhisper` | use the existing `tools/bin` helper and do not build it |
| `-SkipInstaller` | build the portable bundle/zip only |

What the script does:

1. Builds whisper.cpp **v1.9.5** from source into `tools/src/whisper.cpp`
   (ignored by git) with CMake and the Visual Studio 2022 generator.
   `BUILD_SHARED_LIBS=ON` produces `whisper-cli.exe` plus the `ggml*.dll` /
   `whisper.dll` files, which are copied to `tools/bin`.
2. Runs PyInstaller with `--clean` into `dist/LyricLoom/`. The bundle contains
   `LyricLoom.exe`, `LyricLoomWorker.exe`, `_internal/tools/bin/whisper-cli.exe`
   and the ggml DLLs.
3. Zips the whole one-folder bundle as
   `dist/LyricLoom-2.0.0-win64.zip`.
4. Compiles `packaging/windows/LyricLoom.iss` into
   `dist/LyricLoom-Setup-2.0.0.exe`, copies it to the stable name
   `dist/LyricLoom-Setup.exe`, and writes SHA256 files.

The Windows installer:

* installs per-user under `{localappdata}\Programs\LyricLoom` and does not
  request elevation;
* creates a Start Menu shortcut and an optional desktop shortcut (unchecked by
  default);
* registers an uninstaller in Apps & Features;
* does **not** create file associations;
* does **not** include models. They are downloaded at runtime to
  `%LOCALAPPDATA%\LyricLoom\models`.

CI runners generally do not have the Vulkan SDK installed, so release builds
from GitHub Actions use the CPU whisper.cpp variant. A maintainer with the
Vulkan SDK can produce a Vulkan build locally with the same script; both
variants satisfy the app's whisper.cpp contract.

## Building on Linux

From the repository root:

```bash
bash scripts/build-linux.sh
```

The script builds whisper.cpp v1.9.5 when `tools/bin/whisper-cli` is absent.
Linux uses a static whisper.cpp build (no `.so` files to relocate) and the
native `whisper-cli` name, without `.exe`. Set
`LYRICLOOM_WHISPER_VULKAN=1` or `0` to override automatic Vulkan detection.
The script reuses an existing `tools/bin/whisper-cli`; delete that file to force
a rebuild (for example after installing the Vulkan SDK). `tools/src/` and
`tools/bin/` are ignored by git. On Windows, use `-ForceWhisper` for the same
purpose.

Outputs:

```text
dist/LyricLoom/
dist/LyricLoom-2.0.0-linux-x86_64.tar.gz
dist/LyricLoom-2.0.0-linux-x86_64.tar.gz.sha256
```

The tarball contains:

```text
LyricLoom-2.0.0-linux-x86_64/
  LyricLoom/             PyInstaller one-folder bundle
  install.sh             per-user installer
  LyricLoom.desktop      desktop-entry template
```

### Installing the Linux tarball

```bash
tar -xzf LyricLoom-2.0.0-linux-x86_64.tar.gz
cd LyricLoom-2.0.0-linux-x86_64
./install.sh
```

By default this installs to `~/.local/opt/LyricLoom`, creates the launcher
`~/.local/bin/lyricloom`, and adds
`~/.local/share/applications/lyricloom.desktop` with an absolute `Exec` path.
Override the prefix with `PREFIX=/some/prefix ./install.sh`. No sudo is needed.

To uninstall:

```bash
~/.local/opt/LyricLoom/install.sh --uninstall
```

Uninstalling removes the application, launcher and menu entry. Settings, logs,
cached vocals and downloaded models under the LyricLoom data directory are
intentionally preserved.

### Source install on Linux

A source install is supported for development and for distributions that
prefer a system Python:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install "torch==2.4.1" "torchaudio==2.4.1" \
  --index-url https://download.pytorch.org/whl/cpu
python -m pip install .
lyricloom-app
```

For a source install, the app looks for `whisper-cli` in
`<repo>/tools/bin/`, then on `PATH`. Build it with `scripts/build-linux.sh`
(or copy a compatible binary into `tools/bin/`). A system ffmpeg is optional
because `imageio-ffmpeg` is bundled; the GUI needs a working Qt/OpenGL desktop
session. The MTL worker downloads its small NLTK corpora on first use.

## Model data is not packaged

No model files are added to this repository or to any release artifact. The app
downloads them at runtime:

| Model | Approximate size |
| --- | --- |
| whisper.cpp large-v3 | ~3.1 GB |
| audio-separator Mel-Band RoFormer | ~0.9 GB |
| MMS forced alignment | ~1.2 GB |
| LyricsAlignment-MTL checkpoint | ~66 MB |

Default Windows location: `%LOCALAPPDATA%\LyricLoom\models`.
Default Linux location: `${XDG_DATA_HOME:-~/.local/share}/lyricloom/models`.
`LYRICLOOM_DATA_DIR` and `LYRICLOOM_MODELS` override these locations.

The first-run model dialog handles the large downloads. The application also
downloads `cmudict`, `averaged_perceptron_tagger` and `punkt` for `g2p_en` when
the MTL path is used for the first time.

## Release process

The app version lives in three places that must be bumped together:

1. `lyricloom/__init__.py` (`VERSION`);
2. `pyproject.toml` (`project.version`, currently `2.0.0`);
3. `packaging/windows/version_info.txt` (file/product version strings).

`packaging/windows/LyricLoom.iss` has a `2.0.0` fallback only; the build script
passes the real version with `/DMyAppVersion=...`.

Then:

1. Run `python -m pytest -m "not gpu"` on Windows and Linux.
2. Commit the version bump.
3. Create and push a tag that exactly matches the version:

   ```bash
   git tag v2.0.0
   git push origin v2.0.0
   ```

4. The **Release** workflow validates that the tag equals `lyricloom.VERSION`,
   builds on `windows-latest` and `ubuntu-22.04`, verifies the checksums and
   publishes a GitHub Release with:
   * `LyricLoom-Setup.exe` and `LyricLoom-Setup-2.0.0.exe`;
   * `LyricLoom-2.0.0-win64.zip`;
   * `LyricLoom-2.0.0-linux-x86_64.tar.gz`;
   * per-file `.sha256` files and `SHA256SUMS`.
5. Manual runs are also possible from **Actions -> Release -> Run workflow**.
   A manual run uses the current `lyricloom.VERSION` and creates or updates the
   matching `v<version>` release.

### Auto-update contract

The updater should fetch the latest release metadata from GitHub Releases and
prefer the stable asset name:

```text
LyricLoom-Setup.exe
LyricLoom-Setup.exe.sha256
```

The versioned installer is uploaded too for users who want to pin a release.
The updater must verify the SHA256 before running the installer and compare the
release version with `lyricloom.VERSION` before offering an update. The
installer is per-user and can run without elevation.

## CI

`.github/workflows/ci.yml` runs on pushes to `main`/`master`, pull requests and
manual dispatch:

* Python 3.11 on `windows-latest` and `ubuntu-latest`;
* pip caching keyed by `pyproject.toml`;
* CPU-only torch/torchaudio from the PyTorch CPU index;
* Linux Qt/X11, sound and ffmpeg runtime packages;
* `pytest -m "not gpu"` with `QT_QPA_PLATFORM=offscreen`.

`.github/workflows/release.yml` runs on tags matching `v*` and on manual
dispatch. It builds both platforms, validates the tag against
`lyricloom.VERSION`, verifies every uploaded checksum, and publishes with
`softprops/action-gh-release`.

## Validation performed while adding this scaffolding

The files were checked with Python compilation and YAML parsing. A full
installer build was not run in this workspace because it needs a Windows
Visual Studio/Vulkan toolchain, Inno Setup, Inno's compiler and several GB of
downloads. The workflows run those steps on GitHub-hosted runners.

## Known assumptions and limitations

* **No icon asset is checked in.** If `packaging/windows/LyricLoom.ico` exists,
  both the executables and Inno Setup use it automatically. Without it, the
  executables use the bootloader icon and the Linux menu entry uses the
  standard `audio-x-generic` icon. Add an `.ico`/`.png` when branding assets
  are available.
* **No code signing.** Windows SmartScreen and SmartScreen-like warnings are
  expected until an Authenticode certificate is configured. Linux packages are
  unsigned tarballs.
* **x86_64 only.** The Inno script is x64-only and the PyInstaller builds use
  the host architecture. ARM64 is not covered.
* **No file association**, as required. The desktop file deliberately has no
  `MimeType` entry.
* **Models and NLTK corpora are not bundled**, so the first run needs network
  access (or a pre-populated model directory).
* **Vulkan is optional and environment-dependent.** GitHub's Windows runner
  does not normally provide the Vulkan SDK, so release CI uses CPU whisper.cpp.
  Linux release CI uses the static CPU build; users who need Vulkan can rebuild
  locally with the SDK present.
* **Linux compatibility is tied to the build runner.** Release CI uses
  `ubuntu-22.04` to target an older glibc than `ubuntu-latest` would. Users on
  older distributions should use the source-install path.
* **Worker naming is fixed by the frozen lookup.** On Windows the GUI expects
  a sibling `LyricLoomWorker.exe`. On Linux the code falls back to
  `LyricLoom --worker <name>`; both executables are built from the same
  Analysis so that fallback carries the worker modules.
