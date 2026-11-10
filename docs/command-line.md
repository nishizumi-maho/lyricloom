# Command line

There are two command lines:

- the **desktop app** (`LyricLoom.exe`, `lyricloom-app`, or `python -m lyricloom` with no engine
  subcommand) accepts the `--process` / `--open` options used by MusicBee and other programs;
- the **engine CLI** (`lyricloom`) runs `process`, `models`, `cache` and `doctor` without the GUI.

A source or pipx install provides both. The packaged Windows and Linux GUI builds are windowed
applications: they accept the desktop options but do not expose the engine console commands. Use the
app's **Help > Models…**, **Help > Diagnostics…** and the status bar there, or a source/pipx install
for the console.

## Desktop app options

```text
LyricLoom.exe --process <file> [<file> ...] [--redo]
LyricLoom.exe --open <file>
```

The same options work with `lyricloom-app`, `python -m lyricloom --process ...` or a frozen
`LyricLoom` binary.

### One instance per user

Only one LyricLoom window runs per user profile. A second start hands its command line to the
running window and exits:

- a normal start with no options brings the existing window to the front;
- `--open` brings it to the front and selects the requested song;
- `--process` never takes focus away from the program that started it. The running window shows a
  status-bar message, changes its title and flashes its taskbar button instead.

The window and the second start talk through a local socket limited to the current user. Messages
are small JSON objects; invalid or oversized messages are rejected. If no instance is running, the
new process becomes the window and handles its command line itself.

### `--process`

```text
LyricLoom.exe --process "D:\Music\Artist\Album\01 - Song.flac"
LyricLoom.exe --process "D:\Music\Album A" "D:\Music\Album B"
```

The files are added to the running queue, or a new queue starts when LyricLoom is idle. Folders are
scanned recursively for supported audio files. If no song is open in the player, the first queued
file is selected so its details are visible. `--process` does not bring the window to the front.

Supported extensions are `.flac`, `.mp3`, `.m4a`, `.ogg`, `.opus` and `.wav`. Every path is checked
before it is queued:

- the file or folder must exist;
- a file must have a supported audio extension.

Unsupported or missing paths are ignored. The running window reports how many paths were ignored and
why (in the status bar and the app log); a command that only contains invalid paths does not start a
queue.

Add `--redo` to redo the word timing instead of a normal run:

```text
LyricLoom.exe --process "D:\Music\Artist\Album\01 - Song.flac" --redo
```

This is the same redo path as **Redo selected**: it moves LyricLoom's word timing aside, aligns it
again using the cached vocals and transcript, and restores the previous `.lrc` if the run fails or
is cancelled. The official lyric (`.original.lrc`) is kept.

### `--open`

```text
LyricLoom.exe --open "D:\Music\Artist\Album\01 - Song.flac"
```

`--open` selects one existing audio file in the library without processing it. If the file is inside
the current library, it is selected there. If it is outside the library, LyricLoom switches the
library to that file's folder first, so the file can be shown in the table. Unlike `--process`,
`--open` brings the window to the front because the user asked to see the song.

`--open` cannot be combined with `--process` or `--redo`. `--redo` requires `--process`.

### MusicBee

The installer writes the installation location to the current user's registry so a plugin does not
have to guess it:

```text
HKEY_CURRENT_USER\Software\LyricLoom
    InstallPath   C:\Users\<user>\AppData\Local\Programs\LyricLoom
    Executable    C:\Users\<user>\AppData\Local\Programs\LyricLoom\LyricLoom.exe
```

The uninstaller removes the key. A plugin can then run:

```text
LyricLoom.exe --process "<path to the MusicBee track>"
```

and, when the user wants to review the result, `LyricLoom.exe --open "<path>"`.

## Engine CLI (source or pipx install)

The `lyricloom` command runs the same engine as the GUI without opening a window. It uses the
library selected in the app (or `~/Music` by default).

```text
lyricloom process <file-or-folder> [--force] [--stage STAGE] [--no-cloud]
lyricloom models <list|status|download|verify|repair|use|add> [...]
lyricloom cache [status|clean] [--max-gb N]
lyricloom doctor
lyricloom --version
```

### `lyricloom process`

```bash
lyricloom process "D:\Music\Artist\Album"
lyricloom process "D:\Music\Artist\Album\01 - Song.flac" --force
lyricloom process "D:\Music\Artist\Album" --stage align
lyricloom process "D:\Music\Artist\Album" --no-cloud
```

- The path must be inside the library selected in the app (or the default `~/Music`). Use
  `LYRICLOOM_DATA_DIR` for a test profile or change the library in the app.
- `--force` reprocesses tracks even when the same engine version already wrote them.
- `--stage` recomputes that stage and every stage after it. The choices are `probe`, `lyrics`,
  `separate`, `transcribe`, `align` and `write`.
- `--no-cloud` never uploads audio to AssemblyAI for this run, even when cloud transcription is
  enabled in Settings.
- A run prints one line per track. It exits **0** when every track is done, review or skipped,
  **1** when any track failed, and **2** on a usage error (including a path outside the library).

The engine CLI does not download a model while processing a song. If a model is missing, the track
fails with a message naming the model and the `lyricloom models download` command.

### `lyricloom models`

```bash
lyricloom models list
lyricloom models status
lyricloom models download all-defaults
lyricloom models download whisper-large-v3-turbo
lyricloom models verify whisper-large-v3
lyricloom models repair whisper-large-v3
lyricloom models use transcribe whisper-small
lyricloom models use transcribe whisper-medium --lang ja
lyricloom models add separate "D:\Models\my-vocals.ckpt" --label "My separator"
```

- `list` shows every model per stage with size, status, the languages that choose it and whether it
  is the catalog default.
- `status` is the shorter installation summary (`models` directory, whisper/separator/MMS/MTL,
  NLTK and ffmpeg).
- `download all-defaults` (or the alias `all`) fetches the default for every stage plus the NLTK
  data. A single id or an old short name (`whisper`, `separator`, `mms`, `mtl`, `nltk`) also works.
- `verify [id ...]` recomputes the full SHA-256; without ids it verifies the catalog and custom
  models.
- `repair <id>` deletes a catalog model's files, sidecar and partial download, then downloads them
  again. It refuses custom models.
- `use <stage> <id> [--lang CODE]` writes a default or per-language choice.
- `add <stage> <path|registry-name> [--label TEXT]` registers a custom model with its current size
  and SHA-256 (trust on first use). For vocal separation, a name from audio-separator's registry
  downloads that model when you add it.

The full catalog and choice rules are in [docs/models.md](models.md).

### `lyricloom cache`

```bash
lyricloom cache status
lyricloom cache clean --max-gb 20
```

`status` reports the number of track folders, their total size and the work-cache root. `clean`
deletes the oldest track caches first and never a track that is running. Without `--max-gb` it
removes the whole work cache. The kept vocal stems in the vocals folder are separate and are not
deleted.

### `lyricloom doctor`

`lyricloom doctor` prints the version, Python, data folder, library, vocals cache, models folder,
`whisper-cli` path, ffmpeg, separator/MMS/MTL readiness and whether PyTorch can see CUDA/ROCm. It
does not send anything anywhere and does not print the AssemblyAI key. On Windows it also prints the
WSL settings when WSL is enabled.

## Internal worker mode

`--worker <name>` is how LyricLoom starts its own background stage processes. It is not a user
command; do not run it by hand. The frozen build uses `LyricLoomWorker.exe` instead. See
[docs/architecture.md](architecture.md#worker-model).
