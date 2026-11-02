# Changelog

All notable changes to LyricLoom are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses semantic versioning for the application release.

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

[2.0.0]: https://github.com/nishizumi-maho/lyricloom/releases/tag/v2.0.0
