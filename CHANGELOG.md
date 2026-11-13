# Changelog

All notable changes to LyricLoom and Starry Karaoke are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses semantic versioning for
the application release.

## [2.2.0] - 2026-11-13

LyricLoom 2.2.0 adds GPU processing on Windows without WSL and keeps the interface English on any
Windows language. Starry Karaoke stays at 1.3.1.

### Added

- **GPU on Windows.** The setup assistant's Acceleration page has a new **GPU on Windows** group.
  **Set up and use** downloads the `uv` installer (pinned by size and SHA-256), builds a Python
  3.11 environment in `%LOCALAPPDATA%\LyricLoom\runtimes` with a GPU build of PyTorch and
  audio-separator, and runs a real operation on the GPU. The runtime is selected only when that
  test passes and is used from the next song, with no restart.
  - **NVIDIA GPU (CUDA):** vocal separation, forced alignment and the English singing model run
    on the GPU. Only a current NVIDIA driver is needed. PyTorch 2.5.1 with CUDA 12.4 is used, or
    2.7.1 with CUDA 12.8 for RTX 50-series cards.
  - **DirectML (experimental):** runs vocal separation on AMD, Intel and NVIDIA GPUs. MDX-Net
    and VR models always use the GPU. RoFormer models, including the suggested one, use it
    with **Run RoFormer models on the GPU too**, which needs about 16 GB of video memory and is
    ticked by default only for such a card; otherwise they stay on the CPU. Both alignment
    models stay on the CPU.
- A failed, cancelled or interrupted setup changes no setting and can be resumed. A GPU stage
  that fails during a song falls back to the CPU and records the reason, including a runtime
  folder that was deleted by hand.
- **Remove…** deletes a runtime; the uninstaller deletes the runtimes and installed whisper.cpp
  builds with the rest of LyricLoom's data.
- Settings, the assistant's summary, **Help > Diagnostics…** and `lyricloom doctor` name the
  acceleration in use.

### Fixed

- **English interface on any Windows.** Windows error messages were shown in the system's
  display language; they are now written in English from the error code. Numbers and dates
  followed the Windows regional format and now use English formatting. WSL was reported as not
  installed on a non-English Windows with no distro, because the check read `wsl.exe`'s English
  sentence.
- **Lyrics web search** added the Portuguese word "letra" to the query for every song that was
  not Japanese. It now adds it only for Portuguese songs.
- The separator worker reports the device the model really used, so a DirectML run that
  audio-separator kept on the CPU is shown as CPU with the reason.
- **System check:** a graphics card with 4 GB or more of video memory was always shown as
  4 GB (a 32-bit Windows value); the real size is now read from the display driver.

### Changed

- Choosing **CPU only**, a WSL environment or the Windows runtime deselects the other two. The
  Settings group for WSL is now titled **GPU through WSL (advanced)**.

## [2.1.1] - 2026-11-11

LyricLoom 2.1.1 and Starry Karaoke 1.3.1 make the karaoke sweep follow the singing, time words more
precisely and make Whisper's transcription far more reliable.

### Fixed

- **Lyrics synced per line** (a time per line, none per word) are swept at the song's own pace in
  Starry Karaoke 1.3.1 and in the app: the pace is learned from the song's lines, each line is
  spread by sung syllables, and the sweep starts 150 ms after the line's time and ends before the
  next line. The plugin used a fixed 85 ms per letter from the line's time (racing ahead of slow
  lines), and the app stretched the sweep to the next line.
- **Word timing:** every CTC block is aligned with the neighbouring block on each side and keeps
  only its own lines, so a line's first word can no longer start on the previous line's last note.
  Japanese is aligned in one pass over the whole song instead of blocks cut at Whisper's coarse
  Japanese anchors.
- **Transcription:** Whisper runs with `-mc 0` (no text carried between 30 s windows, which could
  repeat one window through a whole song) and, for the official models, `-dtw <preset> -nfa`
  (token times from the attention alignment).

### Changed

- Engine version 10 and transcribe stage version 4: songs are re-transcribed and re-timed when they
  are processed again; the separated vocals are reused.

## [2.1.0] - 2026-11-09

LyricLoom 2.1.0 adds the first-run setup assistant, a model catalog with per-language and per-song
choices, verified imports and downloads, smooth lyric animation, and an update notice that can install
a verified release automatically. The Windows installer now bundles the Starry Karaoke plugin and can
put it into MusicBee.

### Added

- **Setup assistant** on first start and from **Help > Setup assistant…**: music folder, system
  check, acceleration, models, privacy and MusicBee, with every long job in a worker thread.
