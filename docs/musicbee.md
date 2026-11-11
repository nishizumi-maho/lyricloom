# Use LyricLoom with MusicBee

LyricLoom does not need MusicBee. The built-in player is enough to check a song, watch the
word-by-word highlight and fix timings. MusicBee is for people who want karaoke inside their normal
music player, with the **Starry Karaoke** plugin.

This page covers both setups:

- [Option A: the built-in player (no MusicBee)](#option-a-the-built-in-player-no-musicbee)
- [Option B: MusicBee + Starry Karaoke](#option-b-musicbee--starry-karaoke)
- [How the plugin finds the .lrc](#how-the-plugin-finds-the-lrc)
- [Word-by-word behavior](#word-by-word-behavior)
- [Smooth motion and frame rate](#smooth-motion-and-frame-rate)
- [Troubleshooting](#troubleshooting)

## Option A: the built-in player (no MusicBee)

Use this if you do not use MusicBee. LyricLoom has two built-in views:

- the compact player and word editor in the main window;
- a full-screen **Karaoke** window with the starry-night theme.

1. Process a song in LyricLoom.
2. Select the track in the library table.
3. Press **Play** (or **Space**) for the compact player, or click **Karaoke** (**Ctrl+K**) for the
   full-screen view.
4. In the Karaoke window:
   - **Space** plays or pauses.
   - **←/→** seek 5 seconds.
   - **↑/↓** change volume.
   - **N/P** move to the next or previous track.
   - **F11** toggles fullscreen; **Esc** leaves fullscreen or closes the window.
   - The current line is lit word by word, with the next line dimmed below it.
   - The **Script** list chooses the main `.lrc`, Japanese text or romaji. The main `.lrc` follows
     the script chosen in Settings.
5. The karaoke window starts at the main player's position. **Vocals only** switches playback to the
   cached isolated vocal stem, or to the kept `*.vocals.flac` when the work cache was cleared. If
   neither exists, the switch is disabled.
6. In the main window, double-click a line to jump to it, or press **Play line** to hear one line and
   stop at its end. Low-confidence lines are tinted orange; select a word, use the nudge buttons,
   then **Save**. **Accept line** / **Accept all** clear review flags; **Ctrl+Z** and **Ctrl+Y**
   undo and redo edits.

The lyric column and the stars move on the same frame clock. **Settings > Smooth animation** offers
**Match display (default)**, **Half refresh** and **Third refresh**; every lower rate is an exact
integer divisor of the monitor refresh rate. The main window's compact player stops its timer while
nothing is playing.

The Karaoke window uses the normal Qt media backend, so it depends on the codecs available on your
system. On Linux, that means GStreamer plugins; see
[docs/install-linux.md](install-linux.md#the-app-opens-but-there-is-no-sound). It does not need
MusicBee, a browser or an account.

## Option B: MusicBee + Starry Karaoke

**Starry Karaoke** is the MusicBee plugin in this repository under
[`musicbee/`](../musicbee/README.md). It has its own **MIT license** and is not part of LyricLoom's
GPL code. LyricLoom writes the enhanced `.lrc`; the plugin displays it.

Version 1.3.0 targets .NET Framework 4.8, which is included in Windows 10 and Windows 11, and runs
inside MusicBee without administrator rights. It is bundled with LyricLoom's Windows build so the
setup assistant (and the installer's optional MusicBee task) can put it in place for you.

### 1. Install MusicBee

Install MusicBee from its official website, or use the portable version if you prefer. Start it once
so it creates its settings and plugin folders.

MusicBee is a 32-bit Windows application. If your Windows installation is missing .NET Framework 4.8,
install it from Microsoft before using the plugin.

### 2. Install the Starry Karaoke plugin

There are three equivalent ways:

- **The LyricLoom installer:** if MusicBee is detected, the optional **Install the Starry Karaoke
  plugin for MusicBee** task is offered and checked. It copies the plugin into
  `%APPDATA%\MusicBee\Plugins`.
- **The setup assistant:** open **Help > Setup assistant… > MusicBee** and click **Install Starry
  Karaoke** or **Update Starry Karaoke**. It refuses while MusicBee is running, replaces the
  plugin's own files, replaces the shared `RomajiCore.dll`/`LibNMeCab.dll` only when the bundled
  version is newer, and copies the `RomajiLyrics\IpaDic` dictionary only when it is missing.
- **The release ZIP:** download `StarryKaraoke-MusicBee-1.3.0.zip` from the
  [Releases page](https://github.com/nishizumi-maho/lyricloom/releases), extract it, and copy its
  **contents** into MusicBee's Plugins folder:
  - installed MusicBee: `%APPDATA%\MusicBee\Plugins`;
  - portable MusicBee: `<MusicBee folder>\Plugins`.

  `mb_StarryKaraoke.dll` must sit directly in `Plugins`, not in a nested `StarryKaraoke` folder.
  The ZIP also contains `StarryKaraoke.Recorder.exe`, the romaji support DLLs,
  `RomajiLyrics\IpaDic`, and a `StarryKaraoke` documentation folder. Do not rename the DLLs or the
  `RomajiLyrics` folder.

If Windows marks the downloaded DLLs as blocked, open the file properties and choose **Unblock**
before starting MusicBee. This is a common reason a plugin does not appear. Close MusicBee completely
before copying files, then start it again.

### 3. Open the karaoke window

In MusicBee, choose **View > Starry Karaoke**. The window opens for the currently playing track.

Useful controls:

- **F11** or double-click toggles fullscreen.
- **Esc** leaves fullscreen.
- **Right-click** opens the window menu for fullscreen, monitor, topmost, skip intro, loop,
  screenshot, Japanese mode, LyricLoom, recording, settings, diagnostics and close.
- **Space** plays or pauses; **←/→** seek 10 seconds; **P** skips the instrumental intro.
- **L** loops the current line; **Shift+L** loops the current section.
- **[** and **]** change this song's lyric delay by 100 ms; **Ctrl+0** resets it.
- **M** mutes; **F12** saves a screenshot.

Settings are also under **Preferences > Plugins > Starry Karaoke > Configure**. The plugin remembers
whether the window was open when MusicBee closed cleanly.

### 4. Play a LyricLoom song

1. Play the audio file that has LyricLoom's `.lrc` next to it.
2. Open **View > Starry Karaoke**.
3. The plugin reads the lyrics MusicBee has for the song, or the adjacent `.lrc` when it has better
   timing. See [How the plugin finds the .lrc](#how-the-plugin-finds-the-lrc).
4. The current line lights up word by word. The previous and next lines are dimmed around it.

There is no "file picker" in the plugin. It follows MusicBee's now-playing track, so the `.lrc` must
have the same base name as the audio file and live in the same folder:

```text
D:\Music\Artist\Album\01 - Song.flac
D:\Music\Artist\Album\01 - Song.lrc
```

LyricLoom writes exactly that layout. The `.original.lrc`, `.japanese.lrc` and `.romaji.lrc` files
are extra copies for reference or for a different script; the plugin reads the main `.lrc`.

### Auto-open

**Open automatically** defaults to **When the song has word-timed lyrics**. The other choices are
**Off** and **When it has any synced lyrics**. A song with word-timed lyrics therefore opens the
Starry Karaoke window by default; this also applies to settings upgraded from 1.2.

- **On an unsupported song:** keep the window open, hide it or close it.
- **Bring the window to the front when it opens automatically** is off by default, so a song starting
  in MusicBee does not interrupt another application.
- The window is not reopened after you close it by hand for that song. A new song may open it again,
  and opening it by hand clears the dismissal.
- While auto-open is on, the plugin watches the playing song's folder even when the window is closed.
  When LyricLoom writes the sidecar for the playing song, the window opens or is shown by the same
  rules: the song must be playing, you must not have closed the window for that song, and the new
  lyrics must match the auto-open setting. The watcher is disposed when the song changes.
- If the lyrics are not there yet (MusicBee or LyricLoom may still be writing them), the plugin
  checks again after 1.5 and 4 seconds before applying the unsupported-song action.

### LyricLoom integration

**Make word-timed lyrics with LyricLoom…** in the window menu (or **Tools > Starry Karaoke: make
word-timed lyrics with LyricLoom**) sends the playing local file to LyricLoom. The plugin starts
`LyricLoom.exe --process "<path>"` (or hands the command to the running copy) without a shell and
without taking the focus. LyricLoom then writes `<song>.lrc` and, for Japanese songs,
`<song>.japanese.lrc` and `<song>.romaji.lrc` next to the audio file.

When the command is sent from the window, it shows *Sent to LyricLoom — the lyrics appear here when
they are ready* until the sidecar arrives or the song changes. Clicking again for the same song
within 10 seconds does not launch a second copy.

If another program should send the song to LyricLoom for processing, run
`LyricLoom.exe --process "<file>"`. See [docs/command-line.md](command-line.md).

The plugin itself makes **no network request**: it does not upload the song, check for updates,
collect telemetry or contact LyricLoom's servers. Only the local executable is started, and the
LyricLoom download page is opened in the browser only after the user says yes to that question.
LyricLoom's own network use (for example, cloud transcription if the user enables it) is described
in LyricLoom's documentation.

## How the plugin finds the .lrc

The plugin's priority is:

1. MusicBee's own lyrics for the now-playing track, if they have line timing.
2. The `.lrc` next to the audio file, if it has timing.
3. MusicBee's downloaded lyrics, if the first two are unusable.

Within that, word timing wins over line-only timing:

- If the adjacent `.lrc` has `<mm:ss.xx>` word tags and MusicBee's lyrics do not, the plugin uses the
  adjacent file.
- If MusicBee's lyrics already have word timing, the plugin uses MusicBee's copy even when an
  adjacent `.lrc` exists.
- If both are line-only, the plugin can still show a swept highlight, but it cannot highlight
  individual words accurately.
- Japanese mode uses the `.japanese.lrc` or `.romaji.lrc` sidecar first for the matching display mode.

The parser handles multiple timestamps per line, `[offset:]`, full-width characters and a trailing
word tag followed by a space. While the window is open, it watches the playing song's folder and
reloads when a sidecar changes, so a file written by LyricLoom appears without reopening the window.

This matters when MusicBee has cached an older lyric for a track. If the plugin shows the wrong text
or only line-level timing after you reprocessed the song, update or clear MusicBee's lyrics for that
track. In MusicBee, open the lyrics editor for the track and replace/remove the stored lyrics, or use
**Tools > Advanced > Rescan Files** after changing the file. The exact menu names vary slightly
between MusicBee versions.

A simple check: open the `.lrc` in a text editor. If it contains tags like `<00:22.98>`, the plugin
can highlight words. If it only has `[00:22.98]` line tags, it cannot.

## Word-by-word behavior

LyricLoom writes enhanced LRC:

```lrc
[00:22.98]<00:22.98>This <00:23.10>is <00:23.30>a <00:23.50>synthetic <00:24.05>line<00:24.60>
```

- The plugin turns each `<...>` segment gold as playback reaches it.
- A final `<...>` with no text marks the end of the last word, so the last word does not stay lit
  through the next instrumental break.
- If a file has no word tags (lyrics synced per line, as LRCLIB and most players write them), the
  plugin estimates the sweep: it learns the song's pace from its own lines, spreads each line by sung
  syllables rather than letters, starts a moment after the line's time (a line time usually comes a
  little before the voice) and finishes before the next line. The LyricLoom app does the same. It is
  still an estimate, not real word timing; process the song with LyricLoom for word timing.
- Japanese text is displayed without inserted spaces. LyricLoom segments Japanese with MeCab and
  keeps the original text in `.japanese.lrc`; the `.romaji.lrc` copy uses spaces between romanized
  segments.
- If the main `.lrc` is written in romaji, the plugin sees Latin text and will not apply its Japanese
  romaji mode. If you want the plugin's Japanese display options, set LyricLoom's Japanese script to
  **Japanese: 日本語** and let the plugin romanize.

### Japanese modes in the plugin

The plugin's right-click menu and settings offer:

- romaji only;
- Japanese with romaji below it;
- Japanese only.

The plugin has its own romaji engine and IPADic dictionary. It does not need LyricLoom's
`.romaji.lrc` to show romaji, but it can only apply the mode when the lyric text is Japanese. Choose
the mode that matches how you want the main `.lrc` written.

## Smooth motion and frame rate

The plugin uses the same time-driven lyric motion as the app: a playback clock fed with timestamped
MusicBee samples, a gliding scroll path that settles without a jump, a gold sweep inside each word,
and eased line growth and dimming. A seek or a new song is absorbed without a visible jump.

**Settings > Effects > Window frame rate** offers:

- **Match display** (default);
- **Half refresh**;
- **Third refresh**.

The resulting Hz for the monitor the window is on is shown next to each choice. Every rate is an
integer divisor of the monitor's refresh rate, so 144 Hz offers 144, 72 or 48 fps and never a
juddering 60. A paused song ticks slowly at an exact divisor too. Rendering stops when the window is
hidden, minimised or completely covered by another window, and resumes when it is visible again. The
plugin does not change MusicBee's or other plugins' frame rate.

**Lyrics delay (ms, base)** applies to every song. **[** and **]** change the playing song's own
delay in 100 ms steps and **Ctrl+0** resets it. This changes the display only; it never rewrites the
`.lrc`. If only one song is off, fix it in LyricLoom instead of changing the global delay.

## Troubleshooting

### Starry Karaoke is not in the View menu

- Check that `mb_StarryKaraoke.dll` is directly in the Plugins folder, not in a nested
  `StarryKaraoke` subfolder. The release ZIP contains a documentation subfolder named
  `StarryKaraoke`; do not confuse it with the DLL location.
- Use the correct Plugins folder: `%APPDATA%\MusicBee\Plugins` for the installed version,
  `<MusicBee folder>\Plugins` for portable.
- Close MusicBee completely before copying files, then start it again.
- Right-click each DLL, choose **Properties**, and click **Unblock** if Windows blocked it.
- Check that .NET Framework 4.8 is available.
- Look at MusicBee's plugin error message and at the plugin log (below).

### The window opens but says "no synced lyrics"

- There is no `.lrc` next to the audio, or it has no `[mm:ss.xx]` line tags.
- Process the song in LyricLoom first.
- Check that the `.lrc` base name matches the audio base name exactly. `01 - Song.flac` needs
  `01 - Song.lrc`.
- If MusicBee has an old lyric cached, clear/replace it.
- A `.lrc` created by another program may use a format the plugin cannot parse. LyricLoom's output is
  the tested format.

### The lyrics show but only sweep across the line

The file has line timing but no word tags. Reprocess it with LyricLoom, or check that you are not
looking at an old `.lrc.bak` or a different script copy. The main `.lrc` should contain `<mm:ss.xx>`
tags.

### The wrong lyric version appears

MusicBee's own word-timed lyrics take priority over the adjacent `.lrc`. Clear MusicBee's stored
lyrics for that track, or update them to the LyricLoom file. This is especially common after editing
a `.lrc` while MusicBee was running.

### The highlight drifts later through the song

A constant offset is best fixed with the plugin's **Lyrics delay** setting. A drift that grows over
time usually means the lyric was timed for a different edit or remaster. Reprocess the exact audio
file; LyricLoom aligns against that file's vocals, not against a different release.

### Japanese text shows boxes or the wrong script

- Boxes are usually a font problem in the plugin settings. Choose a font with Japanese glyphs.
- If the window shows romaji but you expected Japanese, check the plugin's Japanese mode.
- If the main `.lrc` is romaji and you want the plugin's Japanese mode, change LyricLoom's script
  preference to Japanese and let it rewrite the `.lrc` files. The `.japanese.lrc` and `.romaji.lrc`
  copies are kept.

### Video recording fails

*Record song video...* is a Starry Karaoke feature. It needs `ffmpeg.exe`. The plugin looks for it in
this order:

1. the path in **Settings > Recorded video**;
2. the ffmpeg bundled with an installed LyricLoom;
3. `ffmpeg.exe` on `PATH` (for example after `winget install Gyan.FFmpeg`).

**Test** in the settings confirms which file would be used. The output is committed atomically: an
existing video is replaced only after the new file is complete, and the recorder refuses to write
over the song's audio or any other input. The lyrics and settings copies it uses are kept in a
per-run folder under `%TEMP%\StarryKaraoke\rec-<id>` and deleted after they are read; folders left by
a crash are removed on a later start after 24 hours.

### Where the plugin log is

Starry Karaoke writes `mb_StarryKaraoke.log` next to the plugin DLL, normally:

```text
%APPDATA%\MusicBee\Plugins\mb_StarryKaraoke.log
```

If that folder is not writable, it falls back to MusicBee's persistent storage folder
(`%APPDATA%\MusicBee` for an installed MusicBee, or the storage folder beside a portable MusicBee).
The log is rotated at about 1 MB to `.old`, records start-up, lyrics loading, LyricLoom launches and
recording errors, and never contains lyric text.

### Where to get diagnostics

Open **Preferences > Plugins > Starry Karaoke > Configure > Diagnostics** or **Diagnostics…** in the
window menu. The report shows the plugin, MusicBee, romaji dictionary, ffmpeg and LyricLoom
versions/paths plus the log path. **Copy** puts it on the clipboard; **Open log folder** opens the
folder. It never contains lyrics.

### Where to report a plugin bug

The plugin ships from this repository. Open an issue at:

<https://github.com/nishizumi-maho/lyricloom/issues>

Choose the Starry Karaoke product in the bug template and paste the plugin Diagnostics text. Include
the MusicBee version, plugin version, Windows version, whether MusicBee is installed or portable, and
the relevant part of `mb_StarryKaraoke.log`. Do not attach copyrighted lyrics unless you have the
right to share them.

For LyricLoom issues (no `.lrc`, wrong timing that is present in the file itself), see
[docs/troubleshooting.md](troubleshooting.md).

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
recording folders under `%TEMP%\StarryKaraoke` are cleaned up automatically; you can delete the folder
by hand if you prefer.
