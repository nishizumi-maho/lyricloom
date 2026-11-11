# LyricLoom packaging and releases

This directory contains the public-release scaffolding for LyricLoom 2.1.1 and the Starry Karaoke
MusicBee plugin 1.3.1. It builds the Windows installer and portable zip, the Linux tarball, the
plugin zip, and the GitHub Actions workflows that attach those files to a release.

Nothing in this directory adds models or helper binaries to the repository.
`tools/bin/` and `models/` remain ignored; `dist/` and `build/` are generated
locally.

## Release artifacts

| Platform | File | Notes |
| --- | --- | --- |
| Windows | `LyricLoom-Setup-2.1.1.exe` | Inno Setup 6 per-user installer |
| Windows | `LyricLoom-Setup.exe` | stable copy used by the auto-updater |
| Windows | `LyricLoom-2.1.1-win64.zip` | portable PyInstaller one-folder bundle |
| Linux | `LyricLoom-2.1.1-linux-x86_64.tar.gz` | bundle + `.desktop` + install script |
| MusicBee | `StarryKaraoke-MusicBee-1.3.1.zip` | plugin, recorder, romaji DLLs and dictionary |
| All | `*.sha256` | one checksum file per artifact |

The release workflow also creates an aggregate `SHA256SUMS` asset and verifies every checksum before
publishing.

## Layout

```text
packaging/
  README.md                     this document
  pyinstaller/
    LyricLoom.spec              one Analysis, two executables, one COLLECT
    entry.py                    dispatches GUI vs worker by executable name
  wsl/
    setup-lyricloom-wsl.sh      creates an optional GPU environment inside WSL 2
  windows/
    LyricLoom.iss               Inno Setup 6 script
    version_info.txt            Windows version resource (keep in sync)
  linux/
    LyricLoom.desktop           desktop-entry template
    install.sh                  per-user Linux installer/uninstaller
musicbee/
  build.ps1                     plugin tests + plugin/recorder + release ZIP
  src/                          StarryKaraoke and StarryKaraoke.Recorder
  tests/StarryKaraoke.Tests/    .NET test project
.github/workflows/
  ci.yml                        Python tests on windows-latest + ubuntu-latest and plugin tests
  release.yml                   tag/dispatch builds and GitHub Release
scripts/
  setup-dev.ps1                 Windows Python 3.11 dev environment
  setup-dev.sh                  Linux Python 3.11 dev environment
  build-windows.ps1             whisper.cpp + wheel + plugin + PyInstaller + zip + installer
  build-linux.sh                whisper.cpp + PyInstaller + tarball
```

## Prerequisites

### Windows build host

* Windows 10/11 x64.
* Python 3.11 x64. The project intentionally requires `>=3.11,<3.12`.
* .NET 8 SDK for the Starry Karaoke plugin and recorder (they target .NET Framework 4.8).
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

They deliberately do not download models. Start the app and use the setup assistant's **Models** page
or **Help > Models…**, or use the CLI's `models` command.

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
2. Builds a wheel of the current LyricLoom into `build/wsl/` with
   `python -m pip wheel --no-deps . -w build\wsl`. The setup assistant uses
   this wheel to create a WSL GPU environment without a source tree or PyPI
   checkout of LyricLoom.
3. Builds the Starry Karaoke plugin and recorder by running `musicbee/build.ps1`, then copies the
   staged `musicbee/dist/StarryKaraoke-MusicBee-<plugin-version>` folder to `dist/MusicBeePlugin`.
   The installer uses that folder for its optional MusicBee task; the release workflow also uploads
   the plugin ZIP as a separate asset.
4. Runs PyInstaller with `--clean` into `dist/LyricLoom/`. The bundle contains
   `LyricLoom.exe`, `LyricLoomWorker.exe`, `_internal/tools/bin/whisper-cli.exe`
   and the ggml DLLs, `_internal/wsl/setup-lyricloom-wsl.sh` plus the wheel, and the bundled plugin
   under `_internal/musicbee/`.
5. Zips the whole one-folder bundle as
   `dist/LyricLoom-2.1.1-win64.zip`.
6. Compiles `packaging/windows/LyricLoom.iss` into
   `dist/LyricLoom-Setup-2.1.1.exe`, copies it to the stable name
   `dist/LyricLoom-Setup.exe`, and writes SHA256 files.

The Windows installer:

* installs per-user under `{localappdata}\Programs\LyricLoom` and does not
  request elevation;
* creates a Start Menu shortcut and an optional desktop shortcut (unchecked by
  default);
* offers the optional **Install the Starry Karaoke plugin for MusicBee** task when
  MusicBee is detected; the task is checked by default and installs into
  `%APPDATA%\MusicBee\Plugins`;
* keeps previous task choices on an upgrade and accepts `/SKIPPLUGIN=1` from a
  silent update, so MusicBee is never closed by the updater;
* writes `HKCU\Software\LyricLoom\InstallPath` and `Executable` for the plugin;
* registers an uninstaller in Apps & Features;
* does **not** create file associations;
* does **not** include models. They are downloaded at runtime to
  `%LOCALAPPDATA%\LyricLoom\models`.

The uninstaller removes the program folder, shortcuts, registry key and the plugin files it installed.
It asks once (default No) whether to delete LyricLoom's own data and lists custom or environment-based
locations for manual removal. It never deletes the music library or `.lrc` files, and it leaves the
MusicBee files shared with other plugins.

