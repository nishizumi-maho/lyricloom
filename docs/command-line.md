# Command line

`LyricLoom.exe` can be started by another program, for example the Starry Karaoke MusicBee plugin.
The same options work with the source/Linux launchers that call the GUI (`lyricloom-app`,
`python -m lyricloom`, or a frozen `LyricLoom` binary).

```text
LyricLoom.exe --process <file> [<file> ...] [--redo]
LyricLoom.exe --open <file>
```

## One instance per user

Only one LyricLoom window runs per user profile. A second start hands its command line to the
running window and exits:

- a normal start with no options brings the existing window to the front;
- `--open` brings it to the front and selects the requested song;
- `--process` never takes focus away from the program that started it. The running window shows a
  status-bar message, changes its title and flashes its taskbar button instead.

The window and the second start talk through a local socket that is limited to the current Windows
user. Messages are small JSON objects; invalid or oversized messages are rejected. If no instance is
running, the new process becomes the window and handles its command line itself.

## `--process`

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

Unsupported or missing paths are ignored. The running window reports how many paths were ignored
and why (in the status bar and the app log); a command that only contains invalid paths does not
start a queue.

Add `--redo` to redo the word timing instead of a normal run:

```text
LyricLoom.exe --process "D:\Music\Artist\Album\01 - Song.flac" --redo
```

This is the same Redo path as the **Redo selected** button: it moves LyricLoom's word timing aside,
aligns it again using the cached vocals and transcript, and restores the previous `.lrc` if the run
fails or is cancelled. The official lyric (`.original.lrc`) is kept.

## `--open`

```text
LyricLoom.exe --open "D:\Music\Artist\Album\01 - Song.flac"
```

`--open` selects one existing audio file in the library without processing it. If the file is inside
the current library, it is selected there. If it is outside the library, LyricLoom switches the
library to that file's folder first, so the file can be shown in the table. Unlike `--process`,
`--open` brings the window to the front because the user asked to see the song.

`--open` cannot be combined with `--process` or `--redo`.

## MusicBee

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

## Internal worker mode

`--worker <name>` is how LyricLoom starts its own background stage processes. It is not a user
command and is unchanged by the options above.
