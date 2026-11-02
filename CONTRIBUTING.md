# Contributing to LyricLoom

Thanks for helping. LyricLoom is a small open-source desktop tool, and contributions of code, tests, documentation and bug reports are welcome.

By contributing, you agree that your contribution is licensed under the project's **GNU GPL v3 or later** license (see [LICENSE](LICENSE)). Do not contribute code, models, lyrics, audio or other material that you cannot license under those terms.

Please be respectful in issues and pull requests. Harassment, personal attacks and publishing someone's private data are not acceptable.

## Before you start

- Read [docs/architecture.md](docs/architecture.md) for the pipeline and cache model.
- Read [docs/lrc-format.md](docs/lrc-format.md) before changing anything that writes `.lrc` files.
- Check existing issues and pull requests so we do not duplicate work.
- For a large feature, open an issue first and describe the approach. It is easier to agree on the design before the code exists.

## Development setup

### Windows

Requirements: Python **3.11**, Git, and PowerShell. GPU work is optional.

```powershell
git clone https://github.com/nishizumi-maho/lyricloom.git
cd lyricloom
.\tools\setup_env.ps1
```

The script creates `.venv`, installs the project with the `dev` extra, checks dependencies, and exposes `imageio-ffmpeg`'s ffmpeg inside the environment.

Run the app:

```powershell
.\.venv\Scripts\python.exe -m lyricloom
```

Run the engine:

```powershell
.\.venv\Scripts\python.exe -m lyricloom doctor
.\.venv\Scripts\python.exe -m lyricloom process "D:\Music\Artist\Album"
```

### Linux

Install the Qt/GStreamer/ffmpeg packages from [docs/install-linux.md](docs/install-linux.md#install-the-system-packages), then:

```bash
git clone https://github.com/nishizumi-maho/lyricloom.git
cd lyricloom
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### Models

The test suite does not need the large models by default. For end-to-end work:

```bash
lyricloom models download all
lyricloom doctor
```

Models, audio files, `.venv`, `.venv-mtl`, caches and `assemblyai.key` are ignored by git. Do not commit them.

## Tests

```bash
pytest
pytest -m gpu
ruff check .
```

- The default `pytest` run deselects tests marked `gpu` (see `pyproject.toml`).
- `pytest -m gpu` needs real models, a GPU toolchain or the WSL distro. Do not expect it to pass on a clean machine.
- Source-adapter tests use recorded fixtures under `tests/fixtures` and `tests/sources`; do not add tests that hit live lyrics sites.
- If you change the LRC format, update `tests/test_lrc.py`, `tests/test_write.py` and [docs/lrc-format.md](docs/lrc-format.md).
- If you change a stage's output, bump the relevant `STAGE_VERSIONS` entry; if the written `.lrc` changes, bump `ENGINE_VERSION` in `lyricloom/__init__.py`.

Please run the tests that cover your change before opening a pull request. The project does not require 100% coverage, but new behavior should have a test where it is practical.

## Code style

- Python 3.11, 4-space indentation, 120-character lines (configured in `pyproject.toml`).
- Keep the engine free of Qt imports. The GUI may import the engine; the engine may not import the GUI.
- Heavy torch/audio-separator work belongs in a worker under `lyricloom/workers/`, not in `app/`.
- Keep user-facing text in English. The UI is English-only in 2.0.0.
- Prefer small functions with a clear data contract (`TrackMeta`, `Candidate`, `Transcript`, `Line`, `Segment`).
- Do not silently swallow errors that the user needs to see; log them with enough context to diagnose the track.
- Do not add telemetry, analytics, crash reporting or a hidden network call.

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

2. Use `check()` so 401/403/429 become `SourceBlocked`. Do not try to bypass blocks, captchas or decoy pages.
3. Add the module to `SOURCES` in `lyricloom/lyrics/search.py`.
4. Add a source weight to `SOURCE_WEIGHT` in `lyricloom/lyrics/score.py` if it is official/editorial or user-submitted.
5. Add parser tests with saved HTML/JSON fixtures. Do not make the test suite depend on the live site.
6. Document any new host and data sent in [docs/privacy.md](docs/privacy.md).

If the site has no public API and blocks scripted requests, do not add an adapter that works around it. A missing source is better than a fragile or abusive one.

## Changing alignment or transcription

- Preserve the worker protocol: JSON on stdin, a single marked JSON result line on stdout, stderr for diagnostics.
- A worker crash must become a per-track failure or a documented fallback, not a crash of the GUI.
- Keep the word skeleton and times honest. Do not invent words or times to make a line look aligned.
- Add a fixture-based test for the new behavior.
- Update [docs/architecture.md](docs/architecture.md) and the model/license pages if you add a model.

## Documentation

- All user-facing docs are English in 2.0.0.
- Use relative links between docs and the README so they work on GitHub and in a local checkout.
- Do not add screenshot links until the image files actually exist in the repository.
- Do not include personal paths, machine names, API keys or copyrighted lyrics in examples.
- Keep Windows instructions friendly for non-technical users; put developer detail in the development docs.

## Pull requests

A good pull request:

- has a focused title and a short description of the problem and the fix;
- includes tests for behavior changes, or explains why a test is not practical;
- updates the relevant docs;
- does not mix unrelated refactors with a bug fix;
- does not commit generated files, models, audio, `.lrc` files from your library, or secrets.

Use imperative commit subjects such as `fix: keep the last word's closing tag` or `docs: explain WSL model paths`. The repository history uses `feat:`, `fix:`, `docs:`, `test:` and `chore:` prefixes; following that style is helpful but not mandatory.

Before opening the PR:

```bash
pytest
ruff check .
```

If the change affects packaging, release builds or GPU behavior, say what you tested and on which platform. If you could not test something, say so explicitly.

## Reporting bugs

Include:

- LyricLoom version (`lyricloom --version`).
- Windows or Linux version.
- Installer, portable, source or pipx.
- The output of `lyricloom doctor` (redact personal paths).
- The track's `log.txt` around the failure (redact personal paths).
- Whether the audio plays in another player.

Do not attach copyrighted audio or full lyrics unless you have the right to share them. See [docs/troubleshooting.md](docs/troubleshooting.md).

## Security issues

Do **not** open a public issue for a vulnerability. Follow [SECURITY.md](SECURITY.md) and use GitHub's private vulnerability reporting.

## License

LyricLoom is licensed under the GNU General Public License, version 3 or later. See [LICENSE](LICENSE). Third-party components and model licenses are listed in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). In particular, the default MMS_FA alignment weights are CC-BY-NC 4.0 (non-commercial); do not describe LyricLoom as commercially usable without addressing that.
