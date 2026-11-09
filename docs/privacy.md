# Privacy

LyricLoom is a local desktop application. It has **no telemetry, no analytics, no crash reporting and no account system**. It does not upload your audio unless you turn on the optional AssemblyAI integration, keep an API key, and allow cloud transcription for the run.

This page lists every network connection the application can make, what is sent, when it happens, and how to turn it off.

## Summary

| Question | Answer |
|---|---|
| Does LyricLoom collect usage data? | No. |
| Does it upload my music? | Not by default. Only the optional AssemblyAI path uploads the isolated vocal stem, and only when cloud transcription is enabled and allowed for that run. |
| Does it need an account? | No. |
| Does it phone home for updates? | Not until you turn on the startup check. **Help > Check for updates** is a one-off request you start yourself. |
| Where is my data? | In `%LOCALAPPDATA%\LyricLoom` on Windows and `~/.local/share/lyricloom` on Linux, plus the `.lrc` files next to your music. |
| Can I use it offline? | Yes, once the models and `whisper-cli` are installed, with the caveats below. |

## Network connections

### Lyrics search

When you process a song, LyricLoom searches public lyrics providers. The request contains the song's **artist and title** (and sometimes title variants with bracketed text removed, album/duration for scoring, and a search query). It does not contain the audio, the file path, your name or your library contents beyond that query.

| Provider | Host and request | What is sent | When |
|---|---|---|---|
| LRCLIB | `lrclib.net` (`/api/search`) | Track name and artist name | Every processed track |
| NetEase Cloud Music | `music.163.com` (`/api/cloudsearch/pc`, `/api/song/lyric/v1`) | Search query `title artist`; song IDs for lyric requests | Every processed track |
| QQ Music | `c.y.qq.com` (`/soso/fcgi-bin/client_search_cp`, `/lyric/fcgi-bin/fcg_query_lyric_new.fcg`) | Search query `title artist`; song MID for lyric requests | Every processed track |
| Uta-Net | `utaten.com` (`/search`, `/lyric/...`) | Title and artist name | Every processed track |
| Genius | `genius.com` (`/api/search/multi`, `/<song>-lyrics`) | Search query `title artist` | Every processed track |
| DuckDuckGo HTML | `html.duckduckgo.com` (`/html/`) | Search query `artist title` plus `歌詞` or `letra lyrics` | Fallback search |

Requests are made over **HTTPS** with a browser-like User-Agent. The DuckDuckGo fallback accepts only HTTPS result URLs on exact allowlisted hosts (`genius.com` and `utaten.com`, including their subdomains); lookalike hosts such as `evilgenius.com` and plain-HTTP URLs are ignored. Each provider can still see your IP address, request time and the query, as with any website. Each provider has its own privacy policy and terms.

LyricLoom respects sites that block scripted requests (HTTP 401, 403 or 429). It skips them instead of trying to bypass the block.

**Turn it off:** there is no separate switch in 2.1.0, because finding lyrics is the purpose of the lyrics stage. To avoid these requests entirely, do not process songs, or use an offline DNS/firewall rule for the hosts above. Skipped providers do not stop a local transcription from succeeding.

### Model downloads

Models are downloaded from **Help > Download models**, the first-run prompt, or the explicit `lyricloom models download ...` command. A processing run can also start a missing artifact download from the stage that needs it: `audio-separator` for the separator, `torchaudio` for MMS_FA, and the singing-model worker for NLTK data. There is no always-on background downloader; the request happens only when that stage runs.

| Download | Host | What is requested | When |
|---|---|---|---|
| Whisper large-v3 | `huggingface.co` | The model file, and the published file metadata for its checksum | Help > Download models, `lyricloom models download whisper`, or the first stage that needs it |
| LyricsAlignment-MTL checkpoint | `github.com` | The checkpoint file from the upstream repository | Help > Download models, or `lyricloom models download mtl` |
| Mel-Band RoFormer | The model host used by `audio-separator` | Separator weights and associated data | Help > Download models, or the first separation that needs it |
| MMS_FA | PyTorch/torchaudio model host (`download.pytorch.org`) | The torchaudio MMS_FA checkpoint | Help > Download models, or the first alignment that needs it |
| NLTK corpora | The NLTK data index and GitHub-hosted package files | `cmudict`, `averaged_perceptron_tagger`, `punkt` | Help > Download models, or the first singing-model run that needs them |

