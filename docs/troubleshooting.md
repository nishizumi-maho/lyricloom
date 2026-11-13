# Troubleshooting

If you use a **source or pipx install**, start here:

```bash
lyricloom doctor
```

It prints the version, Python, data folder, library, vocals cache, models folder, `whisper-cli` path, ffmpeg, separator/MMS/MTL readiness, and whether PyTorch can see a GPU. Most problems are visible in that output.

Also useful in a source/pipx install:

```bash
lyricloom models status
lyricloom --version
```

The packaged Windows and Linux GUI builds are windowed applications and do not expose the console
command in 2.2.0. Use **Help > Diagnostics…** (copy the text), **Help > Models…**, the status bar and
the per-track logs; the source/pipx commands below are still the clearest way to inspect a machine if
you can install them.

Per-track logs are in:

```text
Windows: %LOCALAPPDATA%\LyricLoom\work\<hash>\log.txt
Linux:   ~/.local/share/lyricloom/work/<hash>/log.txt
```

The app itself also keeps a rotating log at `%LOCALAPPDATA%\LyricLoom\logs\app.log`
(`~/.local/share/lyricloom/logs/app.log` on Linux). **Help > Open log folder** opens it.

The `<hash>` changes when the audio file changes. To find a song's log on Windows:

```powershell
Get-ChildItem "$env:LOCALAPPDATA\LyricLoom\work" -Recurse -Filter log.txt |
  Select-String -Pattern "Song Title" -List
```

On Linux:

```bash
grep -rl "Song Title" ~/.local/share/lyricloom/work --include=log.txt
```

## Setup assistant and models

The first start opens **LyricLoom setup assistant**. It is also under **Help > Setup assistant…** and
has these pages: Welcome, Your music folder, System check, Acceleration, Models, Privacy, MusicBee and
Ready.

- **A page will not continue.** A setup or download may still be running. Wait for it to finish or
  click **Cancel**; the assistant does not run two jobs at once.
- **No WSL environment passes.** The probe needs `torch`, `torchaudio`, `audio_separator`, `g2p_en`,
  `nltk`, `lyricloom` and a working GPU. Read the detailed error in the combo-box tooltip or the
  setup log, or use the manual path in [docs/wsl-rocm.md](wsl-rocm.md).
- **The GPU on Windows setup fails.** Read the last lines of the setup log on the page: they are
  the installer's own message. *Not enough free disk space* needs about 8 GB (CUDA) or 3 GB
  (DirectML) on the drive that holds `%LOCALAPPDATA%\LyricLoom`. A network error can simply be
  retried with **Set up and use**: what was already downloaded is kept. *PyTorch found no CUDA
  device* means the NVIDIA driver is missing or too old; update it and run the setup again.
  *The GPU refused a test operation* means this build of PyTorch has no code for the card; send
  the message with **Help > Diagnostics…** in a bug report. In every case the acceleration
  setting is left as it was and LyricLoom keeps working on the CPU.
- **DirectML is set up but separation is still slow.** Without **Run RoFormer models on the GPU
  too**, the suggested Mel-Band RoFormer model stays on the CPU and the status bar says
  `Device: CPU (fallback)` with that reason. Tick the option on a card with about 16 GB of video
  memory, or choose an MDX-Net model in **Help > Models…**, which needs far less memory at some
  cost in separation quality. Both alignment models always run on the CPU with DirectML.
- **DirectML: "not enough GPU video memory".** DirectML ran out of video memory for a RoFormer
  model; the song was separated on the CPU instead. Close games and other programs that use the
  graphics card and try again. If it keeps happening, untick **Run RoFormer models on the GPU
  too** so no time is lost on the failed attempt.
- **The setup assistant has no WSL setup script.** A source checkout does not build the wheel. Use the
  manual procedure in [docs/wsl-rocm.md](wsl-rocm.md), or a packaged Windows build.
