# Use LyricLoom with MusicBee

LyricLoom does not need MusicBee. The built-in player is enough to check a song, watch the word-by-word highlight and fix timings. MusicBee is for people who want karaoke inside their normal music player, with the separate **Starry Karaoke** plugin.

This page covers both setups:

- [Option A: the built-in player (no MusicBee)](#option-a-the-built-in-player-no-musicbee)
- [Option B: MusicBee + Starry Karaoke](#option-b-musicbee--starry-karaoke)
- [How the plugin finds the .lrc](#how-the-plugin-finds-the-lrc)
- [Word-by-word behavior](#word-by-word-behavior)
- [Troubleshooting](#troubleshooting)

## Option A: the built-in player (no MusicBee)

Use this if you do not use MusicBee. LyricLoom has two built-in views:

- the compact player and word editor in the main window;
- a full-screen **Karaoke** window with the starry-night theme.

1. Process a song in LyricLoom.
2. Select the track in the library table.
3. Press **Play** (or **Space**) for the compact player, or click **Karaoke** (**Ctrl+K**) for the full-screen view.
4. In the Karaoke window:
   - **Space** plays or pauses.
   - **←/→** seek 5 seconds.
   - **↑/↓** change volume.
   - **N/P** move to the next or previous track.
   - **F11** toggles fullscreen; **Esc** leaves fullscreen or closes the window.
   - The current line is lit word by word, with the next line dimmed below it.
   - The **Script** list chooses the main `.lrc`, Japanese text or romaji. The main `.lrc` follows the script chosen in Settings.
5. The karaoke window starts at the main player's position. **Vocals only** switches playback to the cached isolated vocal stem, or to the kept `*.vocals.flac` when the work cache was cleared. If neither exists, the switch is disabled.
6. In the main window, double-click a line to jump to it, or press **Play line** to hear one line and stop at its end. Low-confidence lines are tinted orange; select a word, use the nudge buttons, then **Save**. **Accept line** / **Accept all** clear review flags; **Ctrl+Z** and **Ctrl+Y** undo and redo edits.

The Karaoke window uses the normal Qt media backend, so it depends on the codecs available on your system. On Linux, that means GStreamer plugins; see [docs/install-linux.md](install-linux.md#the-app-opens-but-there-is-no-sound). It does not need MusicBee, a browser, or an account.

## Option B: MusicBee + Starry Karaoke

**Starry Karaoke** is a separate MusicBee plugin with its own repository and its own MIT license:

<https://github.com/nishizumi-maho/MusicBee-StarryKaraoke>

It is not bundled with LyricLoom and is not covered by LyricLoom's GPL license. LyricLoom's job is to write the enhanced `.lrc`; the plugin's job is to display it.

### 1. Install MusicBee

Install MusicBee from its official website, or use the portable version if you prefer. Start it once so it creates its settings and plugin folders.

MusicBee is a 32-bit Windows application. The plugin targets .NET Framework 4.8, which is included in Windows 10 and Windows 11. If your Windows installation is missing it, install .NET Framework 4.8 from Microsoft before using the plugin.

### 2. Install the Starry Karaoke plugin

1. Close MusicBee.
2. Open the plugin's [Releases page](https://github.com/nishizumi-maho/MusicBee-StarryKaraoke/releases).
3. Download the latest release `.zip`.
4. Extract the ZIP.
5. Copy the **contents** of the extracted folder into MusicBee's Plugins folder:
   - Installed MusicBee: `%APPDATA%\MusicBee\Plugins`
   - Portable MusicBee: `<MusicBee folder>\Plugins`
6. Start MusicBee.

The release contains `mb_StarryKaraoke.dll`, the romaji support DLLs, `RomajiLyrics\IpaDic`, and a `StarryKaraoke` documentation folder. Copy them as they are; do not rename the DLLs or the `RomajiLyrics` folder.

If Windows marks the downloaded DLLs as blocked, open the file properties and choose **Unblock** before starting MusicBee. This is a common reason a plugin does not appear.

### 3. Open the karaoke window

In MusicBee, choose **View > Starry Karaoke**. The window opens for the currently playing track.

Useful controls from the plugin's README:

- **F11** or double-click toggles fullscreen.
- **Esc** leaves fullscreen.
- **Right-click** opens the menu for fullscreen, Japanese mode, *Record song video...* and *Settings...*.
- Settings are also under **Preferences > Plugins > Starry Karaoke > Configure**.

The plugin remembers whether the window was open when MusicBee closed cleanly.

### 4. Play a LyricLoom song

1. Play the audio file that has LyricLoom's `.lrc` next to it.
2. Open **View > Starry Karaoke**.
3. The plugin reads the lyrics MusicBee has for the song, or the adjacent `.lrc` when it has better timing. See [How the plugin finds the .lrc](#how-the-plugin-finds-the-lrc).
4. The current line lights up word by word. The previous and next lines are dimmed around it.

There is no "file picker" in the plugin. It follows MusicBee's now-playing track, so the `.lrc` must have the same base name as the audio file and live in the same folder:

```text
D:\Music\Artist\Album\01 - Song.flac
D:\Music\Artist\Album\01 - Song.lrc
```

LyricLoom writes exactly that layout. The `.original.lrc`, `.japanese.lrc` and `.romaji.lrc` files are extra copies for reference or for a different script; the plugin reads the main `.lrc`.

If another program should send the song to LyricLoom for processing, run `LyricLoom.exe --process "<file>"`. This queues the file in the running LyricLoom window without taking focus. See [docs/command-line.md](command-line.md).

## How the plugin finds the .lrc

The plugin's priority is:

1. MusicBee's own lyrics for the now-playing track, if they have line timing.
2. The `.lrc` next to the audio file, if it has timing.
3. MusicBee's downloaded lyrics, if the first two are unusable.

Within that, word timing wins over line-only timing:

- If the adjacent `.lrc` has `<mm:ss.xx>` word tags and MusicBee's lyrics do not, the plugin uses the adjacent file.
- If MusicBee's lyrics already have word timing, the plugin uses MusicBee's copy even when an adjacent `.lrc` exists.
- If both are line-only, the plugin can still show a swept highlight, but it cannot highlight individual words accurately.

This matters when MusicBee has cached an older lyric for a track. If the plugin shows the wrong text or only line-level timing after you reprocessed the song, update or clear MusicBee's lyrics for that track. In MusicBee, open the lyrics editor for the track and replace/remove the stored lyrics, or use **Tools > Advanced > Rescan Files** after changing the file. The exact menu names vary slightly between MusicBee versions.

A simple check: open the `.lrc` in a text editor. If it contains tags like `<00:22.98>`, the plugin can highlight words. If it only has `[00:22.98]` line tags, it cannot.

## Word-by-word behavior

LyricLoom writes enhanced LRC:

```lrc
[00:22.98]<00:22.98>言<00:23.10>葉<00:23.30>が<00:23.50>人<00:24.05>を<00:24.30>結<00:24.62>い<00:24.90>つ<00:25.12>け<00:25.30>る<00:25.62>
```

- The plugin turns each `<...>` segment gold as playback reaches it.
- A final `<...>` with no text marks the end of the last word, so the last word does not stay lit through the next instrumental break.
- If a file has no word tags, the plugin sweeps across the line over an estimated duration. That is a fallback, not real word timing.
- Japanese text is displayed without inserted spaces. LyricLoom segments Japanese with MeCab and keeps the original text in `.japanese.lrc`; the `.romaji.lrc` copy uses spaces between romanized segments.
- If the main `.lrc` is written in romaji, the plugin sees Latin text and will not apply its Japanese romaji mode. If you want the plugin's Japanese display options, set LyricLoom's Japanese script to **Japanese: 日本語** and let the plugin romanize.

### Japanese modes in the plugin

The plugin's right-click menu and settings offer:

- romaji only;
- Japanese with romaji below it;
- Japanese only.

The plugin has its own romaji engine and IPADic dictionary. It does not need LyricLoom's `.romaji.lrc` to show romaji, but it can only apply the mode when the lyric text is Japanese. Choose the mode that matches how you want the main `.lrc` written.

### Lyrics delay

If the highlight is consistently early or late, use the plugin's **Lyrics delay (ms)** setting. Positive values show the lyrics later. This changes only the plugin display; it does not rewrite the `.lrc`. If only one song is off, fix it in LyricLoom instead of changing the global delay.

## Troubleshooting

### Starry Karaoke is not in the View menu

- Check that `mb_StarryKaraoke.dll` is directly in the Plugins folder, not in a nested `StarryKaraoke` subfolder. The release ZIP contains a documentation subfolder named `StarryKaraoke`; do not confuse it with the DLL location.
- Use the correct Plugins folder: `%APPDATA%\MusicBee\Plugins` for the installed version, `<MusicBee folder>\Plugins` for portable.
- Close MusicBee completely before copying files, then start it again.
- Right-click each DLL, choose **Properties**, and click **Unblock** if Windows blocked it.
- Check that .NET Framework 4.8 is available.
- Look at MusicBee's plugin error message and at the plugin log (below).

### The window opens but says "no synced lyrics"

- There is no `.lrc` next to the audio, or it has no `[mm:ss.xx]` line tags.
- Process the song in LyricLoom first.
- Check that the `.lrc` base name matches the audio base name exactly. `01 - Song.flac` needs `01 - Song.lrc`.
- If MusicBee has an old lyric cached, clear/replace it.
- A `.lrc` created by another program may use a format the plugin cannot parse. LyricLoom's output is the tested format.

### The lyrics show but only sweep across the line

The file has line timing but no word tags. Reprocess it with LyricLoom, or check that you are not looking at an old `.lrc.bak` or a different script copy. The main `.lrc` should contain `<mm:ss.xx>` tags.

### The wrong lyric version appears

MusicBee's own word-timed lyrics take priority over the adjacent `.lrc`. Clear MusicBee's stored lyrics for that track, or update them to the LyricLoom file. This is especially common after editing a `.lrc` while MusicBee was running.

### The highlight drifts later through the song

A constant offset is best fixed with the plugin's **Lyrics delay** setting. A drift that grows over time usually means the lyric was timed for a different edit or remaster. Reprocess the exact audio file; LyricLoom aligns against that file's vocals, not against a different release.

### Japanese text shows boxes or the wrong script

- Boxes are usually a font problem in the plugin settings. Choose a font with Japanese glyphs.
- If the window shows romaji but you expected Japanese, check the plugin's Japanese mode.
- If the main `.lrc` is romaji and you want the plugin's Japanese mode, change LyricLoom's script preference to Japanese and let it rewrite the `.lrc` files. The `.japanese.lrc` and `.romaji.lrc` copies are kept.

### Video recording fails

*Record song video...* is a Starry Karaoke feature, not a LyricLoom feature. It needs `ffmpeg.exe` in the Plugins folder, on `PATH`, installed with `winget install Gyan.FFmpeg`, or set explicitly in the plugin settings. Video export is unrelated to lyric timing.

### Where the plugin log is

Starry Karaoke writes `mb_StarryKaraoke.log` in MusicBee's persistent storage folder, usually:

```text
%APPDATA%\MusicBee\mb_StarryKaraoke.log
```

For the portable build, the storage folder is beside the MusicBee executable. The log records startup, plugin loading, lyrics loading and recording errors.

### Where to report a plugin bug

The plugin is a separate project. Report plugin issues at:

<https://github.com/nishizumi-maho/MusicBee-StarryKaraoke/issues>

Include the MusicBee version, plugin version, Windows version, whether MusicBee is installed or portable, and the relevant part of `mb_StarryKaraoke.log`. Do not attach copyrighted lyrics unless you have the right to share them.

For LyricLoom issues (no `.lrc`, wrong timing that is present in the file itself), see [docs/troubleshooting.md](troubleshooting.md).