These requests reveal your IP address and the fact that you are downloading a particular model file. They do not include your music or library.

**Turn it off:** download the models before processing, or block the hosts above; a missing model then fails the stage instead of being fetched. `lyricloom doctor` and `lyricloom models status` do not upload anything; `doctor` reads local paths and imports PyTorch.

### GitHub and updates

The automatic update check is **opt-in**. Until you save `check_updates` as `true` in Settings, LyricLoom makes no update request at startup.

When it is enabled, or when you choose **Help > Check for updates**, LyricLoom sends one request to:

- `https://api.github.com/repos/nishizumi-maho/lyricloom/releases/latest`

The request contains a `User-Agent: LyricLoom/<version>` header and asks only for public release metadata. It does not contain your library, your machine name or an identifier.

If you then choose to download an update, LyricLoom fetches the installer from this project's own GitHub release:

- `https://github.com/nishizumi-maho/lyricloom/releases/download/<tag>/<installer>`, which may redirect to GitHub's asset hosts `objects.githubusercontent.com`, `release-assets.githubusercontent.com` or `github-releases.githubusercontent.com`;
- the matching `.sha256` file (or `SHA256SUMS`) from the same release.

The updater verifies the SHA-256 before running anything and refuses to download or run an installer when the checksum is missing or wrong, when the URL is not this project's release, or when a redirect leaves GitHub's release asset hosts. A downloaded file that was not verified by the running app is never executed. The installer is not code-signed, so the SHA-256 from the release is the integrity check.

**Turn it off:** leave `check_updates` unset or set it to `false`. The manual **Help > Check for updates** action still works when you use it. Visiting the Releases page in a browser is an ordinary browser request.

The Starry Karaoke MusicBee plugin is shipped from the same repository; it has no update check of its own.

### Optional AssemblyAI

AssemblyAI is **off by default**. Three things must all be true before anything is uploaded:

1. `assemblyai_enabled` is `true` (a saved setting, default `false`);
2. an API key is configured, either in `%LOCALAPPDATA%\LyricLoom\assemblyai.key` (or `~/.local/share/lyricloom/assemblyai.key`) or in `ASSEMBLYAI_API_KEY`;
3. the run allows cloud use. `runner.process(..., allow_cloud=None)` uses the setting; `allow_cloud=False` never uploads, even when the setting is on. A stored key by itself never enables an upload.

When all three are true and the local transcription needs help, LyricLoom may use AssemblyAI for:

- Japanese songs: a second transcription is used to improve anchors and lyric choice.
- Songs where Whisper's output looks hallucinated, repetitive or too sparse.
- Songs where no lyric source produced an acceptable candidate.
- Additional voting passes for difficult tracks.

When it uses AssemblyAI, LyricLoom uploads the **isolated vocal track** as a 16 kHz mono WAV, not the full mix, to `api.assemblyai.com`:

- `POST /v2/upload` with the WAV;
- `POST /v2/transcript` with the upload URL, language code, model name and a context prompt containing the artist and title;
- repeated `GET /v2/transcript/<id>` polls until the transcript is ready.

The request carries your API key in its `Authorization` header. AssemblyAI returns a transcript with word timings; LyricLoom stores that JSON in the track's work cache. A cached cloud transcript is reused without a second upload.

Audio uploaded to AssemblyAI is subject to **AssemblyAI's terms and privacy policy**, not LyricLoom's. LyricLoom cannot control how long AssemblyAI retains it.

The key is protected at rest:

- **Windows:** encrypted with Windows DPAPI (`CryptProtectData`) for the current user. It can only be decrypted by the same Windows account.
- **Linux/macOS:** the key file is created with mode `0600` and its parent data folder is restricted to the current user. A plain-text key file from an older version is migrated to the protected form on first read.

The key is never written to the per-track log or the diagnostics text, and errors that would contain it are redacted before they are logged or shown.

**Turn it off:**

