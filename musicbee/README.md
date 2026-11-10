# Starry Karaoke for MusicBee

A karaoke window for MusicBee with a starry night sky. The current line lights up word by word in
gold, with a soft edge and a glow. Japanese lyrics can be shown as romaji.

Version 1.3.0. The plugin targets .NET Framework 4.8 (included in Windows 10 and 11) and runs inside
MusicBee; it does not need admin rights. It is MIT-licensed and ships from the same repository as
LyricLoom, under `musicbee/`.

## Install

Close MusicBee first.

**With the LyricLoom installer (Windows).** The LyricLoom setup has an optional task **Install the
Starry Karaoke plugin for MusicBee**. It appears and is checked by default when MusicBee is installed (an earlier choice is kept when you
reinstall or update),
and copies the plugin into `%APPDATA%\MusicBee\Plugins`.

**With the LyricLoom setup assistant.** Open **Help > Setup assistant… > MusicBee** and click
**Install Starry Karaoke** or **Update Starry Karaoke**. The page also has **Check again** and shows
whether MusicBee was found and which plugin version is installed. The assistant refuses while
MusicBee is running.

**With the release zip.** Download `StarryKaraoke-MusicBee-1.3.0.zip` from the LyricLoom
[Releases page](https://github.com/nishizumi-maho/lyricloom/releases), extract it, and copy its
**contents** into:

- `%APPDATA%\MusicBee\Plugins` for an installed MusicBee, or
- `<MusicBee folder>\Plugins` for the portable version.

Do not copy the zip's `StarryKaraoke` documentation folder into a nested `Plugins\StarryKaraoke`
folder: `mb_StarryKaraoke.dll` must sit directly in `Plugins`.

The plugin ships:

- `mb_StarryKaraoke.dll` and `StarryKaraoke.Recorder.exe`;
- `RomajiCore.dll`, `LibNMeCab.dll` and `RomajiLyrics\IpaDic`;
- a `StarryKaraoke` folder with this README, the license and third-party notices.

`RomajiCore.dll`, `LibNMeCab.dll` and `RomajiLyrics\IpaDic` are shared with Desktop Lyrics (romaji).
Copying them over is harmless. The LyricLoom installer replaces those files only with a newer
version, adds the dictionary only when it is missing, and never removes them when LyricLoom is
uninstalled.

If Windows marks the downloaded DLL blocked, open its properties and choose **Unblock**, then start
MusicBee.

## Use

- **View > Starry Karaoke** opens and closes the window.
- **F11** or a double-click toggles fullscreen; **Esc** leaves it.
- **Right-click** opens the window menu: fullscreen, monitor, topmost, skip intro, loop, screenshot,
  Japanese mode, LyricLoom, recording, settings, diagnostics and close.
- Keyboard:
  - **Space** play/pause, **←/→** seek 10 seconds, **P** skip the intro;
  - **L** loop the current line, **Shift+L** loop the current section;
  - **[** and **]** move this song's lyric delay by 100 ms, **Ctrl+0** resets it;
  - **M** mute, **F12** save a screenshot.
- The transport bar fades in near the bottom: play/pause, previous/next, ±10 seconds, seek, volume,
  mute, and this song's delay when it is not zero.
- The window remembers the per-song delay.

## Settings

Open **Preferences > Plugins > Starry Karaoke > Configure**, or right-click the window and choose
**Settings...**. Changes are previewed live; **OK** saves them and **Cancel** restores the previous
values. **Defaults** resets everything except the window's position, size and monitor choices.

**Window**

- **Open automatically:** *Off*, *When the song has word-timed lyrics* (the default, also for
  settings upgraded from 1.2), or *When it has any synced lyrics*.
- **On an unsupported song:** keep the window open, hide it, or close it.
- **Bring the window to the front when it opens automatically** (off by default, so a song starting
  in MusicBee never interrupts another application).
- **Fullscreen monitor:** the current monitor or a named display.
- **Keep on top in fullscreen.**

**LyricLoom**

- **LyricLoom.exe:** empty means automatic discovery; **Browse...** picks the file and **Test**
  reports the version.

**Theme and text**

- A theme preset (Starry, Aurora, Sakura, Neon, Sunset, Snow, or Custom) and **Random theme for each
  song**.
- Font, text size, and the Japanese display mode: *Romaji only*, *Japanese + romaji below*, or
  *Japanese only*.
- **Lyrics delay (ms, base):** the global delay added to every song's own delay.

**Colors and effects**

- Lit colour, glow head, current line (unlit), other lines, glow, background top/bottom and title.
- Stars on/off, the passing comet, the number of stars, a burst of stars at each line end, glow on lit
  lyrics, the current line growing, and the transition speed.
- **Show title**, **Show progress bar**, **Fullscreen shows only the lyrics**, and **Window frame rate**.
- **Window frame rate** is *Match display*, *Half refresh* or *Third refresh*, with the resulting Hz
  shown for the monitor the window is on. The default is *Match display*. Rendering stops when the
  window is hidden, minimised or completely covered by another window, and resumes when it is
  visible again.

**Party mode**

- **Fullscreen on play, hide cursor, keep the display awake.**
- **Show the next song near the end.**
- **When playback stops:** keep fullscreen, leave fullscreen, hide the window, or close it.

**Instrumental intro**

- **Skip the intro automatically on playback.**
- **Recorded video starts right at the lyrics.**
- **Start how long before the lyrics (s):** how much of the intro to keep.

**Recorded video**

- Resolution and video frame rate.
- **ffmpeg.exe:** empty means automatic; **Browse...** picks the file and **Test** reports the
  version.

**Diagnostics**

- A report with the plugin, MusicBee, romaji dictionary, ffmpeg and LyricLoom versions/paths and the
  log path. **Copy** puts it on the clipboard; **Open log folder** opens the log's folder. It never
  contains lyrics.

## Auto-open

With auto-open on, the plugin looks at the lyrics the window would show for the playing song and
opens the window when the setting accepts them. If the lyrics are not there yet (MusicBee or
LyricLoom may still be writing them), it checks again after 1.5 and 4 seconds before applying the
unsupported-song action.

The window is not reopened after the user closed it by hand for that song; a new song may open it
again, and opening it by hand clears the dismissal. **Bring the window to the front...** controls
whether an automatic open takes the keyboard focus.

While auto-open is on, the plugin watches the playing song's folder even when the window is closed.
When LyricLoom writes the sidecar for the playing song, the window opens (or is shown) by the same
rules: the song must be playing, the user must not have closed the window for that song, and the new
lyrics must match the auto-open setting. The watcher is disposed when the song changes.

## Fullscreen, monitor and frame rate

Fullscreen fills exactly one monitor, including the taskbar area. Choose the monitor in the settings
or in the window menu; an empty monitor setting means the window's current monitor. Fullscreen can
stay above other applications, and can show only the lyrics.

The frame rate is a separate setting: *Match display* (the default), *Half refresh* or *Third
refresh*. Every rate is an integer divisor of the monitor's refresh rate, so 144 Hz offers 144, 72
or 48 fps and never a juddering 60. A paused song ticks slowly at an exact divisor too. The plugin
does not change MusicBee's or other plugins' frame rate.

## Per-song lyrics delay

The base delay in the settings applies to every song. **[** and **]** change the playing song's own
delay in 100 ms steps and **Ctrl+0** resets it. The value is saved per song, never written into the
`.lrc`, and remains when the window is closed. MusicBee's own hotkey editor can bind the
**Tools > Starry Karaoke: lyrics delay** commands, so the delay can be adjusted without focusing the
karaoke window.

## Party mode

Party mode brings the window forward in fullscreen when playback starts, hides the cursor after a
moment, keeps the display awake while the song plays, shows the next song near the end and a
thank-you message after the last line. When playback stops, the **When playback stops** setting
decides whether the window stays fullscreen, leaves fullscreen, hides or closes.

## Hotkey-bindable commands

These are normal MusicBee menu commands. The **Tools** menu contains:

- **Starry Karaoke: record song video**
- **Starry Karaoke: make word-timed lyrics with LyricLoom**
- **Starry Karaoke: toggle window**
- **Starry Karaoke: toggle fullscreen**
- **Starry Karaoke: lyrics delay +100 ms**
- **Starry Karaoke: lyrics delay -100 ms**
- **Starry Karaoke: reset this song's lyrics delay**
- **Starry Karaoke: loop current line**

**View > Starry Karaoke** also opens the window. Use MusicBee's hotkey settings to bind any of them.

## Lyrics

The plugin shows the lyrics MusicBee has for the song. If the `.lrc` next to the audio file has word
timing (`<mm:ss.xx>`, as LyricLoom writes it) and MusicBee's copy does not, the plugin uses that
`.lrc`. If both have word timing, MusicBee's copy wins; clear or replace MusicBee's stored lyrics for
the track if it is stale. Japanese mode uses the `.japanese.lrc` or `.romaji.lrc` sidecar first for
the matching display mode.

The parser handles multiple timestamps per line, `[offset:]`, full-width characters and a trailing
word tag followed by a space. Lyrics with line timing only are swept across each line over an
estimated time.

While the window is open, it watches the playing song's folder and reloads when a sidecar changes,
so a file written by LyricLoom appears without reopening the window.

## LyricLoom integration

**Make word-timed lyrics with LyricLoom...** in the window menu (or **Tools > Starry Karaoke: make
word-timed lyrics with LyricLoom**) sends the playing local file to LyricLoom. The plugin starts
LyricLoom with `--process "<path>"` (or hands the command to the running copy) without a shell and
without taking the focus. LyricLoom then writes `<song>.lrc` and, for Japanese songs,
`<song>.japanese.lrc` and `<song>.romaji.lrc` next to the audio file.

When the command is sent from the window, it shows *Sent to LyricLoom — the lyrics appear here when
they are ready* until the sidecar arrives or the song changes. Clicking again for the same song
within 10 seconds does not launch a second copy.

The plugin itself makes **no network request**: it does not upload the song, check for updates,
collect telemetry or contact LyricLoom's servers. Only the local executable is started, and the
LyricLoom download page is opened in the browser only after the user says yes to that question.
LyricLoom's own network use (for example, the default update check or cloud transcription if the
user enables it) is described in LyricLoom's documentation.