- **Model catalog and Models window** (**Help > Models…**): Whisper large-v3, large-v3-turbo, medium
  and small; three vocal separators; MMS_FA; the English singing model and its NLTK data. Exact
  sizes, SHA-256 values, licenses, ready/missing/corrupt/unverified states, and a row per stage.
- **Per-language and per-song model choices**, including **Process with other models…** and
  **Redo with current models**. The `.lrc` records the choice in `[#models:…]`, and the library can
  filter songs **Made with other models**.
- **Custom models** from a local file or an audio-separator registry name, with trust-on-first-use
  size and SHA-256, without copying or deleting the user's file.
- **Verified resumable downloads**: HTTPS only, `.part` files resumed with HTTP Range, retries,
  exact size and pinned SHA-256 before the atomic move, free-space checks, cancel and resume.
- **`lyricloom models` CLI**: `list`, `status`, `download`, `verify`, `repair`, `use` and `add`.
- **Update notice with automatic install**: a non-modal bar with release notes, *Restart now*,
  *Later* and *Skip this version*. **Settings > When an update is found** offers automatic install on
  close (default), ask first, or notify only. Downloads are SHA-256 verified and a silent update
  never closes MusicBee.
- **Smooth lyric animation** in the karaoke window and the main player: a timestamped playback
  clock, a gliding scroll path, eased line emphasis, a feathered word sweep and a slow tick while
  paused. **Settings > Smooth animation** offers Match display, Half refresh and Third refresh.
- **Single-instance desktop app** with `--process`, `--redo` and `--open`; a second start forwards its
  command line to the running window. The installer records `HKCU\Software\LyricLoom` so the
  MusicBee plugin can find the app.
- **Help > Diagnostics…** and a rotating app log with versions, paths, model/GPU state and a log
  tail; the AssemblyAI key is never included.
- **Queue controls** for stop after the current song, stop now and pause after the current song, with
  safe cancellation of the worker process tree.
- **Editor and player polish**: undo/redo for every edit, destructive-edit confirmation, **Accept
  line** / **Accept all**, F3 navigation between review lines, click-to-seek, kept-vocal playback and
  a light/dark Windows theme.
- **WSL acceleration setup**: find an existing GPU environment and verify its imports, or create
  `/opt/lyricloom/venv` with the bundled script for ROCm 6.2, CUDA 12.4 or CPU PyTorch.
- **Faster transcription builds** installed by the setup assistant: official whisper.cpp BLAS (CPU)
  and cuBLAS 12.4 (NVIDIA) Windows builds, pinned by size and SHA-256 and tested before use.
- **Starry Karaoke 1.3.0** bundled with the Windows installer and published as its own release ZIP.

### Changed

- The main window opens the setup assistant instead of the old first-run model dialog; **Help >
  Models** is the permanent model manager.
- **Update checks are on by default** (an explicit off in Settings stops them). A found update is now
  announced in the app and can be installed automatically; the installer is never run without its
  published checksum.
- **Cloud transcription is a separate consent switch** (`assemblyai_enabled`, off by default), apart
  from storing an AssemblyAI key. A queue can ask before uploading; the CLI has `--no-cloud`.
- Library, vocals and work folders are validated before saving and before a queue starts.
- Stage caches carry model fingerprints; changing a model redoes only the affected stages.
- Kept vocal stems carry a manifest of the source audio and separator model.
- `ENGINE_VERSION` is 8; lyric search, language handling, transcript checks and alignment changed.
- The MusicBee plugin now opens automatically by default for word-timed lyrics.
- The interface follows the Windows light/dark setting and the library table is a model/view table
  with in-place row updates, sortable columns and a debounced filter.

### Fixed

- **Stop, cancel and pause** no longer leave a queue wedged; a cancelled song shows as stopped and is
  retried later. Closing the window during a queue asks what to do.
- A failing track never stops the queue, and a corrupt scan cache or stage cache is rebuilt or
  discarded instead of breaking the run.
- **Honest lyric choice**: an empty or too-short phonetic reading no longer counts as a perfect
  match, and a missing artist tag no longer rejects a correct candidate.
- **Language handling**: Japanese means kana, an explicit tag wins, Han-only text is not Japanese,
  and unsupported scripts get line timing plus review instead of silent errors.
- An empty lyric search is never cached; **Search lyrics again** retries only the search, alignment
  and write.
- LRCLIB synced lines feed alignment; a failed singing-model alignment falls back to CTC with a
  warning; a hallucinated transcript is reported and marked for review.
