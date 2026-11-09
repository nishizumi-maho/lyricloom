# Privacy at a glance

LyricLoom has **no telemetry, no analytics, no crash reporting and no account system**. Audio is processed locally by Whisper, the vocal separator and the aligners.

- **Lyrics search** sends the artist and title (and sometimes album/duration) to public providers such as LRCLIB, NetEase, QQ Music, Uta-Net, Genius and DuckDuckGo. All requests use HTTPS.
- **Model downloads** contact GitHub, Hugging Face, PyTorch/torchaudio, NLTK and the audio-separator model registry only when you ask for a model. Processing never downloads one: a missing model fails that track with a download command. **Update checks are off until you turn them on**; a manual **Help > Check for updates** still works.
- **Optional AssemblyAI:** cloud transcription is off by default. It runs only when you turn on `assemblyai_enabled`, keep a key, and allow cloud use for the run. It uploads the isolated vocal stem, never the full mix. On Windows the key is encrypted with DPAPI for your user; on Linux/macOS the key file is mode 0600. The key is never written to logs.
- **No other audio upload.** There is no background upload and no hidden network call.
- **Local data** lives in `%LOCALAPPDATA%\LyricLoom` on Windows and `~/.local/share/lyricloom` on Linux. Lyrics are written next to your music.

The complete list of hosts, the data sent, when it is sent, how to turn it off, local cache locations and deletion steps is in **[docs/privacy.md](docs/privacy.md)**.

For a security issue, see **[SECURITY.md](SECURITY.md)**. For ordinary questions, use the issue tracker: <https://github.com/nishizumi-maho/lyricloom/issues>.
