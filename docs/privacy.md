# Privacy

LyricLoom is a local desktop application. It has **no telemetry, no analytics, no crash reporting and no account system**. It does not upload your audio unless you explicitly configure the optional AssemblyAI integration and LyricLoom uses it.

This page lists every network connection the application can make, what is sent, what is stored locally, and how to remove it.

## Summary

| Question | Answer |
|---|---|
| Does LyricLoom collect usage data? | No. |
| Does it upload my music? | Not by default. Only the optional AssemblyAI path uploads the isolated vocal stem, and only when that path is enabled and used. |
| Does it need an account? | No. |
| Does it phone home for updates? | No automatic update check in 2.0.0. |
| Where is my data? | In `%LOCALAPPDATA%\LyricLoom` on Windows and `~/.local/share/lyricloom` on Linux, plus the `.lrc` files next to your music. |
| Can I use it offline? | Yes, once the models and `whisper-cli` are installed, with the caveats below. |

## Network connections

### Lyrics search

When you process a song, LyricLoom searches public lyrics providers. The request contains the song's **artist and title** (and sometimes a title variant with bracketed text removed). It does not contain the audio, the file path, your name or your library contents beyond that query.

The providers used in 2.0.0 are:

| Provider | Host | What is sent | Notes |
|---|---|---|---|
| LRCLIB | `lrclib.net` | Track name, artist name | Open lyrics database. |
| NetEase Cloud Music | `music.163.com` | Search query `title artist`; song IDs for lyric requests | Chinese lyrics service. |
| QQ Music | `c.y.qq.com`, `y.qq.com` | Search query `title artist`; song MID for lyric requests | Chinese lyrics service. |
| Uta-Net | `utaten.com` | Title and artist name | Japanese lyrics site. |
| Genius | `genius.com` | Search query `title artist` | English/other lyrics site. |
| DuckDuckGo HTML | `html.duckduckgo.com` | Search query `artist title` plus `歌詞` or `letra lyrics` | Used as a fallback to find Genius/Uta-Net pages. |

Requests are made over HTTPS with a browser-like User-Agent. The provider can still see your IP address, request time and the query, as with any website. Each provider has its own privacy policy and terms.

LyricLoom respects sites that block scripted requests (HTTP 401, 403 or 429). It skips them instead of trying to bypass the block.

### Model downloads

Large models are downloaded only when you ask for them: from **Help > Download models**, the first-run prompt, or the explicit `lyricloom models download ...` command. LyricLoom 2.0.0 checks GitHub Releases for updates in the background on startup unless you disable that in Settings; the check sends no library data and only fetches public release metadata. Processing a song never downloads a model: if a stage's resolved model is missing, the track fails with a message naming the file and the download command.