CI runners generally do not have the Vulkan SDK installed, so the release workflow uses the pinned
prebuilt CPU whisper.cpp v1.9.2 archive (`-SkipWhisper`). A maintainer with the Vulkan SDK can build a
Vulkan variant locally with the same script. No official Vulkan whisper.cpp asset is published.

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
dist/LyricLoom-2.1.1-linux-x86_64.tar.gz
dist/LyricLoom-2.1.1-linux-x86_64.tar.gz.sha256
```

The tarball contains:

```text
LyricLoom-2.1.1-linux-x86_64/
  LyricLoom/             PyInstaller one-folder bundle
  install.sh             per-user installer
  LyricLoom.desktop      desktop-entry template
```

### Installing the Linux tarball

```bash
tar -xzf LyricLoom-2.1.1-linux-x86_64.tar.gz
cd LyricLoom-2.1.1-linux-x86_64
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

Uninstalling removes the application, launcher and menu entry, then asks once
(default No) whether to also remove LyricLoom's data. `--purge` removes the data
without asking. Custom `models`, `vocals` or `work` locations from
`settings.json`, and environment-provided locations, are listed for manual
removal. The music library is never touched.

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
session. NLTK data is a pinned model entry, downloaded by the app; the worker
never fetches it on its own.

## Model data is not packaged

No model files are added to this repository or to any release artifact. The app
downloads them at runtime:

| Model | Approximate size |
| --- | --- |
| whisper.cpp large-v3 | ~2.9 GB |
| audio-separator Mel-Band RoFormer | ~0.9 GB |
| MMS forced alignment | ~1.2 GB |
| LyricsAlignment-MTL checkpoint | ~66 MB |
| NLTK data for the singing model | ~22 MB |

The suggested defaults total about 5.4 GB. Alternative Whisper sizes and separator models are in the
catalog; see [docs/models.md](../docs/models.md).

Default Windows location: `%LOCALAPPDATA%\LyricLoom\models`.
Default Linux location: `${XDG_DATA_HOME:-~/.local/share}/lyricloom/models`.
`LYRICLOOM_DATA_DIR` and `LYRICLOOM_MODELS` override these locations.

The setup assistant's **Models** page and the Models window handle the downloads. Every file is
verified against its pinned size and SHA-256 before use.

## Release process

The app version lives in three places that must be bumped together:

1. `lyricloom/__init__.py` (`VERSION`);
2. `pyproject.toml` (`project.version`, currently `2.1.1`);
3. `packaging/windows/version_info.txt` (file/product version strings).

The plugin version lives in `musicbee/src/StarryKaraoke/StarryKaraoke.csproj` (`<Version>`, currently
`1.3.1`). `tests/test_versions.py` fails when the app version sources disagree, and the release
workflow reads the plugin version from the project file.

`packaging/windows/LyricLoom.iss` has a `2.1.1` fallback only; the build script
passes the real version with `/DMyAppVersion=...`.

Then:

1. Run `python -m pytest -m "not gpu"` on Windows and Linux, and the .NET plugin tests.
2. Commit the version bump.
3. Create and push a tag that exactly matches the version:

   ```bash
   git tag v2.1.1
   git push origin v2.1.1
   ```

4. The **Release** workflow validates that the tag equals `lyricloom.VERSION`,
   builds the Windows installer/portable ZIP, the Linux tarball and the plugin ZIP, verifies the
   checksums and publishes a GitHub Release with:
   * `LyricLoom-Setup.exe` and `LyricLoom-Setup-2.1.1.exe`;
   * `LyricLoom-2.1.1-win64.zip`;
   * `LyricLoom-2.1.1-linux-x86_64.tar.gz`;
   * `StarryKaraoke-MusicBee-1.3.1.zip`;
   * per-file `.sha256` files and `SHA256SUMS`.
5. Manual runs are also possible from **Actions -> Release -> Run workflow**.
   A manual run uses the current `lyricloom.VERSION` and creates or updates the
   matching `v<version>` release.

### Auto-update contract

The updater fetches the latest release metadata from GitHub Releases and
prefers the stable asset name:

```text
LyricLoom-Setup.exe
LyricLoom-Setup.exe.sha256
```

The versioned installer is uploaded too for users who want to pin a release.
The updater fails closed: it accepts only an HTTPS asset from this repository's
own GitHub release (redirects only to GitHub's release asset hosts), requires the
published SHA-256 (the asset digest, a matching `.sha256` file, or `SHA256SUMS`
from the same release), verifies it, and refuses to run anything when the
checksum is missing or wrong. The release workflow publishes with
`overwrite_files: false`, so an existing release's assets cannot be replaced.
The updater compares the release version with `lyricloom.VERSION` before
offering an update. The installer is per-user and can run without elevation.

## CI

`.github/workflows/ci.yml` runs on pushes to `main`/`master`, pull requests and
manual dispatch:

* Python 3.11 on `windows-latest` and `ubuntu-latest`;
* pip caching keyed by `pyproject.toml`;
* CPU-only torch/torchaudio from the PyTorch CPU index;
* Linux Qt/X11, sound and ffmpeg runtime packages;
* `pytest -m "not gpu"` with `QT_QPA_PLATFORM=offscreen`;
* a separate Windows job runs the Starry Karaoke tests and builds the recorder.

`.github/workflows/release.yml` runs on tags matching `v*` and on manual
dispatch. It builds the Windows installer/portable ZIP, the Linux tarball and the plugin ZIP, validates
the tag against `lyricloom.VERSION`, verifies every uploaded checksum, and publishes with
`softprops/action-gh-release`.

## Validation

The release workflow is the authoritative full build. It runs the Python and .NET tests, builds every
artifact on GitHub-hosted runners and verifies the checksums before publishing. A local full build
needs a Windows Visual Studio/Vulkan toolchain, Inno Setup and several GB of downloads; use the
workflow or run `scripts/build-windows.ps1` on a prepared machine.

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