- Set `assemblyai_enabled` to `false` (the default), or
- remove the key in the app (leave the field empty) or delete `assemblyai.key`, or unset `ASSEMBLYAI_API_KEY`, or
- pass `--no-cloud` to `lyricloom process` for that run.

There is no other audio upload path. Whisper, vocal separation, forced alignment and the singing model all run locally (including inside WSL, which is still your computer).

## Local data

Everything LyricLoom writes lives in the per-user data directory, except the `.lrc` files next to your music.

### Windows

```text
%LOCALAPPDATA%\LyricLoom\
├── settings.json
├── assemblyai.key          (DPAPI-encrypted; only if you added a key)
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
├── assemblyai.key            (mode 0600)
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
| `settings.json` | Library path, vocals/work paths, Japanese script, update-check choice, cloud choice, optional WSL settings. | Contains local folder paths. |
| `scan-*.json` | Cached artist/title/status per track, so startup is instant. | Contains your library metadata. |
| `work/<hash>/*.json` | Per-stage cache: lyric candidates, separation info, transcript, alignment. | Contains fetched lyrics and transcript text. |
| `work/<hash>/vocals.wav`, `vocals16k.wav` | Player and aligner input. | Audio from your songs. |
| `work/<hash>/log.txt` | Errors, source URL, device used, fallback reason, whether cloud transcription was used. The AssemblyAI key is redacted. | Contains the audio path and error details. |
| `vocals/<artist>/<album>/<song>.vocals.flac` | Kept lossless vocal stem, so redo does not re-separate. | Audio from your songs. |
| `assemblyai.key` | API key, if you added one. | **Secret.** DPAPI-encrypted on Windows; mode 0600 on Linux/macOS. |
| `assemblyai*.json` | Cloud transcript response. | Contains transcript text. |
| `models/` | Model weights. | Large, not personal. |

The work directory key is a SHA-1 of the audio path, size and modification time. It is not a cryptographic secret; it is only a cache key.

### Logs

Per-track logs are at `work/<hash>/log.txt`. They include the track path, status, lyric source URL, confidence, device used, whether the isolated vocal was uploaded to AssemblyAI, and, on failure, a traceback. They do not contain the audio itself and the AssemblyAI key is redacted.

There is no global rolling log. `lyricloom doctor` prints the paths and environment details to the terminal; it does not send them anywhere and does not print the API key.

## Retention and deletion

- **Lyrics next to music** stay until you delete them. LyricLoom keeps `.original.lrc` and `.lrc.bak` files even when you uninstall the app.
- **Work cache** can be deleted at any time when the app is closed. It is recreated on the next run.
- **Kept vocals** can be deleted at any time. They are recreated by separating again.
- **Models** can be deleted at any time. See [docs/models.md](models.md#deleting-models).
- **AssemblyAI key** can be removed in the app or by deleting `assemblyai.key`.
- **All LyricLoom data** can be removed by deleting `%LOCALAPPDATA%\LyricLoom` or `~/.local/share/lyricloom`.

The installers can delete LyricLoom's own data for you:

- **Windows:** the uninstaller asks once, with **No** as the default, whether to remove settings, logs, work cache, kept vocals, models and the AssemblyAI key. Custom `models`, `vocals` or `work` locations from `settings.json`, and environment-provided locations, are listed for you to remove by hand.
- **Linux:** `install.sh --uninstall` asks once (default No); `install.sh --purge` removes the data without asking.

Neither uninstaller deletes anything in your music library or the `.lrc` files next to your music.

Before deleting, keep any `.lrc` files you want. They are the useful output.

## Children, tracking and advertising

LyricLoom has no advertising, no trackers, no social features and no user profiles. It is a local tool for processing audio files. It is not directed at children.

## Changes

This page describes LyricLoom 2.1.0. If a later version adds a network feature, it should be documented here and in the release notes. The short summary is in [PRIVACY.md](../PRIVACY.md).

## Questions

For a privacy question that is not a security vulnerability, open a normal issue at <https://github.com/nishizumi-maho/lyricloom/issues>. For a vulnerability, use the private process in [SECURITY.md](../SECURITY.md).