- **A model is missing or corrupt.** Open **Help > Models…**. Select the row and use **Download**,
  **Verify** or **Repair**. See [docs/models.md](models.md).
- **Every track fails with a model error.** A queue checks its models first and offers to download
  what is missing. A model is never downloaded during a song; the track log names the file and the
  `lyricloom models download` command.
- **Not enough disk space.** The Models page checks free space before downloading. Free space in the
  models folder, or move it with `LYRICLOOM_MODELS`.
- **"Made with other models" appears.** The `.lrc` records its model ids in `[#models:…]`, and they
  differ from the current choices. Use **Redo with current models** if you want the current set.
- **An upgrade from 2.0 is redoing work.** Existing caches and kept vocals are reused when the models
  are still the catalog defaults. A changed model, a changed audio file or a new engine version can
  invalidate the affected stages. See [docs/models.md](models.md#upgrading-from-20).

## Updates

Automatic update checks are **on by default**. LyricLoom contacts `api.github.com` shortly after
start-up and every 24 hours; clear the check in **Settings > Privacy** to stop it. **Help > Check for
updates…** is always a manual one-off.

- **No update is offered.** You may already be current, the update check may be off, or the release
  may be skipped. **Skip this version** only skips that release; a newer one is offered normally.
- **The download fails.** Use **Help > Check for updates…** to try again, or download from the release
  page. A missing, wrong or unavailable SHA-256 is refused by design.
- **The installer does not start.** The updater accepts only this project's GitHub release assets,
  re-checks the SHA-256 before launching, and refuses a file it did not download and verify itself.
  Download the installer manually from the [Releases page](https://github.com/nishizumi-maho/lyricloom/releases)
  if needed.
- **MusicBee was open during a silent update.** LyricLoom intentionally skipped the plugin files
  rather than closing MusicBee. Close MusicBee and use **Help > Setup assistant… > MusicBee** or the
  release ZIP.
- **A queue was running.** **Restart now** and **Install now** ask whether to stop the queue first. A
  normal exit installs a pending automatic update only after the queue has stopped.


## No lyrics found

The track fails with an error such as `no lyrics found anywhere and the transcription is unusable`, or it completes as `review` with `#source:transcription`.

### Check what happened

Open the track log. Look for lines like:

```text
lrclib: blocked (...)
genius: error ...
failed
source=transcription
```

The app table shows `review` when Whisper's transcript became the lyric. Hover the row for a short error.

### Common causes

- **Wrong or incomplete tags.** The search uses the artist and title from the audio tags. A missing artist, a title with `feat.`, a TV-size edit, or a romaji/Japanese mismatch can hide the right lyric. Fix the tags in your tag editor, then use **Force** or **Redo selected**.
- **The lyric exists only on a blocked site.** LyricLoom deliberately skips providers that return 401/403/429 instead of bypassing them. Try another release or paste the lyric manually.
- **The song is an instrumental, a cover, or a different-language version.** There may be no lyric that matches what is sung. The aligner can still produce line timing from a transcript, but not an official word-timed lyric.
- **The audio is an intro, a short clip or a medley.** A lyric for the full song does not match the vocal. Use the exact release, or paste the matching text.
- **Network/proxy/TLS failure.** The log shows the source error. Test the provider URL in a browser; corporate proxies and offline machines need cached lyrics or manual paste.
- **All sources return a lyric that does not match the audio.** LyricLoom rejects candidates below its transcript-match threshold. That is intentional; forcing a wrong lyric would produce worse timing. Paste the correct text.

### What to try

1. Fix artist/title tags. Remove bracketed extras such as `(TV Size)` or `[Single]`; LyricLoom already tries a variant with brackets removed, but clean tags help.
2. Process the exact audio file again with **Force**.
3. Use **Paste lyrics…** in the app. The song must have been processed once, because the app reuses the cached vocal stem and transcript. This is often the fastest fix for an obscure release.
4. If the track has an official lyric in a text file, paste it rather than copying from a web page with credits and ads.
5. Optional: add an AssemblyAI key for a second transcription on difficult tracks. This uploads the isolated vocal; read [docs/privacy.md](privacy.md#optional-assemblyai) first.
6. For the CLI, `--no-cloud` guarantees no AssemblyAI upload for that run.

If the lyric text is correct but a few lines are untimed, that is a different problem; see [Word timing is missing or wrong](#word-timing-is-missing-or-wrong).

## Whisper CLI or model missing

Typical errors:

```text
whisper-cli was not found.
the Whisper model is missing: ...\ggml-large-v3.bin
whisper-cli failed: ...
```

### Check the paths

```bash
lyricloom doctor
```

It prints the `whisper-cli` path and whether the file exists, plus the models folder.

LyricLoom looks for `whisper-cli` in:

1. The `whisper_cli` setting, or `LYRICLOOM_WHISPER_CLI`.
2. The bundled `tools/bin` folder.
3. A developer checkout's `tools/bin`.
4. `%LOCALAPPDATA%\LyricLoom\bin` on Windows, or `~/.local/share/lyricloom/bin` on Linux.
5. Your `PATH`.

The default model is `<models>/ggml-large-v3.bin`. Choose another catalog model with
`lyricloom models use transcribe <id>`; a tiny placeholder file will not work. The default model is
about 3 GB.

### Fix it

```bash
lyricloom models list
lyricloom models download whisper
lyricloom doctor
```

On Linux, if `whisper-cli` is missing, build it as described in [docs/install-linux.md](install-linux.md#build-whisper-cli). On Windows, reinstall the app or restore the bundled `whisper-cli.exe` and its DLLs (`ggml.dll`, `ggml-cpu.dll`, optionally `ggml-vulkan.dll`); copying only the `.exe` is not enough.

If `whisper-cli` starts but exits with an error, run it directly to see the full message:

```powershell
& "C:\Path\To\whisper-cli.exe" -m "C:\Path\To\ggml-large-v3.bin" -f test.wav -ojf -of test
```

Common causes are a corrupted model, a missing shared library, an unsupported CPU instruction set, or an antivirus quarantine. Verify the model checksum with `lyricloom models download whisper` again if in doubt.

### Whisper output looks hallucinated

LyricLoom detects credits, repeated short phrases and transcripts with too few words. It logs:

```text
whisper output looks hallucinated (credits / repetition / too few words): not used
```

This is not an installation error. It means the audio is unusual (instrumental, spoken, very short, or a different language). LyricLoom uses another source or transcription path if it can. If the song is fine, try a cleaner source file or add AssemblyAI.

## ffmpeg

Typical errors mention `ffmpeg`, `ffprobe`, or `audio-separator` failing to decode.

### Check

```bash
ffmpeg -version
lyricloom doctor
```

`lyricloom doctor` reports ffmpeg as ready when the Python package `imageio-ffmpeg` has its bundled binary, or when `ffmpeg` is on `PATH`.

### Fix

- **Linux:** `sudo apt install ffmpeg`.
- **Windows:** the normal build includes an ffmpeg through `imageio-ffmpeg`. If it is missing, reinstall the app. You can also install ffmpeg and put it on `PATH`, but LyricLoom does not have a separate "ffmpeg path" setting.
- **WSL:** install ffmpeg inside the distro: `sudo apt install ffmpeg`. The Windows ffmpeg is not automatically available to the Linux worker. See [docs/wsl-rocm.md](wsl-rocm.md).
- **Antivirus:** a quarantined `ffmpeg.exe` looks like "ffmpeg not found". Check the antivirus log.

`audio-separator` calls ffmpeg as an external program. A Python-only ffmpeg is not enough for every separator path, so a system ffmpeg is the safer setup.

## Qt multimedia and sound

The built-in player uses Qt Multimedia (`QMediaPlayer`). The app can show lyrics and process audio even when playback is silent.

### Linux

Install GStreamer and its codec plugins:

```bash
sudo apt install gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav
```

Check a file outside LyricLoom:

```bash
gst-play-1.0 "/path/to/song.flac"
```

If that fails, the problem is the GStreamer installation, not LyricLoom. If it works but LyricLoom does not, run with Qt plugin debugging:

```bash
QT_DEBUG_PLUGINS=1 lyricloom-app
```

On Wayland, try the X11 platform plugin:

```bash
QT_QPA_PLATFORM=xcb lyricloom-app
```

### Windows

Qt uses Windows Media Foundation. Most FLAC/MP3/M4A/WAV files play; unusual codecs or damaged files may not. Test the same file in another player. Updating the Windows codecs or converting the file usually helps.

### The player is silent but the progress bar moves

- Check the Windows/Linux output device and volume.
- Check that the track is not muted in the system mixer.
- Try another audio file.
- **Vocals only** is disabled when neither the cached vocal file nor the kept `*.vocals.flac` stem
  exists. Process or redo the song to create one.

### The player shows no lyrics

The track may not have a LyricLoom `.lrc`, or it may have a `.lrc` from another program that the parser cannot read. Process it in LyricLoom first. `other` in the library means the `.lrc` was not written by LyricLoom; processing it will back up the old file and write a new one.

### Smooth animation is slow or looks wrong

The lyric view animates at the monitor refresh rate by default. **Settings > Smooth animation** can
use **Half refresh** or **Third refresh**; those are exact integer divisors, not arbitrary caps. A
lower rate reduces CPU/GPU use on a slow machine.

- **The main window is idle but still busy.** The compact player's timer stops when nothing plays; the
  karaoke window keeps a slow tick while paused so the stars stay alive.
- **The karaoke window stops moving when hidden or minimised.** That is intentional. Restore it and
  rendering resumes.
- **Motion judders on a high-refresh monitor.** Use **Match display** and make sure the window is on
  the monitor you expect; the view follows the screen's actual refresh rate.
- **Words flash rather than sweep.** Very short words use a 60 ms minimum ramp; if the timing itself is
  wrong, edit the word in LyricLoom.
- **MusicBee frame rate.** The plugin has its own **Settings > Effects > Window frame rate** with
  **Match display**, **Half refresh** and **Third refresh**. It does not change MusicBee's frame rate
  or another plugin's. See [docs/musicbee.md](musicbee.md#smooth-motion-and-frame-rate).

## CUDA or ROCm not used

### Linux

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
lyricloom doctor
```

If `torch.cuda.is_available()` is `False`:

- The NVIDIA driver or ROCm runtime is missing or mismatched.
- The installed torch is a CPU build. Reinstall torch and torchaudio from the correct CUDA/ROCm index.
- For ROCm, your user is not in `render`/`video`, or the GPU needs `HSA_OVERRIDE_GFX_VERSION`.
- You are running a different Python environment from the one LyricLoom uses. Compare `which python` and the path in `lyricloom doctor`.

The app's separation device is controlled by `LYRICLOOM_SEPARATOR_DEVICE` (`auto` by default, or `cpu`). The alignment device is `LYRICLOOM_ALIGN_DEVICE` (`auto` on Linux, `cpu` on Windows). If you set either to `cpu`, the GPU is intentionally not used.

### Windows

**NVIDIA:** open **Help > Setup assistant… > Acceleration**, choose **NVIDIA GPU (CUDA)** under **GPU on Windows** and click **Set up and use**. The status under the backend must read *in use*. The bundled app itself is CPU-only, so the Windows-side `doctor` showing `cuda=False` is expected; the runtime's interpreter in `%LOCALAPPDATA%\LyricLoom\runtimes\cuda` is the one that must see the GPU, and the setup tests exactly that.

**AMD and Intel:** the full path is WSL 2 + ROCm for AMD: [docs/wsl-rocm.md](wsl-rocm.md). **DirectML** under **GPU on Windows** needs no WSL, but it only speeds up MDX-Net and VR separator models (see [Setup assistant and models](#setup-assistant-and-models)).

The status bar shows where the last separation ran. `Device: CPU (fallback)` in orange means a GPU attempt failed or the GPU could not run that model; hover it for the reason, then read the track log. If the runtime folder was deleted by hand, the reason says the runtime is missing: set it up again or choose **CPU only**.

### The GPU is used but the result is worse

GPU and CPU should produce the same model output. If timings got worse after changing hardware, check that you did not change the source audio, the lyric source, or the separator overlap at the same time. Use **Redo selected** to compare on the same file, and keep a `.lrc.bak` of the previous result.

## WSL

Use this checklist when `wsl_gpu` is enabled but separation still runs on the CPU.

1. **Is WSL 2 installed and running?**

   ```powershell
   wsl -l -v
   wsl --update
   ```

   The distro must show `VERSION 2`.

2. **Is the exact distro name in `settings.json`?**

   ```powershell
   wsl -l -q
   ```

   Copy the name exactly, including a version suffix such as `Ubuntu-22.04`. Remove the NUL characters if PowerShell displays them.

3. **Does the interpreter exist?**

   ```powershell
   wsl -d Ubuntu -- test -x /opt/lyricloom/venv/bin/python
   wsl -d Ubuntu -- /opt/lyricloom/venv/bin/python -c "import torch; print(torch.cuda.is_available())"
   ```

4. **Can the worker import LyricLoom?**

   ```powershell
   wsl -d Ubuntu -- /opt/lyricloom/venv/bin/python -c "import lyricloom; print(lyricloom.__file__)"
   ```

   If this fails, install the package into the venv with `--no-deps` as shown in [docs/wsl-rocm.md](wsl-rocm.md#5-install-audio-separator-the-mtl-packages-and-lyricloom).

5. **Is `wsl_gpu` actually true?** It is read at app startup. Save `settings.json`, close LyricLoom completely, and start it again. `lyricloom doctor` should print `wsl enabled True`.

6. **Did you restart WSL after a driver or group change?**

   ```powershell
   wsl --shutdown
   ```

   Then reopen the app. The first command may take a few seconds while the distro starts.

7. **Is the GPU visible?**

   ```powershell
   wsl -d Ubuntu -- ls -l /dev/dri
   wsl -d Ubuntu -- rocminfo
   ```

   If `rocminfo` does not list the GPU, fix the Windows AMD driver or the ROCm installation before debugging LyricLoom.

8. **Did you set an unnecessary HSA override?** A wrong `wsl_hsa_override` can hide the GPU. Remove it and retry. For RDNA 2, try `10.3.0`; for other cards, check AMD's documentation.

9. **Read the track log.** It contains the WSL stderr tail, for example a missing `audio_separator`, a missing checkpoint, or a Python traceback.

10. **Fallback is expected to be safe.** If WSL fails, the CPU path runs. You can keep working while you fix the GPU setup. Set `"wsl_gpu": false` to skip the failed attempt and go straight to CPU.

Full setup and rollback: [docs/wsl-rocm.md](wsl-rocm.md).

## Windows SmartScreen and antivirus

### SmartScreen

If Windows shows "Windows protected your PC":

1. Click **More info**.
2. Confirm the file came from the official [Releases page](https://github.com/nishizumi-maho/lyricloom/releases).
3. Click **Run anyway**.

Verify the SHA-256 hash against the release notes if you want certainty:

```powershell
Get-FileHash .\LyricLoom-Setup-*.exe -Algorithm SHA256
```

Do not disable SmartScreen permanently. A mismatch means the download is corrupt or not the file you think it is.

### Antivirus false positives

LyricLoom is a PyInstaller application and includes a separate worker executable and a whisper.cpp binary. Some antivirus engines flag unsigned/new PyInstaller binaries. If the app works but a stage fails, check whether these were quarantined:

- `LyricLoomWorker.exe`
- `whisper-cli.exe` and its DLLs
- `ffmpeg.exe` (bundled by `imageio-ffmpeg`)

Restore them from quarantine and add an exclusion for the LyricLoom install folder **only if you trust the download**. Reinstall if the files were deleted. Do not turn off real-time protection for the whole system.

Windows **Controlled folder access** can block writing `.lrc` files next to your music. Allow LyricLoom or choose a library folder that it can write to.

## Permissions

LyricLoom needs:

- **Read** access to the audio files and their folder.
- **Write** access to the folder containing each audio file, for the `.lrc` and backups.
- **Write** access to the per-user data folder.

Test the music folder on Windows:

```powershell
New-Item -ItemType File "$env:USERPROFILE\Music\.lyricloom-write-test"
Remove-Item "$env:USERPROFILE\Music\.lyricloom-write-test"
```

On Linux:

```bash
touch "/path/to/music/.lyricloom-write-test" && rm "/path/to/music/.lyricloom-write-test"
```

Common blockers:

- Read-only mount or network share.
- OneDrive/Dropbox "files on demand" placeholders.
- Antivirus controlled folder access.
- A library inside `Program Files` or another protected location.
- A folder owned by another user.

Move the library to a local folder you own, or fix the permissions. Do not run the whole app as Administrator as a workaround; that creates files owned by Administrator and complicates later edits.

## Long paths

Windows has a traditional 260-character path limit unless long paths are enabled. Deep artist/album/title folders plus `.japanese.lrc` can exceed it.

Symptoms include "path too long", "file not found" for a file you can see, or a track that scans but fails on write.

Fixes:

- Move the library to a shorter root, for example `D:\Music`.
- Shorten very long file names.
- Enable **Win32 long paths** in Windows (Group Policy or the `LongPathsEnabled` registry value) and restart. This is a system-wide change; understand it before applying it.
- Keep the per-user data folder on a short path too.

On Linux, the limit is 255 bytes per file name, and the `.japanese.lrc` suffix adds bytes. Rename extremely long titles.

## Japanese script

### The main `.lrc` is in the wrong script

In LyricLoom, choose **Japanese: 日本語** or **Japanese: romaji**. Changing the setting rewrites the main `.lrc` of Japanese songs under the current library from the kept `.japanese.lrc`/`.romaji.lrc` files. Both variants are always kept, so no reprocessing is needed.

If a song was processed by an older version that only wrote the main `.lrc`, changing the setting creates the missing variants from that file.

### The plugin shows romaji but I wanted Japanese

Set LyricLoom's script to Japanese, then use the Starry Karaoke Japanese mode. If the main `.lrc` is romaji, the plugin sees Latin text and cannot apply its Japanese romaji mode. See [docs/musicbee.md](musicbee.md#japanese-modes-in-the-plugin).

### Japanese text shows boxes

That is a font problem in the player or plugin, not in the `.lrc`. Choose a font with Japanese glyphs (for example Noto Sans JP, Yu Gothic or Meiryo). On a minimal Linux install, install a Japanese font package such as `fonts-noto-cjk`.

### Romaji is wrong

Romanization uses MeCab/IPADic and pykakasi. Names, invented readings and unusual kanji can be wrong. The `.japanese.lrc` remains the authoritative text; edit the romaji file or the app's displayed text if needed. Inline furigana such as `運命(さだめ)` is used as the reading.

### The song was not detected as Japanese

The detector looks for Japanese kana/kanji in the tags and lyric text. A Japanese song with an English title and English artist tags may be detected from the lyric text during alignment; if both the tags and lyric are ambiguous, it may use the non-Japanese path. The `.japanese.lrc`/`.romaji.lrc` files are only written when Japanese characters are found in the final lyric. Fix the tags or paste the Japanese lyric to force the issue.

Chinese lyrics that use only Han characters can be ambiguous with Japanese kanji; 2.2.0 does not have a separate Chinese mode. Check the output and use manual editing if needed.

## Word timing is missing or wrong

- **Line has only `[mm:ss.xx]`, no `<...>` tags.** The line could not be word-aligned. Check the log; this is expected for spoken lines, whispers, overlapping vocals or text that does not match the audio.
- **The whole file has no word tags.** The lyric may have been aligned as line-only, or the file may be a `.original.lrc` or an old file from another program. Check the main `.lrc`.
- **Words are consistently late/early.** Use the player's lyrics delay if it is a playback offset; if the file itself is wrong, edit the word times. A global delay in the file can be fixed with a script, but LyricLoom has no "shift all" button.
- **Timing drifts within a line.** This usually means the lyric version differs from the audio edit. Reprocess the exact file.
- **The last word stays lit too long.** LyricLoom's `trim` stage ends the last word where the isolated vocal goes quiet. If the vocal stem is noisy or the word is whispered, the trim may not find a quiet gap. Fix the end time by hand.
- **A line is tinted orange.** It is below the confidence threshold. Listen, then edit or accept it. `#review` lists zero-based line numbers.

## Backups

The main `.lrc` is backed up before every replacement:

```text
song.lrc      -> song.lrc.bak
song.lrc      -> song.lrc.bak1   (if .bak exists)
song.lrc      -> song.lrc.bak2   (if .bak1 exists)
```

Restore:

1. Close LyricLoom and any player using the file.
2. Move the current `.lrc` aside.
3. Rename the desired `.lrc.bak*` to `.lrc`.
4. Reopen the song.

`.original.lrc` is the official source text, not a backup of your edited timing. `.japanese.lrc` and `.romaji.lrc` are script variants and are overwritten without `.bak` files. Keep your own copies before experimenting.

## Logs and diagnostics

### What to include in a bug report

- Product: LyricLoom app, Starry Karaoke plugin or both. Use the product choice in the bug template.
- LyricLoom version (`lyricloom --version`) and/or plugin version.
- Operating system and version.
- Installer or portable / source or pipx, and installed or portable MusicBee for the plugin.
- For the app, the **Help > Diagnostics…** text, with personal paths redacted if you prefer.
- For the plugin, the **Diagnostics** text from its settings or window menu.
- The per-track `log.txt` around the failure, with personal paths redacted.
- Whether the file plays in another player.
- The lyric source shown in the table, if the track completed.
- For GPU/WSL problems, the output of the WSL check commands in
  [docs/wsl-rocm.md](wsl-rocm.md#8-verify).

Do not attach copyrighted audio or full lyrics unless you have the right to share them. A short error
excerpt is enough. The diagnostics texts never contain the AssemblyAI key or lyric text.

### Log locations

| Log | Path |
|---|---|
| App | `%LOCALAPPDATA%\LyricLoom\logs\app.log` (Windows) or `~/.local/share/lyricloom/logs/app.log` (Linux); rotates at about 1 MB |
| Per-track | `%LOCALAPPDATA%\LyricLoom\work\<hash>\log.txt` (Windows) or `~/.local/share/lyricloom/work/<hash>/log.txt` (Linux) |
| Whisper output | `work/<hash>/whisper*.json` |
| AssemblyAI response | `work/<hash>/assemblyai*.json` |
| MusicBee plugin | `%APPDATA%\MusicBee\Plugins\mb_StarryKaraoke.log` next to the plugin DLL, or MusicBee's persistent storage folder when the Plugins folder is not writable; rotates at about 1 MB |

`lyricloom doctor` does not write a log; it prints to the terminal. Copy its output into the report.
The app log does not replace the per-track log: use the track log for a stage failure and the app log
for queue, setup, update or window-level problems.

For privacy details, see [docs/privacy.md](privacy.md).