- M4A and other container formats decode through ffmpeg; large files stream instead of loading at
  once; a WSL run that used the CPU is reported as `cpu`, not ROCm.
- The last word's end is trimmed against the isolated vocal, and very short words get a visible
  minimum sweep.
- Redo and script changes keep the other sidecars and a backup; Japanese script variants are
  rewritten from the kept variants without reprocessing.
- The updater keeps a verified download across *Later* and installs it only after the queue stops.
- The Windows and Linux uninstallers offer to remove only LyricLoom's own data, refuse to delete a
  folder that contains music, and list custom or environment-based folders for manual removal.

### Security

- The updater fails closed: HTTPS only, this project's GitHub release only, redirects only to
  GitHub's release asset hosts, and a required SHA-256 that is re-checked before launch. Published
  release assets cannot be overwritten.
- The AssemblyAI key is DPAPI-encrypted on Windows and mode 0600 elsewhere, a plain-text key is
  migrated, and the key is redacted from logs and errors.
- The single-instance channel is limited to the current user, validates JSON and size, and accepts
  only existing audio files; a test or second profile cannot talk to the user's window.
- Web-search result pages must be HTTPS on an exact allowlist at every redirect hop.
- Library scans prune symlinked and junction directories; the uninstaller does not follow reparse
  points.
- Plugin settings are validated and saved crash-safely; an unreadable file is kept as `.bad-<time>`.

### Known limitations