A silent LyricLoom update never closes MusicBee. When MusicBee is running, that update skips the
plugin files; the next LyricLoom start explains this and offers to open the setup assistant's MusicBee
page, where you can update the plugin after closing MusicBee (the release ZIP works too).

## Video recording

**Record song video...** in the window menu (or **Tools > Starry Karaoke: record song video**) asks
where to save and renders the song offline, frame by frame, outside MusicBee. The video uses the same
stars, theme and lyric layout as the window, and the song's own audio. The song is never re-encoded
from a screen capture, so a slow frame or another window cannot spoil it.

The recording needs `ffmpeg.exe`. The plugin looks for it in this order:

1. the path in **Settings > Recorded video**;
2. the ffmpeg bundled with an installed LyricLoom;
3. `ffmpeg.exe` on `PATH` (for example after `winget install Gyan.FFmpeg`).

**Test** in the settings confirms which file would be used. The output is committed atomically: an
existing video is replaced only after the new file is complete, and the recorder refuses to write
over the song's audio or any other input. The lyrics and settings copies it uses are kept in a
per-run folder under `%TEMP%\StarryKaraoke\rec-<id>` and deleted after they are read; folders left by
a crash are removed on a later start after 24 hours.

The video settings control the resolution, frame rate, and whether the recording starts at the intro
or right at the first lyric.

