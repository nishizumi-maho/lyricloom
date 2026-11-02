# Privacy at a glance

LyricLoom has **no telemetry, no analytics, no crash reporting and no account system**. Audio is processed locally by Whisper, the vocal separator and the aligners.

- **Lyrics search** sends the artist and title (and sometimes album/duration) to public providers such as LRCLIB, NetEase, QQ Music, Uta-Net, Genius and DuckDuckGo.
- **Model downloads** contact GitHub, Hugging Face, PyTorch/torchaudio, NLTK and the audio-separator model registry. LyricLoom 2.0.0 does not check for updates automatically.
- **Optional AssemblyAI:** if you add an API key, LyricLoom may upload the isolated vocal stem for cloud transcription (for example Japanese songs or tracks where local transcription is unusable). Remove the key to disable it; the CLI also accepts `--no-cloud`.
- **No other audio upload.** There is no background upload and no hidden network call.
- **Local data** lives in `%LOCALAPPDATA%\LyricLoom` on Windows and `~/.local/share/lyricloom` on Linux. Lyrics are written next to your music.

The complete list of hosts, the data sent, local cache locations and deletion steps is in **[docs/privacy.md](docs/privacy.md)**.

For a security issue, see **[SECURITY.md](SECURITY.md)**. For ordinary questions, use the issue tracker: <https://github.com/nishizumi-maho/lyricloom/issues>.
