# Contributing to LyricLoom and Starry Karaoke

Thanks for helping. This repository contains two products:

- **LyricLoom** — the Python 3.11 / PySide6 desktop app and its engine.
- **Starry Karaoke** — the C# MusicBee plugin in `musicbee/` (.NET Framework 4.8, built with the
  .NET 8 SDK).

Contributions of code, tests, documentation and bug reports are welcome for both. By contributing,
you agree that your contribution is licensed under the license of the product it belongs to: the
**GNU GPL v3 or later** for LyricLoom (see [LICENSE](LICENSE)) and **MIT** for the plugin (see
[musicbee/LICENSE](musicbee/LICENSE)). Do not contribute code, models, lyrics, audio or other
material that you cannot license under those terms.

Please be respectful in issues and pull requests. Harassment, personal attacks and publishing
someone's private data are not acceptable.

## Before you start

- Read [docs/architecture.md](docs/architecture.md) for the pipeline and cache model.
- Read [docs/lrc-format.md](docs/lrc-format.md) before changing anything that writes `.lrc` files.
- Read [musicbee/docs/design.md](musicbee/docs/design.md) before changing the plugin.
- Check existing issues and pull requests so we do not duplicate work.
- For a large feature, open an issue first and describe the approach. It is easier to agree on the
  design before the code exists.

## Repository layout

| Path | Product | Contents |
|---|---|---|
| `lyricloom/` | LyricLoom | Engine, CLI, workers and PySide6 GUI. |
| `tests/` | LyricLoom | Python test suite and fixtures. |
| `docs/` | Both | User, privacy, model, WSL and architecture documentation. |
| `packaging/`, `scripts/` | LyricLoom | PyInstaller, Inno Setup, Linux tarball and release scripts. |
| `musicbee/` | Starry Karaoke | C# plugin, recorder, tests, build script and plugin README. |
| `.github/workflows/` | Both | CI: Python on Windows/Linux and the plugin on Windows. |

## Development setup

### LyricLoom on Windows

Requirements: Python **3.11**, Git, PowerShell and optionally a GPU toolchain.

```powershell
git clone https://github.com/nishizumi-maho/lyricloom.git
cd lyricloom
.\scripts\setup-dev.ps1
```

The script creates `.venv`, installs CPU-only PyTorch, the project with the `dev` extra, checks
dependencies and exposes `imageio-ffmpeg`'s ffmpeg inside the environment.

Run the app:

```powershell
.\.venv\Scripts\python.exe -m lyricloom
```

Run the engine:

```powershell
.\.venv\Scripts\python.exe -m lyricloom doctor
.\.venv\Scripts\python.exe -m lyricloom process "D:\Music\Artist\Album"
```

### LyricLoom on Linux

