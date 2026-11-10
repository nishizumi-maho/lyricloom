# LyricLoom 2.1.0

This release ships **LyricLoom 2.1.0** and **Starry Karaoke 1.3.0** for MusicBee.

LyricLoom turns official lyrics into word-by-word synchronized `.lrc` files by aligning them against
isolated vocals. The app includes a library, a word editor, a compact player and a full-screen karaoke
window; the optional MusicBee plugin displays the same files in a starry karaoke window.

## Highlights

- **Setup assistant** on first start: music folder, system check, acceleration, models, privacy and
  MusicBee, page by page.
- **Model catalog and Models window**: Whisper large-v3 / turbo / medium / small, three vocal
  separators, MMS_FA, the English singing model and its NLTK data, with exact sizes, licenses,
  verified downloads, verify/repair, per-language and per-song choices and custom models.
- **Smooth lyric animation** in the app and the plugin, with frame-rate choices that are exact
  integer divisors of the monitor refresh rate (Match display, Half refresh, Third refresh).
- **Update notice with automatic install**: checks are on by default; choose automatic install on
  close, ask first, or notify only. Every installer is SHA-256 verified and a silent update never
  closes MusicBee.
- **Starry Karaoke 1.3.0** is bundled with the Windows installer and also published as its own ZIP:
  auto-open for word-timed lyrics, a LyricLoom integration command, smooth motion, diagnostics, safe
  offline video recording, party mode, per-song delay and more.
- Engine correctness, queue safety, language handling and model integrity fixes throughout.

## Downloads

| Asset | What it is |
|---|---|
| `LyricLoom-Setup-2.1.0.exe` | Windows installer, per-user, no administrator rights |
| `LyricLoom-Setup.exe` | Stable copy of the latest installer, used by the in-app updater |
| `LyricLoom-2.1.0-win64.zip` | Portable Windows build; extract and run |
| `LyricLoom-2.1.0-linux-x86_64.tar.gz` | Linux bundle with a per-user `install.sh` |
| `StarryKaraoke-MusicBee-1.3.0.zip` | MusicBee plugin, recorder, romaji DLLs and dictionary |
| `SHA256SUMS` and per-file `*.sha256` | Checksums for every asset |

The Windows installer includes the app, its worker, `whisper-cli` and the plugin files. It does not
include the large neural models. The setup assistant offers the suggested models (about 5 GB) on
first start; **Help > Models…** manages them later.

## Upgrade notes

- **Settings, library choice, models, caches and kept vocal stems are kept.** A stage cache written by
  2.0 is reused and upgraded with a model fingerprint when the stage still uses the catalog defaults;
  a kept vocal stem without a manifest is reused when it is newer than the audio and the separator is
  still the default.
- **The plugin's auto-open is on by default** for word-timed lyrics, also when its settings come from
  1.2. Choose *Off* or *When it has any synced lyrics* under **Preferences > Plugins > Starry Karaoke
  > Configure**.
- **Update checks are on by default** and send only LyricLoom's version to `api.github.com`. Clear
  **Check GitHub Releases for updates at startup and every 24 hours** in **Settings > Privacy** to
  stop them; **Help > Check for updates…** still works manually. **When an update is found** defaults
  to automatic install on close; choose *Ask before installing* or *Only notify me* if you prefer.
- **Cloud transcription is now a separate switch.** A stored AssemblyAI key no longer enables an
  upload by itself. Three things must be true: `assemblyai_enabled` is on, a key is set, and the run
  allows cloud use. **Ask before uploading each queue** is on by default; the CLI has `--no-cloud`.
- **The Windows installer offers an optional MusicBee task** when MusicBee is detected, checked by
  default. It replaces the plugin's own files, replaces the shared `RomajiCore.dll`/`LibNMeCab.dll`
  only when the bundled version is newer, and adds the `RomajiLyrics\IpaDic` dictionary only when it
  is missing. The uninstaller leaves those shared files and the plugin settings alone.
- **Engine 8 may reprocess some songs.** This is expected when the engine or a chosen model changes;
  the previous `.lrc` is backed up first. Songs already written by engine 8 are skipped unless you
  use **Force**.
- **WSL users:** workers now prefer the model copies inside the distro (`wsl_models_dir`,
  `wsl_torch_home`, `wsl_mtl_checkpoint`) when their size matches, and fall back to `/mnt`.

## Known limitations

- The installer is **not code-signed**, so Windows SmartScreen can warn. Verify the published SHA-256
  before running it.
- No official **Vulkan whisper.cpp** build is published. The setup assistant installs BLAS (faster
  CPU) or cuBLAS 12.4 (NVIDIA); a compatible local Vulkan build can be selected with `whisper_cli` or
  `LYRICLOOM_WHISPER_CLI`.
- Native AMD GPU acceleration on Windows is not supported; use WSL 2 + ROCm.
- On native Linux, the English singing model (MTL) runs on the CPU.
- The default MMS_FA alignment weights are **CC-BY-NC 4.0 (non-commercial)**. See
  [`THIRD-PARTY-NOTICES.md`](https://github.com/nishizumi-maho/lyricloom/blob/v2.1.0/THIRD-PARTY-NOTICES.md) before commercial use.
- The interface is English-only.

## Verify the download

The release publishes a `.sha256` file for every asset and one aggregate `SHA256SUMS`. On Windows:

```powershell
Get-FileHash .\LyricLoom-Setup-2.1.0.exe -Algorithm SHA256
```

On Linux:

```bash
sha256sum -c LyricLoom-Setup-2.1.0.exe.sha256
sha256sum -c SHA256SUMS
```

A mismatch means the download is corrupt or not the file you think it is. Delete it and download it
again from this release. Because the installer is unsigned, the checksum is the integrity check.

Full documentation is in the repository's `docs/` folder, starting with
[`README.md`](https://github.com/nishizumi-maho/lyricloom/blob/v2.1.0/README.md) and [`install-windows.md`](https://github.com/nishizumi-maho/lyricloom/blob/v2.1.0/docs/install-windows.md).
