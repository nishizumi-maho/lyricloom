# Privacy

LyricLoom is a local desktop application. It has **no telemetry, no analytics, no crash reporting and
no account system**. It does not upload your audio unless you turn on the optional AssemblyAI
integration, keep an API key, and allow cloud transcription for the run.

This page lists every network connection the application can make, what is sent, when it happens, and
how to turn it off.

## Summary

| Question | Answer |
|---|---|
| Does LyricLoom collect usage data? | No. |
| Does it upload my music? | Not by default. Only the optional AssemblyAI path uploads the isolated vocal stem, and only when cloud transcription is enabled and allowed for that run. |
| Does it need an account? | No. |
| Does it phone home for updates? | Yes by default: one request to `api.github.com` about four seconds after start-up and then every 24 hours, carrying only LyricLoom's version. You can turn it off in Settings. **Help > Check for updates…** is a one-off request you start yourself. |
| Where is my data? | In `%LOCALAPPDATA%\LyricLoom` on Windows and `~/.local/share/lyricloom` on Linux, plus the `.lrc` files next to your music. |
| Can I use it offline? | Yes, once the models and `whisper-cli` are installed, with the caveats below. |

## Network connections

All application requests use **HTTPS**. Several features are optional; the exact switch is listed
with each one.

### Lyrics search

When you process a song, LyricLoom searches public lyrics providers. The request contains the song's
**artist and title** (and sometimes title variants with bracketed text removed, album/duration for
scoring, and a search query). It does not contain the audio, the file path, your name or your library
contents beyond that query.

| Provider | Host and request | What is sent | When |
|---|---|---|---|
| LRCLIB | `lrclib.net` (`/api/search`) | Track name and artist name | Every processed track |
| NetEase Cloud Music | `music.163.com` (`/api/cloudsearch/pc`, `/api/song/lyric/v1`) | Search query `title artist`; song IDs for lyric requests | Every processed track |
| QQ Music | `c.y.qq.com` (`/soso/fcgi-bin/client_search_cp`, `/lyric/fcgi-bin/fcg_query_lyric_new.fcg`) | Search query `title artist`; song MID for lyric requests | Every processed track |
| Uta-Net | `utaten.com` (`/search`, `/lyric/...`) | Title and artist name | Every processed track |
| Genius | `genius.com` (`/api/search/multi`, `/<song>-lyrics`) | Search query `title artist` | Every processed track |
| DuckDuckGo HTML | `html.duckduckgo.com` (`/html/`) | Search query `artist title` plus `歌詞` or `letra lyrics` | Fallback search |