## Diagnostics and the log

The Diagnostics section in the settings and **Diagnostics...** in the window menu show the same
report: plugin and MusicBee versions, the romaji dictionary, ffmpeg, LyricLoom and the log path.
**Copy** copies it for a bug report. It never includes lyrics.

The log is `mb_StarryKaraoke.log` next to the plugin DLL (normally
`%APPDATA%\MusicBee\Plugins\mb_StarryKaraoke.log`). If that folder is not writable, the plugin falls
back to MusicBee's persistent storage folder. The log is rotated at about 1 MB to
`mb_StarryKaraoke.log.old`, records start-up, lyrics loading, LyricLoom launches and recording
errors, and never contains lyrics text. **Open log folder** opens the location shown in the report.

## Uninstall

Remove the plugin through MusicBee's plugin settings, or delete `mb_StarryKaraoke.dll`,
`StarryKaraoke.Recorder.exe` and the `StarryKaraoke` documentation folder from the Plugins folder.
When MusicBee removes the plugin it calls its uninstall hook, which deletes:

- `mb_StarryKaraoke.xml`, its `.bak` and any `.bad-*` copies;
- `mb_StarryKaraoke.offsets.json` (the per-song delays);
- `mb_StarryKaraoke.log` and `.old`.

If you delete the files by hand, remove those files from MusicBee's data folder
(`%APPDATA%\MusicBee` for an installed MusicBee) yourself.

The shared `RomajiCore.dll`, `LibNMeCab.dll` and `RomajiLyrics\IpaDic` are left in place because
Desktop Lyrics uses them. The LyricLoom uninstaller removes the plugin files it installed but leaves
the shared files, the plugin settings and the log alone; remove those as described above. Temporary
recording folders under `%TEMP%\StarryKaraoke` are cleaned up automatically; you can delete the
folder by hand if you prefer.

## Build

`.\build.ps1` runs the tests, builds the plugin and recorder and writes
`dist\StarryKaraoke-MusicBee-<version>.zip`, which is the release asset. It needs the **.NET 8 SDK**
and builds for .NET Framework 4.8.

From the repository root the same checks are:

```powershell
dotnet test musicbee\tests\StarryKaraoke.Tests -c Release -nologo
dotnet build musicbee\src\StarryKaraoke.Recorder\StarryKaraoke.Recorder.csproj -c Release -nologo
```

## License

MIT — see `LICENSE.txt` next to this README in the release zip (or `LICENSE` in the repository).

## Third-party components

NMeCab, IPADic and RomajiCore keep their own licenses, included in the release zip under
`StarryKaraoke\licenses` and in the `licenses` folder of the repository.
