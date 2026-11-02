# LyricLoom 2.0.0

LyricLoom turns official lyrics into word-by-word synchronized `.lrc` files by aligning them against isolated vocals. It is the first public release, formerly developed as *Lyrics Boca*.

## Highlights

- Word-level enhanced LRC with line and word timestamps.
- Six-stage pipeline: lyrics search, vocal separation, Whisper transcription, forced alignment, review, write.
- Built-in starry karaoke player — **no MusicBee required** — plus optional MusicBee + [Starry Karaoke](https://github.com/nishizumi-maho/MusicBee-StarryKaraoke) support.
- English singing-model alignment (LyricsAlignment-MTL) and multilingual MMS_FA alignment.
- Windows installer and portable ZIP; native Linux tarball; optional WSL 2 + ROCm path for AMD GPUs.
- Japanese dual-script output (Japanese and romaji), word editor, review flags, per-stage cache.
- No telemetry. Cloud transcription is opt-in.

## Downloads

- **Windows installer:** `LyricLoom-Setup-2.0.0.exe` (per-user, no administrator rights).
- **Windows portable:** `LyricLoom-2.0.0-win64.zip`.
- **Linux:** `LyricLoom-2.0.0-linux-x86_64.tar.gz`.
- `SHA256SUMS` for verification.

The installer does not bundle the neural models. On first use LyricLoom offers to download about 5.3 GB of models (Whisper large-v3, Mel-Band RoFormer, MMS_FA and the English singing model) into `%LOCALAPPDATA%\LyricLoom\models`. The Models dialog and `lyricloom models` manage them later.

## Requirements

Windows 10/11 x64. Linux users need Python 3.11 and Qt/GStreamer libraries; see the README and `docs/install-linux.md`. GPU acceleration is optional: CPU works everywhere; WSL/ROCm is documented for AMD on Windows.

## Notes

- The interface is English-only in 2.0.0.
- MMS_FA weights are CC-BY-NC 4.0 (non-commercial). See `THIRD-PARTY-NOTICES.md`.
- The app checks GitHub Releases for updates unless disabled in Settings. No library data is sent.

Full documentation: https://github.com/nishizumi-maho/lyricloom/tree/main/docs
