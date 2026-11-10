# Install LyricLoom on Windows

LyricLoom 2.1.0 runs on 64-bit Windows 10 and Windows 11. The normal installer includes the
application, the worker, `whisper-cli` and the optional Starry Karaoke MusicBee plugin; you do not
need Python, CUDA or a separate Whisper installation. The large models are not included: the setup assistant offers
them on first start and **Help > Models…** downloads them at any time; processing never downloads
a model.

There are two ways to run the app:

- **Installer:** `LyricLoom-Setup-2.1.0.exe` from the
  [Releases page](https://github.com/nishizumi-maho/lyricloom/releases). Recommended for most people.
- **Portable ZIP:** `LyricLoom-2.1.0-win64.zip`. Extract and run, without an installer. Good for a
  USB stick or a folder you control.

Both use the same per-user data folder for settings, models, caches and logs. See
[Where settings and caches live](#where-settings-and-caches-live).

## Before you start

- 64-bit Windows 10 or Windows 11.
- At least **10 GB free** for the app, the models and the working cache. A large library or many
  kept vocal stems needs more.
- 8 GB of RAM or more is recommended.
- Your music folder should be writable, because LyricLoom writes the `.lrc` next to each audio file.

LyricLoom reads these audio formats: `.flac`, `.mp3`, `.m4a`, `.ogg`, `.opus`, `.wav`. Other
formats are ignored by the library scanner. Convert them first if needed.

The interface is **English-only** in 2.1.0.

## Install with the setup program

1. Open the [Releases page](https://github.com/nishizumi-maho/lyricloom/releases).
2. Download `LyricLoom-Setup-2.1.0.exe`. Do not use a third-party download site.
3. Run the setup file.
4. Follow the wizard. It installs for the current user under
   `%LOCALAPPDATA%\Programs\LyricLoom`, does not request administrator rights and does not create
   file associations. The desktop shortcut is optional and unchecked by default.
5. If MusicBee is detected, the optional **Install the Starry Karaoke plugin for MusicBee** task is
   shown and checked (Setup keeps your earlier choice when you reinstall or update). Clear it if you do not want the plugin. Setup asks you to close MusicBee if it
   has the plugin files open; it does not restart MusicBee for you.
6. Start **LyricLoom** from the Start menu or the desktop shortcut.

The installer records its location in the current user's registry so the MusicBee plugin can find
the app:

```text
HKEY_CURRENT_USER\Software\LyricLoom
    InstallPath   C:\Users\<user>\AppData\Local\Programs\LyricLoom
    Executable    C:\Users\<user>\AppData\Local\Programs\LyricLoom\LyricLoom.exe
```

### If SmartScreen appears

A new open-source application may not have an established SmartScreen reputation yet, and this
installer is not code-signed. If Windows shows **"Windows protected your PC"**:

1. Click **More info**.
2. Check that the file name and the publisher text match the release you downloaded.
3. Click **Run anyway**.

Only do this for a file downloaded from the official Releases page. If you want to verify the
download, compare its SHA-256 checksum with the value on the release page:

```powershell
Get-FileHash .\LyricLoom-Setup-*.exe -Algorithm SHA256
```

The release publishes a per-file `.sha256` file and an aggregate `SHA256SUMS`. If the checksums do
not match, delete the file and download it again. Do not disable SmartScreen or your antivirus
permanently to work around a blocked installer.

## Install the portable ZIP

1. Download `LyricLoom-2.1.0-win64.zip` from the
   [Releases page](https://github.com/nishizumi-maho/lyricloom/releases).
2. Extract it to a folder you can write to, for example `D:\Apps\LyricLoom`. Do not run it from
   inside the ZIP preview window.
3. Run `LyricLoom.exe` in that folder.
4. Optional: create a shortcut to the executable.

The portable build does not need an installer, but by default it still keeps settings, models and
caches in `%LOCALAPPDATA%\LyricLoom`, not in the extracted folder. That means you can replace the
program files with a newer release without losing your settings.

To keep the data beside the portable app instead, set `LYRICLOOM_DATA_DIR` before launching. For
example, from PowerShell in the app folder:

```powershell
$env:LYRICLOOM_DATA_DIR = "$PWD\LyricLoomData"
.\LyricLoom.exe
```

To make that permanent for shortcuts, create a small `.cmd` launcher in the same folder:

```bat
@echo off
set LYRICLOOM_DATA_DIR=%~dp0LyricLoomData
start "" "%~dp0LyricLoom.exe"
```

Use the launcher every time. If you move the folder, move `LyricLoomData` with it. Lyrics are still
written next to the audio files, not into this data folder.

The portable ZIP does not install the MusicBee plugin. Install it from the setup assistant's
**MusicBee** page if your portable build includes the plugin files, or from the release ZIP as
described in [docs/musicbee.md](musicbee.md).

## The setup assistant page by page

The first start opens **LyricLoom setup assistant**. It is also available later from
**Help > Setup assistant…**. Nothing on the assistant pages is a commitment: you can change every
choice in **Settings**, **Help > Models…** or the assistant later.

### Welcome

A short explanation of what LyricLoom does, the approximate model download size, and the privacy
summary: music stays on the computer unless cloud transcription is enabled. Click **Next**.

### Your music folder

Choose the folder that contains your music. Subfolders are scanned automatically. The folder must
already exist. LyricLoom writes the `.lrc` files beside the audio and keeps its caches in its own
data folder, never inside the music folder. Click **Next** when the folder is valid.

### System check

LyricLoom probes the machine with timeouts and downloads nothing on this page. The table shows:

- **CPU:** logical cores.
- **Memory:** total RAM.
- **Free disk (models folder):** free and total space where the models will live.
- **GPUs:** display adapters reported by Windows.
- **WSL:** whether WSL 2 and which distros are installed.
- **whisper-cli:** the path that will be used, or why one was not found.

Click **Check again** to repeat the probes after installing a driver or WSL.

### Acceleration

The top of the page gives a suggested setup with a reason for each part. You can accept it or
choose another path:

- **CPU only** works on every machine and needs no extra setup.
- **Use an existing WSL GPU environment** checks the configured interpreter,
  `/opt/lyricloom/venv/bin/python` and every `/opt/*/bin/python` inside each WSL 2 distro. A probe
  checks `torch`, `torchaudio`, `audio_separator`, `g2p_en`, `nltk` and `lyricloom`, and whether the
  GPU is usable. Only a passing environment can be selected with **Use this**. The app saves the
  WSL settings only after that probe passes; restart LyricLoom to use them.
- **Set up a new WSL GPU environment** runs the bundled setup script and streams its log into the
  page. Choose **ROCm (AMD GPU)**, **CUDA (NVIDIA GPU)** or **CPU only inside WSL**. The script
  creates `/opt/lyricloom/venv`, installs PyTorch 2.5.1 from the matching ROCm 6.2, CUDA 12.4 or
  CPU index, installs `audio-separator`, `g2p_en`, `nltk` and the bundled LyricLoom wheel, then
  probes the result. ROCm must already be installed and working; the script does not install GPU
  drivers. **Cancel** stops between steps, keeps partial downloads and leaves the WSL settings
  unchanged. The default distro is Ubuntu 24.04 when no WSL 2 distro exists yet.
- **Install WSL now…** appears when WSL is missing. Windows asks for administrator rights and may
  ask you to restart. Nothing is started until you click the button.
- **Faster transcription** installs the official whisper.cpp **BLAS** build (faster CPU on any
  machine) or the **cuBLAS 12.4** build (NVIDIA GPU only), or selects the bundled whisper.cpp. The
  download is pinned by size and SHA-256, and the binary is tested with `--help` before it is
  saved.

The assistant does not run two setup jobs at once. If a job is still running, finish it or click
**Cancel** before leaving the page.

### Models

The page lists the suggested model for every stage, its size and its current state. The suggested
set totals about 5 GB. **Download now** fetches only the missing or incomplete files, shows byte
progress and keeps a partial file so a dropped download resumes. **Cancel** stops after the current
chunk; **Later** moves on without downloading. **Open Models window…** opens the full manager
described in [docs/models.md](models.md).

The download goes to `%LOCALAPPDATA%\LyricLoom\models`. The page checks free disk space before it
starts. A model is never downloaded while a song is processing.

### Privacy

Two separate choices:

- **Check for updates when LyricLoom starts and every 24 hours (contacts GitHub)** is on by
  default. The request goes to `api.github.com`, carries LyricLoom's version in the User-Agent and
  contains nothing about you or your library. Clear it to stop automatic checks; **Help > Check for
  updates…** still works when you ask.
- **When an update is found** chooses *Install updates automatically when LyricLoom closes*,
  *Ask before installing* or *Only tell me that a new version exists*.

Below that, **Allow uploading the isolated vocal to AssemblyAI for cloud transcription** is off by
default. A stored key alone never uploads anything. When cloud transcription is on, LyricLoom
uploads only the isolated vocal (not the full mix), the language code and a context prompt with the
artist and title. **Ask before uploading each queue** is on by default. See
[docs/privacy.md](privacy.md#optional-assemblyai).

### MusicBee

The page detects MusicBee from its folders, registry entries or Program Files and shows whether
Starry Karaoke is already in the Plugins folder. A portable copy that leaves none of those traces can
be updated from the release ZIP instead. **Install Starry Karaoke** or **Update Starry Karaoke**
copies the plugin bundled with LyricLoom; **Check again** refreshes the status. Close MusicBee first. The assistant
replaces the plugin's own files, replaces the shared `RomajiCore.dll`/`LibNMeCab.dll` only when the
bundled version is newer, and adds the `RomajiLyrics\IpaDic` dictionary only when it is missing.
LyricLoom works without MusicBee; this page is optional.

### Ready

A summary of the music folder, acceleration, model readiness, update/cloud choices and MusicBee
state. Each page saves its choices when you click **Next**; **Finish** marks the setup as complete and
opens the main window. You can reopen the
assistant later from **Help > Setup assistant…** or jump to its Acceleration page from
**Settings > Acceleration > Change…**.

## Models after setup

The Windows installer deliberately does **not** include the large models. The first-run assistant
offers them, and **Help > Models…** opens the full Models window at any time. It lists every model
per stage with size, status (Ready, Missing, Corrupt, Unverified, Downloading), where it is used and
its license. Buttons include **Download**, **Cancel**, **Verify**, **Repair**, **Use as default**,
**Use for a language…**, **Add custom model…** and **Remove custom model**.

When a queue starts without a required model, LyricLoom lists what is missing and offers to open the
Models window. A track never downloads a model by itself; it fails with a message naming the file
and the download command. The exact catalog, per-language and per-song choices, custom models,
offline install and verification are in **[docs/models.md](models.md)**.

## GPU paths

LyricLoom works on the CPU everywhere. The GPU paths are optional and can be changed later in
**Settings > Acceleration** or the setup assistant.

- **CPU only:** separation, forced alignment, the English singing model and whisper.cpp all run on
  the CPU. Separation is the slow stage.
- **Existing WSL GPU environment:** use the assistant's **Find WSL environments** and **Use this**
  for an environment that already has the packages and a working GPU. LyricLoom keeps the Windows
  app and sends only the heavy stages into WSL.
- **New WSL GPU environment:** let the assistant run the bundled script with ROCm, CUDA or CPU
  PyTorch. This needs WSL 2 and, for ROCm, the AMD driver and ROCm stack installed first.
- **Faster transcription:** the assistant can install whisper.cpp BLAS (faster CPU) or cuBLAS
  (NVIDIA). A Vulkan whisper.cpp build is not published by this project, but a compatible local
  build can be selected with the `whisper_cli` setting or `LYRICLOOM_WHISPER_CLI`.

If a WSL stage fails, LyricLoom falls back to the CPU and keeps processing. The status bar shows
`Device: CPU (fallback)` in orange and the track log records why. The complete WSL setup, manual
procedure, model copies and rollback are in **[docs/wsl-rocm.md](wsl-rocm.md)**.

## Process your songs

1. Select one or more rows. Use **Ctrl** or **Shift** to select several.
2. Click **Process selected**. To process every pending track, click **Process pending**.
3. Watch the progress bar and the status column:
   - **pending:** no LyricLoom `.lrc` yet.
   - **processing:** a queue is working on it.
   - **done:** finished with no review flags.
   - **review:** finished, but at least one line is uncertain. Check the orange row.
   - **failed:** something went wrong. Hover the row to see the error; the full traceback is in the
     track log.
   - **other:** a `.lrc` exists but was not written by LyricLoom, so it is left alone.
4. **Stop** finishes the current track and then stops the queue. The queue controls also offer
   stopping now and pausing after the current track.
5. **Force** reprocesses tracks even when the same engine version already wrote them. Leave it off
   normally.
6. **Redo selected** deletes only the word timing LyricLoom wrote and aligns again, reusing cached
   vocals and transcription. It keeps the official `.original.lrc`. For a song made with other
   models, **Redo with current models** uses the current choices.

One track at a time is processed on purpose. That keeps memory and VRAM use predictable; on a
CPU-only machine, separation is the slowest stage.

### Reviewing a track

1. Select the track to load it in the player.
2. Low-confidence lines are tinted orange. The `[#review:]` tag in the `.lrc` lists their zero-based
   line numbers.
3. Fix a word by selecting it and using the nudge buttons. Hold **Shift** to move the word's end
   instead of its start.
4. Use **Add word…**, **Delete word**, **Insert line…**, **Merge with line above** or **Delete
   line** to repair the structure. Destructive edits ask first; **Ctrl+Z** undoes any edit and
   **Ctrl+Y** (or **Ctrl+Shift+Z**) redoes it.
5. **Accept line** clears that line's `#review` flag and saves; **Accept all** clears every flag and
   saves. **F3** and **Shift+F3** jump between flagged lines.
6. **Paste lyrics…** replaces the whole lyric and aligns it again. The song must have been processed
   once, so the cached vocal stem and transcript exist.
7. Click **Save** (or press **Ctrl+S**). The previous main `.lrc` is kept as a `.bak` file.

Editing does not clear `#review` automatically. The track stays in the **Review** filter until you
accept the flagged lines (or process the song again). This is deliberate: a human edit is not proof
that every other line is correct. Accepting every flag writes an empty `[#review:]` tag, which is how
a transcription-only track leaves the Review filter.

## Playback

The built-in player uses the original audio and the cached isolated vocal.

Main window:

- **Play** (or **Space**) starts or pauses.
- The seek bar moves through the song; click it to jump to that point or drag and release to seek.
- Click a line to select it; double-click to seek to that line.
- **Play line** plays from the selected line and stops at its end.
- **Vocals only** switches to the cached `vocals.wav` when it exists, or to the kept
  `*.vocals.flac` stem when the scratch cache was cleared. The checkbox is disabled when neither
  exists.
- The current line in the player uses the same smooth animation as the karaoke window. The window
  follows the Windows light/dark setting, and every control is reachable by keyboard.
- **Settings > Smooth animation** offers **Match display (default)**, **Half refresh** and **Third
  refresh**. Lower rates are exact integer divisors of the monitor refresh rate, so motion does not
  judder. The main player's animation stops while nothing is playing.

**Karaoke** button (**Ctrl+K**):

- Opens a starry karaoke window for the selected track, starting at the current playback position.
- **Space** plays/pauses, **←/→** seek 5 seconds, **↑/↓** change volume.
- **F11** toggles fullscreen; **Esc** leaves fullscreen or closes the window.
- **N** and **P** move to the next or previous track in the library list.
- The **Script** list chooses the main `.lrc`, the Japanese text or the romaji version; the main
  `.lrc` follows the script chosen in Settings.
- The current line is highlighted word by word; the next line is dimmed. Stars and the lyric column
  move on the same frame clock. The window slows to a slow tick while paused and stops rendering
  while hidden or minimised.

For a MusicBee-based karaoke setup, the setup assistant (**Help > Setup assistant… > MusicBee**) can
install the Starry Karaoke plugin from the copy bundled with LyricLoom. See
[docs/musicbee.md](musicbee.md).

## Where settings and caches live

LyricLoom writes everything to `%LOCALAPPDATA%\LyricLoom` unless you override it with
`LYRICLOOM_DATA_DIR`.

| What | Default Windows path | Notes |
|---|---|---|
| Settings | `%LOCALAPPDATA%\LyricLoom\settings.json` | Library, vocals folder, Japanese script, model choices, update/install mode and optional WSL settings. |
| Models | `%LOCALAPPDATA%\LyricLoom\models` | About 5 GB when the suggested models are present. |
| Work cache | `%LOCALAPPDATA%\LyricLoom\work` | Per-track JSON caches, 16 kHz vocal copies and `log.txt`. Safe to delete when the app is closed. |
| Kept vocals | `%LOCALAPPDATA%\LyricLoom\vocals` | Lossless FLAC vocal stems and their manifests, outside the music library. Safe to delete; they are recreated. |
| Scan cache | `%LOCALAPPDATA%\LyricLoom\scan-*.json` | One small file per scanned library. Safe to delete. |
| App log | `%LOCALAPPDATA%\LyricLoom\logs\app.log` | Rotating log (about 1 MB, two older files) for the app, queue and updater. |
| AssemblyAI key | `%LOCALAPPDATA%\LyricLoom\assemblyai.key` | Encrypted with Windows DPAPI for your user; only present if you added a key. |
| whisper.cpp builds | `%LOCALAPPDATA%\LyricLoom\backends` | Installed BLAS/cuBLAS builds and their downloads. Safe to remove from the assistant or by hand. |
| whisper-cli fallback | `%LOCALAPPDATA%\LyricLoom\bin` | Used only if no bundled or `PATH` copy is found. |
| Update downloads | `%TEMP%\LyricLoom-update` | Verified installer downloads; removed on the next start. |
| Lyrics | Next to each audio file | `<song>.lrc`, `<song>.original.lrc`, and for Japanese songs the two script variants. |

Each track also has its own log at:

```text
%LOCALAPPDATA%\LyricLoom\work\<hash>\log.txt
```

The `<hash>` is derived from the audio path, size and modification time, so it changes when the file
changes. The app shows the error in the table; for a deeper look, open the track's log from the row
menu or **Help > Diagnostics…**. **Help > Open log folder** opens the app log folder. If you use a
source or pipx install, `lyricloom doctor` prints the same paths and model status.

### Changing the data folder

Set `LYRICLOOM_DATA_DIR` before starting the app to move settings, models, cache and vocals together:

```powershell
$env:LYRICLOOM_DATA_DIR = "D:\LyricLoomData"
```

To keep only the large models elsewhere, set `LYRICLOOM_MODELS` instead:

```powershell
$env:LYRICLOOM_MODELS = "D:\LyricLoomModels"
```

The environment variable must be set in the environment that starts LyricLoom. Setting it in one
PowerShell window does not affect a shortcut started from the Start menu.

## Update LyricLoom

Automatic update checks are **on by default**. LyricLoom asks GitHub for the latest public release
about four seconds after the window opens and then every 24 hours, sending only its version in the
User-Agent; nothing about you or your library is sent. Clear **Check GitHub Releases for updates at
startup and every 24 hours** in **Settings > Privacy** to stop them. **Help > Check for updates…**
always works as a one-off check.

When a newer release exists, a non-modal bar appears above the main window. **What's new** opens
the release page in your browser and shows the release notes in the app. **Later** dismisses the
bar. **Skip this version** stops that release being offered again; a newer release is offered
normally.

**Settings > When an update is found** chooses what happens:

- **Install automatically when LyricLoom closes** (default): the verified installer is downloaded
  in the background. The bar offers **Restart now**, which installs at once and reopens LyricLoom;
  **Later** keeps the download and installs it when you close LyricLoom normally.
- **Ask before installing**: the notice appears first. **Install now** downloads with progress and
  starts the interactive installer.
- **Only notify me**: the bar links to the release page; nothing is downloaded.

On Linux, whatever the mode, the bar links to the release page and offers **Download for Linux**
for the release tarball. On Linux and in a source checkout nothing is installed automatically.

A downloaded update is only run after the updater verifies its published SHA-256. The updater
refuses an installer with no checksum, with a wrong checksum, or from anywhere outside this
project's GitHub release. It also refuses a redirect away from GitHub's release asset hosts.

If a queue is running when you choose **Restart now** or **Install now**, LyricLoom asks whether to
stop it first. A normal exit installs a pending automatic update only after the queue has stopped.
Closing the window while a queue is running also asks whether to stop after the current song, stop
now or keep working.

The automatic (silent) update never closes MusicBee. If MusicBee is open, the optional Starry
Karaoke plugin is skipped for that run; the next LyricLoom start tells you and offers to open the
setup assistant's MusicBee page; close MusicBee and update the plugin there (or from the release ZIP).

You can also update manually:

1. Read the release notes on the [Releases page](https://github.com/nishizumi-maho/lyricloom/releases).
2. Close LyricLoom.
3. Download the new `LyricLoom-Setup-<version>.exe` and run it over the old installation. The
   stable asset name `LyricLoom-Setup.exe` points at the latest installer. For the portable build,
   replace the files in the portable folder.
4. Start LyricLoom again.

Your settings, library choice, models and caches are in `%LOCALAPPDATA%\LyricLoom`, so an in-place
update normally keeps them. Back up `settings.json` first if you have customized it.

A new engine version may cause songs to be reprocessed. This is expected: the `.lrc` format includes
an engine version, and a newer engine can produce different timings. The app skips songs already
written by the current engine unless you use **Force**.

## Uninstall

### Installed version

1. Close LyricLoom.
2. Open **Settings > Apps > Installed apps** (or **Add or remove programs**).
3. Find **LyricLoom**, choose **Uninstall**, and follow the prompt.
4. The uninstaller removes the program folder, shortcuts, the registry key and the plugin files it
   installed. It then asks once whether to also delete LyricLoom's own data folders: settings and
   logs, work cache, kept vocals, models, installed whisper.cpp builds and the AssemblyAI key.
   **No** is the default.

If you answer yes, only LyricLoom's default data folders are deleted. Custom `models`, `vocals` or
`work` locations from `settings.json`, and environment-provided locations
(`LYRICLOOM_DATA_DIR`, `LYRICLOOM_MODELS`, `LYRICLOOM_WORK`), are listed for you to remove by hand.
The uninstaller refuses to delete the data folder when it finds music files inside it or when the
configured music library is inside it.

Your music library and the `.lrc` files next to your music are never deleted by the uninstaller. The
shared `RomajiCore.dll`, `LibNMeCab.dll` and `RomajiLyrics\IpaDic` files used by other MusicBee
plugins are also left in place.

The default program folder is:

```text
%LOCALAPPDATA%\Programs\LyricLoom
```

### Portable version

Delete the folder you extracted. Nothing was installed system-wide. As with the installer, the data
in `%LOCALAPPDATA%\LyricLoom` remains unless you used `LYRICLOOM_DATA_DIR`.

### Remove leftover data

Only do this after you have backed up anything you want to keep:

```powershell
Remove-Item -LiteralPath "$env:LOCALAPPDATA\LyricLoom" -Recurse -Force
```

This removes settings, logs, models, caches, kept vocals, installed whisper.cpp builds and the
AssemblyAI key. It does **not** remove the `.lrc` files next to your music. Delete those separately
if you want to undo the lyric changes; the `.original.lrc` files and `.lrc.bak` backups are also
left in place.

If you used a custom `LYRICLOOM_DATA_DIR` or `LYRICLOOM_MODELS`, delete those folders too.

## Common first-run problems

- **The library is empty.** Check that the folder contains one of the supported audio extensions and
  that you selected the folder itself, not a parent with no audio. Click **Refresh**.
- **Every track fails with a model error.** The models are missing. Open **Help > Models…** and
  download them. See [docs/models.md](models.md).
- **The assistant says a WSL environment did not pass.** It needs `torch`, `torchaudio`,
  `audio_separator`, `g2p_en`, `nltk`, `lyricloom` and a working GPU. Read the error in the combo
  box tooltip or the setup log, or use the manual path in [docs/wsl-rocm.md](wsl-rocm.md).
- **Separation is extremely slow.** You are on the CPU. That is expected. See
  [What runs where](../README.md#what-runs-where) and, for AMD, [docs/wsl-rocm.md](wsl-rocm.md).
- **SmartScreen or antivirus blocks the app.** Verify the download hash, then allow the file. Do
  not turn off real-time protection permanently.
- **Lyrics cannot be written.** The music folder is read-only, controlled by antivirus "Controlled
  folder access", or on a locked network/cloud location. Choose a local writable library.
- **No sound in the player.** See
  [Qt multimedia and sound](troubleshooting.md#qt-multimedia-and-sound).

For anything else, see [docs/troubleshooting.md](troubleshooting.md). In a source or pipx install,
`lyricloom doctor` prints the diagnostic paths and model status. In a packaged build, use
**Help > Diagnostics…** and copy the text.