Install the Qt/GStreamer/ffmpeg packages from
[docs/install-linux.md](docs/install-linux.md#install-the-system-packages), then:

```bash
git clone https://github.com/nishizumi-maho/lyricloom.git
cd lyricloom
bash scripts/setup-dev.sh
. .venv/bin/activate
```

### Starry Karaoke

Requirements: the **.NET 8 SDK**, Windows and MusicBee for manual testing. The build targets .NET
Framework 4.8, which is included in Windows 10 and 11.

```powershell
dotnet test musicbee\tests\StarryKaraoke.Tests -c Release -nologo
dotnet build musicbee\src\StarryKaraoke.Recorder\StarryKaraoke.Recorder.csproj -c Release -nologo
```

The complete plugin build (tests, plugin, recorder and release ZIP) is:

```powershell
.\musicbee\build.ps1
```

The ZIP is written to `musicbee\dist\StarryKaraoke-MusicBee-<version>.zip`.

### Models

The Python test suite does not need the large models by default. For end-to-end work:

```bash
lyricloom models download all-defaults
lyricloom doctor
```

Models, audio files, `.venv`, `.venv-mtl`, caches and `assemblyai.key` are ignored by Git. Do not
commit them. The plugin's build output, `musicbee/dist` and the installed binary folders are also
ignored.

## Tests

Run these before opening a pull request:

```powershell
# LyricLoom
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider

# Starry Karaoke
dotnet test musicbee\tests\StarryKaraoke.Tests -c Release -nologo
dotnet build musicbee\src\StarryKaraoke.Recorder\StarryKaraoke.Recorder.csproj -c Release -nologo
```

On Linux use `pytest -q -p no:cacheprovider`. The default Python run deselects tests marked `gpu`
(see `pyproject.toml`); `pytest -m gpu` needs real models, a GPU toolchain or the WSL distro and is
not expected to pass on a clean machine.

- Source-adapter tests use recorded fixtures under `tests/fixtures` and `tests/sources`; do not add
  tests that hit live lyrics sites.
- GUI tests must work with `QT_QPA_PLATFORM=offscreen` (CI sets it; set it yourself before running
  the suite).
- If you change the LRC format, update `tests/test_lrc.py`, `tests/test_write.py` and
  [docs/lrc-format.md](docs/lrc-format.md).
- If you change a stage's output, bump the relevant `STAGE_VERSIONS` entry; if the written `.lrc`
  changes, bump `ENGINE_VERSION` in `lyricloom/__init__.py`.
- If you change the plugin, add or update a test in `musicbee/tests/StarryKaraoke.Tests` and run both
  .NET commands above.

The project does not require 100% coverage, but new behavior should have a test where it is practical.

## Code style

### LyricLoom

- Python 3.11, 4-space indentation, 120-character lines (configured in `pyproject.toml`).
- Keep the engine free of Qt imports. The GUI may import the engine; the engine may not import the
  GUI.
- Heavy torch/audio-separator work belongs in a worker under `lyricloom/workers/`, not in `app/`.
- Keep user-facing text in English. The UI is English-only in 2.1.1.
- Prefer small functions with a clear data contract (`TrackMeta`, `Candidate`, `Transcript`, `Line`,
  `Segment`).
- Do not silently swallow errors that the user needs to see; log them with enough context to diagnose
  the track.
- Do not add telemetry, analytics, crash reporting or a hidden network call. Every network request
  must be one the user asked for or turned on, and must be listed in
  [docs/privacy.md](docs/privacy.md).

### Starry Karaoke

- C# with the existing file layout and naming; keep WPF/MusicBee calls on the UI thread where the
  code already does.
- Keep pure policy (auto-open, frame rate, scroll path, LRC parsing) free of WPF and MusicBee so it
  can be tested directly.
- User-facing strings live in `musicbee/src/StarryKaraoke/Strings.cs`; add the English text there.
- Never let the recorder overwrite its input, the playing audio, the settings or ffmpeg.
- The plugin must not add a hidden network request. Opening the LyricLoom page is an explicit user
  choice; see [docs/privacy.md](docs/privacy.md#the-starry-karaoke-plugin).

## Adding a lyric source

1. Add `lyricloom/lyrics/sources/<name>.py`:

   ```python
   from ...model import TrackMeta
   from .base import RawResult, check

   name = "example"

   def search(meta: TrackMeta, client):
       response = check(client.get("https://example.test/search", params={"q": f"{meta.title} {meta.artist}"}))
       ...
       return [RawResult(title, artist, duration_s, text, synced, url)]
   ```

2. Use `check()` so 401/403/429 become `SourceBlocked`. Do not try to bypass blocks, captchas or
   decoy pages.
3. Add the module to `SOURCES` in `lyricloom/lyrics/search.py`.
4. Add a source weight to `SOURCE_WEIGHT` in `lyricloom/lyrics/score.py` if it is official/editorial
   or user-submitted.
5. Add parser tests with saved HTML/JSON fixtures. Do not make the test suite depend on the live site.
6. Document any new host and data sent in [docs/privacy.md](docs/privacy.md).

If the site has no public API and blocks scripted requests, do not add an adapter that works around
it. A missing source is better than a fragile or abusive one.

## Changing alignment, transcription or models

- Preserve the worker protocol: JSON on stdin, a single marked JSON result line on stdout, stderr for
  diagnostics.
- A worker crash must become a per-track failure or a documented fallback, not a crash of the GUI.
- Keep the word skeleton and times honest. Do not invent words or times to make a line look aligned.
- Add a fixture-based test for the new behavior.
- Add new catalog entries to `lyricloom/models.py` with exact size and SHA-256, and document the
  stage, size, license and default in [docs/models.md](docs/models.md) and
  [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
- Downloads must use a `.part` file and verify the pinned size and checksum. Processing must never
  fetch a model on its own.

## Documentation

- User-facing docs are English in 2.1.1.
- Use relative links between docs and the README so they work on GitHub and in a local checkout.
- Do not add screenshot links until the image files actually exist in the repository.
- Do not include personal paths, machine names, API keys or copyrighted lyrics in examples.
- Keep Windows instructions friendly for non-technical users; put developer detail in the development
  docs.
- Keep [docs/musicbee.md](docs/musicbee.md) and [musicbee/README.md](musicbee/README.md) consistent.

## Pull requests

A good pull request:

- has a focused title and a short description of the problem and the fix;
- includes tests for behavior changes, or explains why a test is not practical;
- updates the relevant docs;
- does not mix unrelated refactors with a bug fix;
- does not commit generated files, models, audio, `.lrc` files from your library, or secrets.

Use imperative commit subjects such as `fix: keep the last word's closing tag` or `docs: explain WSL
model paths`. The repository history uses `feat:`, `fix:`, `docs:`, `test:` and `chore:` prefixes;
following that style is helpful but not mandatory.

Before opening the PR, run the Python and, if relevant, .NET commands above. If the change affects
packaging, release builds or GPU behavior, say what you tested and on which platform. If you could not
test something, say so explicitly.

## Reporting bugs

Use the bug template and choose the product: **LyricLoom app**, **Starry Karaoke plugin** or **both**.
Include:

- LyricLoom version (`lyricloom --version`) and/or plugin version.
- Windows or Linux version.
- Installer, portable, source or pipx; for the plugin, whether MusicBee is installed or portable.
- The **Help > Diagnostics…** text for the app, or the plugin's **Diagnostics** text. Redact personal
  paths if you prefer.
- The track's `log.txt` around the failure (redact personal paths).
- Whether the audio plays in another player.

Do not attach copyrighted audio or full lyrics unless you have the right to share them. See
[docs/troubleshooting.md](docs/troubleshooting.md).

## Security issues

Do **not** open a public issue for a vulnerability. Follow [SECURITY.md](SECURITY.md) and use GitHub's
private vulnerability reporting.

## License

LyricLoom is licensed under the GNU General Public License, version 3 or later. See [LICENSE](LICENSE).
Starry Karaoke is MIT-licensed; see [musicbee/LICENSE](musicbee/LICENSE). Third-party components and
model licenses are listed in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). In particular, the
default MMS_FA alignment weights are CC-BY-NC 4.0 (non-commercial); do not describe LyricLoom as
commercially usable without addressing that.