- The interface is English-only.
- The installer is unsigned, so SmartScreen can warn. Verify the published SHA-256.
- No official Vulkan whisper.cpp build is published; use the BLAS/cuBLAS builds or a local build.
- Native AMD acceleration on Windows is not supported; use WSL 2 + ROCm.
- On native Linux, the English singing model runs on the CPU.
- The default MMS_FA weights are CC-BY-NC 4.0 (non-commercial); see
  [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## [Starry Karaoke 1.3.0] - 2026-11-09

Starry Karaoke 1.3.0 is the MusicBee plugin released with LyricLoom 2.1.0. It is MIT-licensed and
ships from the same repository under `musicbee/`.

### Added

- **Auto-open** for word-timed lyrics (default), any synced lyrics, or off, with keep/hide/close
  behaviour for unsupported songs and an optional front-focus choice.
- A sidecar watcher that opens or refreshes the window when LyricLoom writes the `.lrc` for the
  playing song, even while the window is closed.
- **Make word-timed lyrics with LyricLoom** in the window and Tools menus, using
  `LyricLoom.exe --process` without a shell or focus change, plus a duplicate-request guard.
- **Smooth lyric motion** fed by timestamped MusicBee samples: a gliding scroll path, eased line
  growth and dimming, a gold word sweep and a minimum ramp for very short words.
- **Window frame rate** choices: Match display, Half refresh and Third refresh, always an integer
  divisor of the monitor refresh rate. Rendering stops while hidden, minimised or covered.
- **Diagnostics** with plugin/MusicBee/romaji/ffmpeg/LyricLoom versions and paths, Copy and Open log
  folder, never including lyrics.
- Safe offline **song video recording** with the starry scene, atomic output replacement and
  per-run temporary folders.
- More hotkey-bindable Tools commands for window, fullscreen, lyrics delay and loop.
- Real-DPI lyric layout, screenshots and fullscreen on a chosen monitor.

### Changed

- Auto-open now defaults to word-timed lyrics, including for settings upgraded from 1.2.
- The frame-rate setting is a divisor of the actual monitor refresh rate instead of a fixed 30/60/120
  cap; old settings migrate to the nearest divisor.
- The log is written next to the plugin DLL, with MusicBee's persistent storage folder as a fallback.
- A song is treated as Japanese only when it contains kana; Chinese songs no longer get Japanese
  readings.
- The plugin uses the `.japanese.lrc` or `.romaji.lrc` sidecar for the matching display mode.

### Fixed

- The recorder cannot overwrite the playing audio, the lyrics, the settings or ffmpeg, and a failed
  or cancelled encode leaves the previous video intact.
- Recorder temp folders are deleted on every exit; stale folders are swept on a later start.
- Stale or wrong MusicBee lyrics no longer replace better adjacent word timing.
- Settings that cannot be read are kept as `.bad-<time>` and reset instead of being silently
  overwritten.
- The window restores its monitor, position, size and fullscreen state, and party mode no longer
  steals focus when settings change.

### Security

- Plugin settings are validated before use and saved crash-safely.
- The uninstall hook removes only the plugin's own settings, offsets and log; shared romaji files are
  left for other plugins.
- The plugin makes no network request; only the local LyricLoom executable is started, and the
  download page is opened only after an explicit confirmation.
- The recorder runs ffmpeg in a kill-on-close job object and refuses unsafe output paths.

## [2.0.0] - 2026-11-02

### First public release

LyricLoom 2.0.0 is the first public release. The project was previously called **Lyrics Boca**; the new name is used throughout the package, the application and the documentation. Existing Lyrics Boca settings and `.lrc` files are still recognized.

### Added

- Word-by-word enhanced LRC output: per-line timestamps plus `<mm:ss.xx>` tags for every word or segment, with a final closing tag for the last segment.
- A six-stage pipeline: probe → lyrics search → vocal separation → transcription → alignment → write.
- Lyric search across LRCLIB, NetEase, QQ Music, Uta-Net, Genius and a DuckDuckGo web fallback, with metadata and transcript-based candidate scoring.
- Official lyric preservation as `<song>.original.lrc`; an existing `.lrc` is backed up before replacement.
- Vocal separation with Mel-Band RoFormer through `audio-separator`, including optional subtraction of a same-folder instrumental/off-vocal track.
- Local Whisper large-v3 transcription through whisper.cpp, with word timestamps, anchor detection, hallucination checks, multi-pass voting for difficult tracks and refrain consensus.
- English word alignment with LyricsAlignment-MTL, plus multilingual MMS_FA CTC alignment for other languages.
- Confidence scoring per line and per track, a `review` status for uncertain lines, and `[#review:...]` metadata in the `.lrc`.
- Japanese segmentation with MeCab/IPADic, inline furigana handling, and dual output: `<song>.japanese.lrc` and `<song>.romaji.lrc`, with the main `.lrc` script chosen in the app.
- Built-in PySide6 karaoke player with word highlight, vocals-only playback, play-line, seek, and a word editor with ±10/50 ms nudges, add/delete word, insert/delete line, merge, paste-and-realign and save.
- Library table with All/Review/Pending/Failed/Other/Done filters, search, process selected/pending, force, stop and redo-selected.
- Per-stage cache with versioned JSON files and a scan cache for fast library startup.
- Command line: `lyricloom process`, `lyricloom models`, `lyricloom doctor`, plus `lyricloom-app`.
- Model download and readiness checks for Whisper, the separator, MMS_FA, MTL and NLTK data.
- Windows installer and portable ZIP; native Linux source/pipx install; optional WSL 2 + ROCm path for AMD GPUs on Windows.
- Optional AssemblyAI cloud transcription, off unless a key is added, with `--no-cloud` for the CLI.
- Privacy documentation listing every network host and local data path.
- Full GNU GPL v3 text and third-party notices, including the non-commercial MMS_FA weights.

### Changed

- Renamed the project from **Lyrics Boca** to **LyricLoom**.
- Moved per-user data to `%LOCALAPPDATA%\LyricLoom` on Windows and `~/.local/share/lyricloom` on Linux.
- Kept vocal stems as lossless FLAC outside the music library instead of only inside the work cache.
- Improved last-word trimming against the isolated vocal envelope.
- Documented the enhanced LRC contract, the model layout and the WSL/ROCm setup from scratch.

### Known limitations

- The interface is **English-only** in 2.0.0.
- Native AMD GPU acceleration on Windows is not supported; use WSL 2 + ROCm.
- On native Linux, the English singing model (MTL) runs on the CPU in 2.0.0; separation and CTC alignment can use CUDA/ROCm.
- The default MMS_FA alignment weights are **CC-BY-NC 4.0 (non-commercial)**. See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
- The Mel-Band RoFormer checkpoint's license must be checked upstream before commercial use or redistribution.
- The in-app update check downloads and verifies the Windows installer from GitHub Releases; Linux users are sent to the release page for a new tarball.
- Lyrics search needs a network connection unless the lyrics are cached or pasted manually.
- Chinese lyrics are not a separate language mode; Han-only text can be ambiguous with Japanese.
- A line that cannot be word-aligned falls back to line-level timing; LyricLoom does not invent word times.

[2.2.0]: https://github.com/nishizumi-maho/lyricloom/releases/tag/v2.2.0
[2.1.1]: https://github.com/nishizumi-maho/lyricloom/releases/tag/v2.1.1
[2.1.0]: https://github.com/nishizumi-maho/lyricloom/releases/tag/v2.1.0
[Starry Karaoke 1.3.0]: https://github.com/nishizumi-maho/lyricloom/releases/tag/v2.1.0
[2.0.0]: https://github.com/nishizumi-maho/lyricloom/releases/tag/v2.0.0
