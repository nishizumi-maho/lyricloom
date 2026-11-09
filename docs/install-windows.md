# Install LyricLoom on Windows

LyricLoom 2.0.0 runs on 64-bit Windows 10 and Windows 11. The normal installer includes the application, the worker and `whisper-cli`; you do not need Python, CUDA, or a separate Whisper installation. The large models are downloaded on first use (or from **Help > Models**).

There are two ways to run it:

- **Installer:** `LyricLoom-Setup-2.0.0.exe` from the [Releases page](https://github.com/nishizumi-maho/lyricloom/releases). Recommended for most people.
- **Portable ZIP:** `LyricLoom-2.0.0-win64.zip`. Extract and run, without an installer. Good for a USB stick or a folder you control.

Both use the same per-user data folder for settings, models, caches and logs. See [Where settings and caches live](#where-settings-and-caches-live).

## Before you start

- 64-bit Windows 10 or Windows 11.
- At least **10 GB free** for the app, the models and the working cache. A large library or many kept vocal stems needs more.
- 8 GB of RAM or more is recommended.
- Your music folder should be writable, because LyricLoom writes the `.lrc` next to each audio file.

LyricLoom reads these audio formats: `.flac`, `.mp3`, `.m4a`, `.ogg`, `.opus`, `.wav`. Other formats are ignored by the library scanner. Convert them first if needed.

The interface is **English-only** in 2.0.0.

## Install with the setup program

1. Open the [Releases page](https://github.com/nishizumi-maho/lyricloom/releases).
2. Download `LyricLoom-Setup-2.0.0.exe`. Do not use a third-party download site.
3. Run the setup file.
4. Follow the wizard. It installs for the current user under `%LOCALAPPDATA%\Programs\LyricLoom`, does not request administrator rights, and does not create file associations. The desktop shortcut is optional and unchecked by default.
5. Start **LyricLoom** from the Start menu or the desktop shortcut.

### If SmartScreen appears

A new open-source application may not have an established SmartScreen reputation yet. If Windows shows **"Windows protected your PC"**:

1. Click **More info**.
2. Check that the publisher and file name match the release you downloaded.
3. Click **Run anyway**.

Only do this for a file downloaded from the official Releases page. If you want to verify the download, compare its SHA-256 checksum with the value on the release page:

```powershell
Get-FileHash .\LyricLoom-Setup-*.exe -Algorithm SHA256
```

If the checksums do not match, delete the file and download it again. Do not disable SmartScreen or your antivirus permanently to work around a blocked installer.

## Install the portable ZIP

1. Download `LyricLoom-2.0.0-win64.zip` from the [Releases page](https://github.com/nishizumi-maho/lyricloom/releases).
2. Extract it to a folder you can write to, for example `D:\Apps\LyricLoom`. Do not run it from inside the ZIP preview window.
3. Run `LyricLoom.exe` in that folder.
4. Optional: create a shortcut to the executable.

The portable build does not need an installer, but by default it still keeps settings, models and caches in `%LOCALAPPDATA%\LyricLoom`, not in the extracted folder. That means you can replace the program files with a newer release without losing your settings.

To keep the data beside the portable app instead, set `LYRICLOOM_DATA_DIR` before launching. For example, from PowerShell in the app folder:

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

Use the launcher every time. If you move the folder, move `LyricLoomData` with it. Lyrics are still written next to the audio files, not into this data folder.

## First run

1. Start LyricLoom.
2. Click **Library…** and choose the folder that contains your music. Subfolders are scanned automatically.
3. The library table lists each track with artist, title, status, lyric source and confidence. A track with no `.lrc` starts as **pending**.
4. Choose the Japanese script for the main `.lrc`:
   - **Japanese: 日本語** keeps the Japanese text in the main file.
   - **Japanese: romaji** puts the romaji version in the main file.
   - Both `<song>.japanese.lrc` and `<song>.romaji.lrc` are always written for Japanese songs, so you can change this later without reprocessing.
5. Optional: click **AssemblyAI key…** to store a key. Cloud transcription stays off by default: a stored key alone never uploads audio, and the separate cloud-transcription option must also be turned on. Leave everything off to keep the app fully local. See [Privacy](../docs/privacy.md).

### Models on first run

The Windows installer deliberately does **not** include the large models. On first launch, LyricLoom checks for them and opens the Models window (Help > Models) that lists what is missing. Accept the downloads and keep the app open; the total is about 5.3 GB. The files go to `%LOCALAPPDATA%\LyricLoom\models`.

You can defer a model and fetch it later from the same dialog. The app cannot process a song until the models that stage needs are present.

The `lyricloom models status` / `lyricloom models download all` commands are part of a **source or pipx install**, not the windowed Windows release. If you use a source checkout or need the offline/manual placement procedure, see [docs/models.md](models.md). The exact paths and per-model sizes are there too.

Once the models are downloaded, you can start with one song while you learn the workflow; the first separation is slower because the model has to load.

## Process your songs

1. Select one or more rows. Use **Ctrl** or **Shift** to select several.
2. Click **Process selected**. To process every pending track, click **Process pending**.
3. Watch the progress bar and the status column:
   - **pending**: no LyricLoom `.lrc` yet.
   - **processing**: a queue is working on it.
   - **done**: finished with no review flags.
   - **review**: finished, but at least one line is uncertain. Check the orange row.
   - **failed**: something went wrong. Hover the row to see the error; the full traceback is in the track log.
   - **other**: a `.lrc` exists but was not written by LyricLoom, so it is left alone.
4. **Stop** finishes the current track and then stops the queue.
5. **Force** reprocesses tracks even when the same engine version already wrote them. Leave it off normally.
6. **Redo selected** deletes only the word timing LyricLoom wrote and aligns again, reusing cached vocals and transcription. It keeps the official `.original.lrc`.

One track at a time is processed on purpose. That keeps memory and VRAM use predictable; on a CPU-only machine, separation is the slowest stage.

### Reviewing a track

1. Select the track to load it in the player.
2. Low-confidence lines are tinted orange. The `[#review:]` tag in the `.lrc` lists their zero-based line numbers.
3. Fix a word by selecting it and using the nudge buttons. Hold **Shift** to move the word's end instead of its start.
4. Use **Add word…**, **Delete word**, **Insert line…**, **Merge with line above** or **Delete line** to repair the structure. Destructive edits ask first; **Ctrl+Z** undoes any edit and **Ctrl+Y** (or **Ctrl+Shift+Z**) redoes it.
5. **Accept line** clears that line's `#review` flag and saves; **Accept all** clears every flag and saves. **F3** and **Shift+F3** jump between flagged lines.
6. **Paste lyrics…** replaces the whole lyric and aligns it again. The song must have been processed once, so the cached vocal stem and transcript exist.
7. Click **Save** (or press **Ctrl+S**). The previous main `.lrc` is kept as a `.bak` file.

Editing does not clear `#review` automatically. The track stays in the **Review** filter until you accept the flagged lines (or process the song again). This is deliberate: a human edit is not proof that every other line is correct. Accepting every flag writes an empty `[#review:]` tag, which is how a transcription-only track leaves the Review filter.

## Playback

The built-in player uses the original audio and the cached isolated vocal.

Main window:

- **Play** (or **Space**) starts or pauses.
- The seek bar moves through the song; click it to jump to that point or drag and release to seek.
- Click a line to select it; double-click to seek to that line.
- **Play line** plays from the selected line and stops at its end.
- **Vocals only** switches to the cached `vocals.wav` when it exists, or to the kept `*.vocals.flac` stem when the scratch cache was cleared. The checkbox is disabled when neither exists.
- The window follows the Windows light/dark setting, and every control is reachable by keyboard (menus list their shortcuts).

**Karaoke** button (**Ctrl+K**):

- Opens a starry karaoke window for the selected track, starting at the current playback position.
- **Space** plays/pauses, **←/→** seek 5 seconds, **↑/↓** change volume.
- **F11** toggles fullscreen; **Esc** leaves fullscreen or closes the window.
- **N** and **P** move to the next or previous track in the library list.
- The **Script** list chooses the main `.lrc`, the Japanese text or the romaji version; the main `.lrc` follows the script chosen in Settings.
- The current line is highlighted word by word; the next line is dimmed.
- **Vocals only** is enabled only when the cached or kept vocal stem exists.

For a MusicBee-based karaoke setup, the setup assistant (**Help > Setup assistant… > MusicBee**) can install the Starry Karaoke plugin from the copy bundled with LyricLoom. See [docs/musicbee.md](musicbee.md).

## Where settings and caches live

LyricLoom writes everything to `%LOCALAPPDATA%\LyricLoom` unless you override it with `LYRICLOOM_DATA_DIR`.

| What | Default Windows path | Notes |
|---|---|---|
| Settings | `%LOCALAPPDATA%\LyricLoom\settings.json` | Library, vocals folder, Japanese script and optional WSL settings. |
| Models | `%LOCALAPPDATA%\LyricLoom\models` | About 5.3 GB when all models are present. |
| Work cache | `%LOCALAPPDATA%\LyricLoom\work` | Per-track JSON caches, 16 kHz vocal copies and `log.txt`. Safe to delete when the app is closed. |
| Kept vocals | `%LOCALAPPDATA%\LyricLoom\vocals` | Lossless FLAC vocal stems, outside the music library. Safe to delete; they are recreated. |
| Scan cache | `%LOCALAPPDATA%\LyricLoom\scan-*.json` | One small file per scanned library. Safe to delete. |
| AssemblyAI key | `%LOCALAPPDATA%\LyricLoom\assemblyai.key` | Encrypted with Windows DPAPI for your user; only present if you added a key. |
| whisper-cli fallback | `%LOCALAPPDATA%\LyricLoom\bin` | Used only if no bundled or `PATH` copy is found. |
| Lyrics | Next to each audio file | `<song>.lrc`, `<song>.original.lrc`, and for Japanese songs the two script variants. |

There is no global rolling log file in 2.0.0. Each track has its own log at:

```text
%LOCALAPPDATA%\LyricLoom\work\<hash>\log.txt
```

The `<hash>` is derived from the audio path, size and modification time, so it changes when the file changes. The app shows the error in the table; for a deeper look, open the track's log. If you use a source or pipx install, `lyricloom doctor` prints the same paths and model status.

### Changing the data folder

Set `LYRICLOOM_DATA_DIR` before starting the app to move settings, models, cache and vocals together:

```powershell
$env:LYRICLOOM_DATA_DIR = "D:\LyricLoomData"
```

To keep only the large models elsewhere, set `LYRICLOOM_MODELS` instead:

```powershell
$env:LYRICLOOM_MODELS = "D:\LyricLoomModels"
```

The environment variable must be set in the environment that starts LyricLoom. Setting it in one PowerShell window does not affect a shortcut started from the Start menu.

## Update LyricLoom

Automatic update checks are on by default. LyricLoom asks GitHub for the latest public release
shortly after start-up and then every 24 hours, sending only its version in the User-Agent; nothing
about you or your library is sent. The check can be turned off in **Settings**, and **Help > Check
for updates** always works as a one-off check.

**Settings > When an update is found** chooses what happens:

- **Install automatically when LyricLoom closes** (default): the verified installer is downloaded
  in the background; a notice offers **Restart now**, and closing LyricLoom normally installs it
  silently. **Later** keeps the download and installs it on exit.
- **Ask before installing**: the notice appears first. **Install now** downloads with progress and
  starts the interactive installer.
- **Only notify me**: the notice links to the release page; nothing is downloaded.

**Skip this version** stops that release being offered again; a newer release is offered normally.
A downloaded update is only run after the updater verifies its published SHA-256. The updater refuses
an installer with no checksum, with a wrong checksum, or from anywhere outside this project's GitHub
release. If a queue is running when you choose **Restart now** or **Install now**, LyricLoom asks
whether to stop it first; a normal exit installs a pending automatic update only after the queue has
stopped.

The automatic (silent) update never closes MusicBee. If MusicBee is open, the optional Starry
Karaoke plugin is skipped for that run; the next start tells you and asks you to close MusicBee and
run the installer again.

You can also update manually:

1. Read the release notes on the [Releases page](https://github.com/nishizumi-maho/lyricloom/releases).
2. Close LyricLoom.
3. Download the new `LyricLoom-Setup-<version>.exe` and run it over the old installation. The stable asset name `LyricLoom-Setup.exe` points at the latest installer. For the portable build, replace the files in the portable folder.
4. Start LyricLoom again.

Your settings, library choice, models and caches are in `%LOCALAPPDATA%\LyricLoom`, so an in-place update normally keeps them. Back up `settings.json` first if you have customized it.

A new engine version may cause songs to be reprocessed. This is expected: the `.lrc` format includes an engine version, and a newer engine can produce different timings. The app skips songs already written by the current engine unless you use **Force**.

## Uninstall

### Installed version

1. Close LyricLoom.
2. Open **Settings > Apps > Installed apps** (or **Add or remove programs**).
3. Find **LyricLoom**, choose **Uninstall**, and follow the prompt.
4. The uninstaller removes the program folder and shortcuts, then asks once whether to also delete LyricLoom's own data folders: settings and logs, work cache, kept vocals, models and the AssemblyAI key. **No** is the default. If you answer yes, only LyricLoom's default data folders are deleted; custom `models`, `vocals` or `work` locations from `settings.json`, and environment-provided locations, are listed for you to remove by hand.

Your music library and the `.lrc` files next to your music are never deleted by the uninstaller.

The default program folder is:

```text
%LOCALAPPDATA%\Programs\LyricLoom
```

### Portable version

Delete the folder you extracted. Nothing was installed system-wide. As with the installer, the data in `%LOCALAPPDATA%\LyricLoom` remains.

### Remove leftover data

Only do this after you have backed up anything you want to keep:

```powershell
Remove-Item -LiteralPath "$env:LOCALAPPDATA\LyricLoom" -Recurse -Force
```

This removes settings, models, caches, kept vocals and the AssemblyAI key. It does **not** remove the `.lrc` files next to your music. Delete those separately if you want to undo the lyric changes; the `.original.lrc` files and `.lrc.bak` backups are also left in place.

If you used a custom `LYRICLOOM_DATA_DIR` or `LYRICLOOM_MODELS`, delete those folders too.

## Common first-run problems

- **The library is empty.** Check that the folder contains one of the supported audio extensions and that you selected the folder itself, not a parent with no audio. Click **Refresh**.
- **Every track fails with a model error.** The models are missing. Reopen Help > Models and download them. See [docs/models.md](models.md).
- **Separation is extremely slow.** You are on the CPU. That is expected. See [GPU options](../README.md#gpu-options) and, for AMD, [docs/wsl-rocm.md](wsl-rocm.md).
- **SmartScreen or antivirus blocks the app.** Verify the download hash, then allow the file. Do not turn off real-time protection permanently.
- **Lyrics cannot be written.** The music folder is read-only, controlled by antivirus "Controlled folder access", or on a locked network/cloud location. Choose a local writable library.
- **No sound in the player.** See [Qt multimedia and sound](troubleshooting.md#qt-multimedia-and-sound).

For anything else, see [docs/troubleshooting.md](troubleshooting.md). In a source or pipx install, `lyricloom doctor` prints the diagnostic paths and model status.