| Download | Host | What is requested |
|---|---|---|
| Whisper models | `huggingface.co` (a pinned commit URL) | Model file with its exact size and SHA-256 pinned in the source. |
| LyricsAlignment-MTL checkpoint | `raw.githubusercontent.com` (a pinned commit) | The checkpoint file. |
| Vocal separators | `github.com` release assets (audio-separator's registry) | Separator weights and their YAML/data files, downloaded by LyricLoom. |
| MMS_FA | `dl.fbaipublicfiles.com` (torchaudio's model host) | `model.pt`, with a pinned size and SHA-256. |
| NLTK corpora | `raw.githubusercontent.com` (a pinned commit) | The pinned `cmudict`, tagger, `punkt` and `punkt_tab` zips. |

Every file is written to a `.part` file and checked against the pinned size and SHA-256 before it is moved into place. NLTK data may also be read from an existing local `NLTK_DATA` directory; in that case nothing is downloaded.

These requests reveal your IP address and the fact that you are downloading a particular model file. They do not include your music or library.

`lyricloom doctor`, `lyricloom models list` and `lyricloom models verify` do not upload anything. `doctor` reads local paths and imports PyTorch.

### Optional AssemblyAI

AssemblyAI is **off unless you add an API key**. You can add it in the app with **AssemblyAI key…**, or set `ASSEMBLYAI_API_KEY`, or create `%LOCALAPPDATA%\LyricLoom\assemblyai.key` manually. The key is stored in plain text in that file if you use the app; it is not encrypted.

When the key is present, LyricLoom may use AssemblyAI for:

- Japanese songs: a second transcription is used to improve anchors and lyric choice.
- Songs where Whisper's output looks hallucinated, repetitive or too sparse.
- Songs where no lyric source produced an acceptable candidate.
- Additional voting passes for difficult tracks.

When it uses AssemblyAI, LyricLoom uploads the **isolated vocal track** as a 16 kHz mono WAV, not the full mix. The request also includes the language code, a context prompt containing the artist and title, and your API key. AssemblyAI returns a transcript with word timings; LyricLoom stores that JSON in the track's work cache.

Audio uploaded to AssemblyAI is subject to **AssemblyAI's terms and privacy policy**, not LyricLoom's. LyricLoom cannot control how long AssemblyAI retains it. Remove the key if you do not want any audio to leave your computer.

To disable cloud transcription:

- Remove the key in the app (leave the field empty), or delete `assemblyai.key`, or unset `ASSEMBLYAI_API_KEY`.
- For the command line, pass `--no-cloud` to `lyricloom process` for that run.

There is no other audio upload path. Whisper, vocal separation, forced alignment and the singing model all run locally (including inside WSL, which is still your computer).

### GitHub and updates

LyricLoom 2.0.0 checks GitHub Releases for updates on startup unless you disable the check in Settings; it fetches only public release metadata. It also downloads the MTL checkpoint from GitHub when you request it, and model files from Hugging Face when you ask. Visiting the Releases page or the plugin repository is a normal browser request.

The separate MusicBee Starry Karaoke plugin has its own behavior; see its repository.

## Local data

Everything LyricLoom writes lives in the per-user data directory, except the `.lrc` files next to your music.

### Windows

```text
%LOCALAPPDATA%\LyricLoom\
├── settings.json
├── assemblyai.key          (only if you added a key)
├── scan-*.json             (library scan cache)
├── models\
├── vocals\
└── work\
    └── <hash>\
        ├── log.txt
        ├── lyrics.json
        ├── separate.json
        ├── transcribe.json
        ├── vocals.wav
        ├── vocals16k.wav
        └── whisper*.json / assemblyai*.json
```

### Linux

```text
~/.local/share/lyricloom/     (or $XDG_DATA_HOME/lyricloom)
├── settings.json
├── assemblyai.key
├── scan-*.json
├── models/
├── vocals/
└── work/
    └── <hash>/
        └── ...
```

`LYRICLOOM_DATA_DIR` moves all of this. `LYRICLOOM_MODELS` moves only the models.

### What is stored

| Data | Why | Sensitive? |
|---|---|---|
| `settings.json` | Library path, vocals path, Japanese script, optional WSL settings. | Contains local folder paths. |
| `scan-*.json` | Cached artist/title/status per track, so startup is instant. | Contains your library metadata. |
| `work/<hash>/*.json` | Per-stage cache: lyric candidates, separation info, transcript, alignment. | Contains fetched lyrics and transcript text. |
| `work/<hash>/vocals.wav`, `vocals16k.wav` | Player and aligner input. | Audio from your songs. |
| `work/<hash>/log.txt` | Errors, source URL, device used, fallback reason. | Contains the audio path and error details. |
| `vocals/<artist>/<album>/<song>.vocals.flac` | Kept lossless vocal stem, so redo does not re-separate. | Audio from your songs. |
| `assemblyai.key` | API key, if you added one. | **Secret.** Plain text. |
| `assemblyai*.json` | Cloud transcript response. | Contains transcript text. |
| `models/` | Model weights. | Large, not personal. |

The work directory key is a SHA-1 of the audio path, size and modification time. It is not a cryptographic secret; it is only a cache key.

### Logs

Per-track logs are at `work/<hash>/log.txt`. They include the track path, status, lyric source URL, confidence, device used and, on failure, a traceback. They do not contain the audio itself.

There is no global rolling log in 2.0.0. `lyricloom doctor` prints the paths and environment details to the terminal; it does not send them anywhere.

## Retention and deletion

- **Lyrics next to music** stay until you delete them. LyricLoom keeps `.original.lrc` and `.lrc.bak` files even when you uninstall the app.
- **Work cache** can be deleted at any time when the app is closed. It is recreated on the next run.
- **Kept vocals** can be deleted at any time. They are recreated by separating again.
- **Models** can be deleted at any time. See [docs/models.md](models.md#deleting-models).
- **AssemblyAI key** can be removed in the app or by deleting `assemblyai.key`.
- **All LyricLoom data** can be removed by deleting `%LOCALAPPDATA%\LyricLoom` or `~/.local/share/lyricloom`.

Before deleting, keep any `.lrc` files you want. They are the useful output.

## Children, tracking and advertising

LyricLoom has no advertising, no trackers, no social features and no user profiles. It is a local tool for processing audio files. It is not directed at children.

## Changes

This page describes LyricLoom 2.0.0. If a later version adds a network feature, it should be documented here and in the release notes. The short summary is in [PRIVACY.md](../PRIVACY.md).

## Questions

For a privacy question that is not a security vulnerability, open a normal issue at <https://github.com/nishizumi-maho/lyricloom/issues>. For a vulnerability, use the private process in [SECURITY.md](../SECURITY.md).
