# Starry Karaoke for MusicBee

A karaoke window for MusicBee with a starry night sky. The current line lights up word by word in
gold, with a soft edge and a glow. Japanese lyrics can be shown as romaji.

## Features

- Word-by-word lyrics, with a soft gold edge, glow, line fades and smooth scrolling.
- Japanese mode: romaji only, Japanese with romaji below it, or Japanese only.
- Twinkling stars, an optional comet passing by and a small burst of stars when a line ends.
- Six colour themes: Starry, Aurora, Sakura, Neon, Sunset and Snow, with an optional random theme
  for each song. The sky always stays a starfield.
- **Party mode:** fullscreen when playback starts, auto-hidden cursor, display kept awake, the next
  song shown near the end, and a thank-you message at the end.
- **Practice tools:** click a lyric line to seek to it, `[` and `]` to nudge the lyric delay, loop
  the current line or a short section, and volume/mute controls in the transport bar.
- **Screenshot:** `F12` saves a PNG of the current frame (and copies it to the clipboard).
- **Video recording:** renders the whole song, with the lyrics and the audio, to an MP4 file.

## Use

- **View > Starry Karaoke** opens and closes the window.
- **F11** or a double-click toggles fullscreen, and **Esc** leaves it.
- **Right-click** opens a menu with fullscreen, the Japanese mode, loop, screenshot, *Record song
  video...* and *Settings...*.
- Keyboard:
  - **Space** play/pause, **←/→** seek 10 seconds, **P** skip the intro;
  - **L** loop the current line, **Shift+L** loop the current section;
  - **[** and **]** move the lyric delay by 100 ms, **Ctrl+0** resets it;
  - **M** mute, **F12** save a screenshot.
- The transport bar fades in near the bottom of the window and has play/pause, previous/next,
  ±10 seconds, seek, volume and mute.
- The settings are also under *Preferences > Plugins > Starry Karaoke > Configure*. They cover:
  - font, text size and colours;
  - theme presets and random theme per song;
  - stars and how many, and the passing comet;
  - line bursts and glow;
  - the current line growing;
  - transition speed;
  - lyrics delay;
  - title and progress bar;
  - party mode and the next-song line;
  - the instrumental intro;
  - video resolution, frame rate and the ffmpeg path.

## Lyrics

The plugin plays the lyrics MusicBee has for the song. If the `.lrc` next to the audio file has word
timing (`<mm:ss.xx>`, as LYRICS BOCA writes it) and MusicBee's copy does not, the plugin uses that
`.lrc`. Lyrics timed only per line are swept across each line over an estimated time.

The parser also handles multiple timestamps per line, `[offset:]`, full-width characters and a
trailing word tag followed by a space.

## Themes

The theme presets only change the palette: background, unlit and lit lyrics, glow, title and the
progress bar. Choosing a preset copies its colours into the normal colour fields; editing a colour
switches the preset to *Custom*, and *Random theme for each song* can still vary the palette between
songs.

## Video recording

*Record song video...* in the window's right-click menu (or *Tools > Starry Karaoke: record song
video*) asks where to save and renders the song offline, frame by frame, outside MusicBee. The
recording needs `ffmpeg.exe`: either in the Plugins folder, on `PATH`, installed with
`winget install Gyan.FFmpeg`, or set explicitly in the settings.

The settings control the resolution, the frame rate, and whether the recording starts at the intro
or right at the first lyric. The video uses the same stars, themes and lyric layout as the window.

## Install

1. Close MusicBee.
2. Copy the contents of the release zip into the Plugins folder (`%APPDATA%\MusicBee\Plugins`, or
   `<MusicBee>\Plugins` for the portable version).
3. Start MusicBee.

`RomajiCore.dll`, `LibNMeCab.dll` and `RomajiLyrics\IpaDic` are shared with Desktop Lyrics (romaji
fork). If they are already there, copying them over is harmless.

The plugin targets .NET Framework 4.8, which is built into Windows 10 and 11.

## Build

`.\build.ps1` runs the tests, builds the plugin and writes `dist\MusicBee-StarryKaraoke-<version>.zip`.
It needs the .NET SDK and builds for .NET Framework 4.8.

## License

MIT — see [LICENSE](LICENSE).

## Third-party components

NMeCab, IPADic and RomajiCore keep their own licenses, included in the release zip under
`StarryKaraoke\licenses` and in the [licenses](licenses) folder.