Requests carry a browser-like User-Agent (and, for NetEase and QQ, the provider's usual Referer).
Each provider can still see your IP address, request time and the query, as with any website. Each
provider has its own privacy policy and terms.

The DuckDuckGo fallback accepts only HTTPS result URLs on exact allowlisted hosts (`genius.com` and
`utaten.com`, including their subdomains); lookalike hosts such as `evilgenius.com` and plain-HTTP
URLs are ignored. Redirects while fetching an allowed result page are followed only through hosts on
that allowlist, over HTTPS, checked at every hop.

LyricLoom respects sites that block scripted requests (HTTP 401, 403 or 429). It skips them instead
of trying to bypass the block.

**Turn it off:** there is no separate switch in 2.2.0, because finding lyrics is the purpose of the
lyrics stage. To avoid these requests entirely, do not process songs, or use an offline DNS/firewall
rule for the hosts above. Skipped providers do not stop a local transcription from succeeding.

### Model downloads

Large models are downloaded only when you ask for them: from **Help > Models…**, the setup assistant's
**Models** page, or the explicit `lyricloom models download ...` command. There is no always-on
background model downloader. Processing a song never downloads a model: if a stage's resolved model
is missing, the track fails with a message naming the file and the download command.

| Download | Host | What is requested | When |
|---|---|---|---|
| Whisper models | `huggingface.co` (a pinned commit URL) | The `ggml-*.bin` file with its exact size and SHA-256 pinned in the source. | Help > Models…, the setup assistant, or `lyricloom models download <id>` |
| LyricsAlignment-MTL checkpoint | `raw.githubusercontent.com` (a pinned commit) | The `checkpoint_MTL` file. | Help > Models…, or `lyricloom models download <id>` |
| Vocal separators | `github.com` release assets (`nomadkaraoke/python-audio-separator`, `model-configs`) | Separator weights and their YAML/data files, downloaded by LyricLoom. | Help > Models…, or `lyricloom models download <id>` |
| audio-separator registry data | `raw.githubusercontent.com` (`TRvlvr/application_data`, pinned commit) | `download_checks.json`, plus `vr_model_data.json` or `mdx_model_data.json` for those separator types. | With a separator or a custom registry model |
| MMS_FA | `dl.fbaipublicfiles.com` (torchaudio's model host) | `model.pt`, with a pinned size and SHA-256. | Help > Models…, or `lyricloom models download <id>` |
| NLTK corpora | `raw.githubusercontent.com` (a pinned commit) | The pinned `cmudict`, tagger, `punkt` and `punkt_tab` zips. | Help > Models…, or `lyricloom models download <id>` |
| whisper.cpp Windows backends | `github.com` (`ggml-org/whisper.cpp` v1.9.2 release assets) | The official BLAS (CPU) or cuBLAS (NVIDIA) Windows zip, with its exact size and SHA-256 pinned in the source. | Setup assistant > Acceleration > Faster transcription, only when you choose to install one |

Every model file is written to a `.part` file and checked against the pinned size and SHA-256 before
it is moved into place. NLTK data may also be read from an existing local `NLTK_DATA` directory; in
that case nothing is downloaded.

These requests reveal your IP address and the fact that you are downloading a particular model file.
They do not include your music or library.

**Turn it off:** download the models before processing, or block the hosts above; a missing model then
fails the stage instead of being fetched.

### Windows GPU runtime setup

The optional **GPU on Windows** setup downloads software only when you click **Set up and use** on
the setup assistant's **Acceleration** page:

- the `uv` package installer from `github.com` (`astral-sh/uv` release 0.13.8, with its exact size
  and SHA-256 pinned in the source);
- a standalone Python 3.11 that `uv` fetches from `github.com`
  (`astral-sh/python-build-standalone` release assets) and checks against its own checksum list;
- PyTorch, torchaudio and torchvision wheels from `download.pytorch.org` (the CUDA 12.4 or 12.8
  index) for the CUDA runtime, or from PyPI for the DirectML runtime;
- `audio-separator`, `g2p_en`, `nltk`, `torch-directml` and their dependencies from PyPI (`pypi.org`
  and `files.pythonhosted.org`).

LyricLoom itself is not downloaded: the runtime imports it from the installed app. Everything is
stored in `%LOCALAPPDATA%\LyricLoom\runtimes`. No audio, library path, settings file or key is sent
to any of those hosts; they see your IP address and which packages were requested. The GPU test at
the end of the setup runs on your computer and reports to no one.

### WSL environment setup

The optional **WSL environment setup** downloads packages only when you start it from the setup
assistant's **Acceleration** page:

- `apt` fetches `python3-venv` and `ffmpeg` from your distro's configured Ubuntu package archive;
- `pip` fetches PyTorch and torchaudio wheels from `download.pytorch.org` (the ROCm 6.2, CUDA 12.4 or
  CPU index) and `audio-separator`, `g2p_en`, `nltk` and their dependencies from PyPI (`pypi.org` and
  `files.pythonhosted.org`);
- the LyricLoom wheel itself comes from the installed app, not from the network.

No audio, library path, settings file or key is sent to any of those hosts.

### GitHub and updates

The automatic update check is **on by default**, but no automatic request is made before you have
finished the setup assistant, whose Privacy page shows the choice. After that, about four seconds
after the window opens and then every 24 hours while the app runs, LyricLoom sends one request to:

- `https://api.github.com/repos/nishizumi-maho/lyricloom/releases/latest`

The request contains a `User-Agent: LyricLoom/<version> (+https://github.com/nishizumi-maho/lyricloom)`
header and asks only for public release metadata. It does not contain your library, your machine name,
an identifier or any other personal data. The request itself necessarily reveals your IP address to
GitHub, as any web request does.

When a newer release exists, the `update_install` setting decides what happens:

- **`auto` (default):** on a packaged Windows build, LyricLoom downloads the installer in the
  background, verifies it and shows a notice. The update is installed silently when LyricLoom closes,
  or when you choose **Restart now**.
- **`ask`:** the notice appears first; nothing is downloaded until you choose **Install now**.
- **`notify`:** only the notice and the link to the release page; nothing is downloaded.

If you download an update, LyricLoom fetches the installer from this project's own GitHub release:

- `https://github.com/nishizumi-maho/lyricloom/releases/download/<tag>/<installer>`, which may redirect
  to GitHub's asset hosts `objects.githubusercontent.com`, `release-assets.githubusercontent.com` or
  `github-releases.githubusercontent.com`;
- the matching `.sha256` file (or `SHA256SUMS`) from the same release.

The updater verifies the SHA-256 before running anything and refuses to download or run an installer
when the checksum is missing or wrong, when the URL is not this project's release, or when a redirect
leaves GitHub's release asset hosts. A downloaded file that was not verified by the running app is
never executed, and files left in the temporary update folder by an earlier run are deleted on
start-up. The installer is not code-signed, so the SHA-256 from the release is the integrity check.

A silent update never closes MusicBee. When MusicBee is running, the installer is told not to close
applications and the optional Starry Karaoke plugin task is skipped; the next LyricLoom start explains
that the plugin was not updated and how to update it.

On Linux there is no installer. The notice links to the release page and, when the release publishes
one, to the Linux tarball. Nothing is downloaded or run automatically.

**Turn it off:** clear **Check GitHub Releases for updates at startup and every 24 hours** in
**Settings**, or save `check_updates` as `false` in `settings.json`. The manual
**Help > Check for updates…** action still works when you use it.

The Starry Karaoke MusicBee plugin is shipped from the same repository; it has no update check of its
own.

### Links you open yourself

Some buttons open a page in your default browser only after an explicit click:

- **What's new** in the update bar opens the GitHub release page and shows the release notes in the
  app;
- **Download for Linux** opens the release tarball asset;
- the setup assistant can open the WSL guide when the bundled script is unavailable;
- the plugin can open the LyricLoom download page after you answer **Yes** to its question.

Those are ordinary browser requests to GitHub (or the local documentation file) and are not made by
LyricLoom in the background.

### Optional AssemblyAI

AssemblyAI is **off by default**. Three things must all be true before anything is uploaded:

1. `assemblyai_enabled` is `true` (a saved setting, default `false`);
2. an API key is configured, either in `%LOCALAPPDATA%\LyricLoom\assemblyai.key`
   (`~/.local/share/lyricloom/assemblyai.key` on Linux) or in `ASSEMBLYAI_API_KEY`;
3. the run allows cloud use. `runner.process(..., allow_cloud=None)` uses the setting;
   `allow_cloud=False` never uploads, even when the setting is on. A stored key by itself never
   enables an upload. When **Ask before uploading each queue** is on (the default), a queue asks
   first.

When all three are true and the local transcription needs help, LyricLoom may use AssemblyAI for:

- Japanese songs: a second transcription is used to improve anchors and lyric choice;
- songs where Whisper's output looks hallucinated, repetitive or too sparse;
- songs where no lyric source produced an acceptable candidate;
- additional voting passes for difficult tracks.

When it uses AssemblyAI, LyricLoom uploads the **isolated vocal track** as a 16 kHz mono WAV, not the
full mix, to `api.assemblyai.com`:

- `POST /v2/upload` with the WAV;
- `POST /v2/transcript` with the upload URL, language code, model name and a context prompt containing
  the artist and title;
- repeated `GET /v2/transcript/<id>` polls until the transcript is ready.

The request carries your API key in its `Authorization` header. AssemblyAI returns a transcript with
word timings; LyricLoom stores that JSON in the track's work cache. A cached cloud transcript is
reused without a second upload. The track log and `TrackResult` record whether audio was actually
uploaded.

The main window shows **Cloud transcription: on** in the status bar while the setting is enabled. The
same choices are on the setup assistant's Privacy page and in **Settings > Privacy**.

Audio uploaded to AssemblyAI is subject to **AssemblyAI's terms and privacy policy**, not
LyricLoom's. LyricLoom cannot control how long AssemblyAI retains it.

The key is protected at rest:

- **Windows:** encrypted with Windows DPAPI (`CryptProtectData`) for the current user. It can only be
  decrypted by the same Windows account.
- **Linux/macOS:** the key file is created with mode `0600` and its parent data folder is restricted
  to the current user. A plain-text key file from an older version is migrated to the protected form
  on first read.

The key is never written to the per-track log, the app log or the diagnostics text, and errors that
would contain it are redacted before they are logged or shown.

**Turn it off:**

- set `assemblyai_enabled` to `false` (the default), or
- remove the key in the app (leave the field empty) or delete `assemblyai.key`, or unset
  `ASSEMBLYAI_API_KEY`, or
- pass `--no-cloud` to `lyricloom process` for that run, or choose **Process without cloud** when a
  queue asks.

There is no other audio upload path. Whisper, vocal separation, forced alignment and the singing
model all run locally (including inside WSL, which is still your computer).

## The Starry Karaoke plugin

The MusicBee plugin makes **no network request** of its own. It reads local `.lrc` files, launches the
local LyricLoom executable only when you choose **Make word-timed lyrics with LyricLoom**, and opens
the LyricLoom download page in your browser only after you answer **Yes**. It has no telemetry, no
update check and no account.

## Local data

Everything LyricLoom writes lives in the per-user data directory, except the `.lrc` files next to
your music.

### Windows

```text
%LOCALAPPDATA%\LyricLoom\
├── settings.json
├── assemblyai.key          (DPAPI-encrypted; only if you added a key)
├── scan-*.json             (library scan cache)
├── logs\
│   └── app.log             (rotating app/queue/updater log)
├── backends\               (optional whisper.cpp BLAS/cuBLAS builds)
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
├── logs/app.log
├── backends/
├── models/
├── vocals/
└── work/
    └── <hash>/
        └── ...
```

`LYRICLOOM_DATA_DIR` moves all of this. `LYRICLOOM_MODELS` moves only the models.

Update downloads are written to the system temporary folder (`%TEMP%\LyricLoom-update` on Windows,
the platform temporary folder elsewhere). Files there are deleted when LyricLoom starts; only a file
that the running app downloaded and verified itself can be launched.

### What is stored

| Data | Why | Sensitive? |
|---|---|---|
| `settings.json` | Library path, vocals/work paths, Japanese script, model choices, update-check and install-mode choices, skipped version, cloud choice and per-queue consent, setup completion, optional WSL settings. | Contains local folder paths. |
| `scan-*.json` | Cached artist/title/status per track, so startup is instant. | Contains your library metadata. |
| `work/<hash>/*.json` | Per-stage cache: lyric candidates, separation info, transcript, alignment. | Contains fetched lyrics and transcript text. |
| `work/<hash>/vocals.wav`, `vocals16k.wav` | Player and aligner input. | Audio from your songs. |
| `work/<hash>/log.txt` | Errors, source URL, device used, fallback reason, whether cloud transcription was used. The AssemblyAI key is redacted. | Contains the audio path and error details. |
| `vocals/<artist>/<album>/<song>.vocals.flac` and `.json` | Kept lossless vocal stem and its manifest, so redo does not re-separate. | Audio from your songs. |
| `logs/app.log` | Rotation log of the app, queue, setup and update activity. | Contains local paths and error details; never the API key or lyric text. |
| `assemblyai.key` | API key, if you added one. | **Secret.** DPAPI-encrypted on Windows; mode 0600 on Linux/macOS. |
| `assemblyai*.json` | Cloud transcript response. | Contains transcript text. |
| `models/` | Model weights and `.verified.json` sidecars. | Large, not personal. |
| `backends/` | Optional whisper.cpp builds and their downloads. | Not personal. |

The work directory key is a SHA-1 of the audio path, size and modification time. It is not a
cryptographic secret; it is only a cache key.

### Logs

Per-track logs are at `work/<hash>/log.txt`. They include the track path, status, lyric source URL,
confidence, device used, whether the isolated vocal was uploaded to AssemblyAI, and, on failure, a
traceback. They do not contain the audio itself and the AssemblyAI key is redacted.

The app log is at `logs/app.log`, rotates at about 1 MB with two older files, and records start-up,
library scans, queue state, setup/update activity and errors. It is local only.

There is no remote logging or crash reporting. `lyricloom doctor` prints paths and environment
details to the terminal; it does not send them anywhere and does not print the API key. **Help >
Diagnostics…** shows a copyable snapshot with versions, paths, model/GPU state and the last 200 app
log lines. It never reads the API key.

## Retention and deletion

- **Lyrics next to music** stay until you delete them. LyricLoom keeps `.original.lrc` and `.lrc.bak`
  files even when you uninstall the app.
- **Work cache** can be deleted at any time when the app is closed. It is recreated on the next run.
- **Kept vocals** can be deleted at any time. They are recreated by separating again.
- **Models and installed whisper.cpp builds** can be deleted at any time. See
  [docs/models.md](models.md#deleting-models).
- **AssemblyAI key** can be removed in the app or by deleting `assemblyai.key`.
- **Downloaded update installers** can be deleted at any time; they are also removed on the next
  LyricLoom start.
- **All LyricLoom data** can be removed by deleting `%LOCALAPPDATA%\LyricLoom` or
  `~/.local/share/lyricloom`.

The installers can delete LyricLoom's own data for you:

- **Windows:** the uninstaller asks once, with **No** as the default, whether to remove settings,
  logs, work cache, kept vocals, models, installed whisper.cpp builds and the AssemblyAI key. Custom
  `models`, `vocals` or `work` locations from `settings.json`, and environment-provided locations,
  are listed for you to remove by hand. Only what LyricLoom itself created is deleted; other files
  in the data folder are kept. It deletes nothing there when music files, the music library or one
  of those custom or environment-provided folders is inside it, or when it cannot read the folders
  saved in `settings.json`.
- **Linux:** `install.sh --uninstall` asks once (default No); `install.sh --purge` removes the data
  without asking.

Neither uninstaller deletes anything in your music library or the `.lrc` files next to your music.
The Windows uninstaller also leaves the MusicBee files shared with other plugins in place.

Before deleting, keep any `.lrc` files you want. They are the useful output.

## Children, tracking and advertising

LyricLoom has no advertising, no trackers, no social features and no user profiles. It is a local
tool for processing audio files. It is not directed at children.

## Changes

This page describes LyricLoom 2.2.0 and Starry Karaoke 1.3.1. If a later version adds a network
feature, it should be documented here and in the release notes. The short summary is in
[PRIVACY.md](../PRIVACY.md).

## Questions

For a privacy question that is not a security vulnerability, open a normal issue at
<https://github.com/nishizumi-maho/lyricloom/issues>. For a vulnerability, use the private process in
[SECURITY.md](../SECURITY.md).
