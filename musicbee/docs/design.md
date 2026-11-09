# Starry Karaoke: MusicBee plugin (design)

A MusicBee plugin, independent of Desktop Lyrics. It has its own project, repository and DLL
(`mb_StarryKaraoke.dll`) and does not touch Desktop Lyrics or the Lyrics Panel (BETA). The
StarryKaraoke.Recorder project produces the offscreen video recorder.

## What it does

- **Window:** opens under *View > Starry Karaoke*. It is a normal resizable window, with F11 or
  double-click for fullscreen and Esc to leave it. Position, size and the last monitor are saved.
- **Look:** a night-sky gradient with twinkling stars, an optional comet passing by and a small
  burst of stars when a line ends.
  - At the top, "✦ title — artist ✦".
  - The current line in the middle, with the previous and next lines dimmed above and below.
  - `♪ ♪ ♪` pulsing during instrumental breaks and a countdown before the first line.
  - A gold progress bar at the bottom.
  - Six colour themes (Starry, Aurora, Sakura, Neon, Sunset, Snow), optional random theme per song.
    Themes only change the palette: the background always stays a starfield.
- **Lyrics:** the ones MusicBee loads (`NowPlaying_GetLyrics`), through its own LRC parser:
  - simple LRC and multiple timestamps per line;
  - `[offset:]`;
  - LRC with per-word timing (`<mm:ss.xx>`, as LyricLoom writes it), lighting up word by word;
  - without per-word timing, the highlight sweeps across each line over an estimated time.
- **Sidecars:** the `.lrc` next to the audio file, and the `.japanese.lrc` / `.romaji.lrc` variants,
  are used when they have better timing than MusicBee's copy. A `FileSystemWatcher` on the playing
  song's folder reloads when a sidecar changes; it also runs while the window is closed when
  auto-open is on.
- **Romaji:** uses RomajiCore with NMeCab, the same engine as Desktop Lyrics, and the dictionary
  already in `Plugins\RomajiLyrics\IpaDic`. The romaji follows the word timing.
- **Japanese:** a setting with three options: romaji only, Japanese with romaji below, or Japanese
  only.
- **Practice:** click a line to seek to it; `[`/`]` nudge this song's delay (saved automatically);
  `Ctrl+0` resets it; `L` loops the current line, `Shift+L` loops a short section; volume and mute
  live in the transport bar.
- **Party mode:** starts in fullscreen when playback starts, hides the cursor after a moment, keeps
  the display awake, shows the next song during the last seconds and a thank-you message at the
  end. When playback stops, a setting keeps fullscreen, leaves it, hides the window or closes it.
- **Auto-open:** off, word-timed only, or any synced lyrics. A song without the required lyrics is
  rechecked after 1.5 and 4 seconds, then the configured unsupported-song action (keep, hide or
  close) is applied. A window closed by hand stays closed for that song. Automatic opens only take
  focus when "Bring the window to the front" is on.
- **LyricLoom:** sends `LyricLoom.exe --process "<file>"` to the running copy or starts it. The
  plugin makes no network request of its own. A per-song guard suppresses a second launch within
  ten seconds, and the window shows a waiting status until the sidecar arrives or the song changes.
- **Screenshot:** F12 renders the current window to a PNG in `Pictures\Starry Karaoke` and copies
  it to the clipboard.
- **Video recording:** a separate process renders every frame offline with the same scene and muxes
  the song's own audio; see below.
- **Diagnostics:** version/path report plus the log location, with Copy and Open log folder. The
  report never contains lyrics or unrelated paths.

## Rendering

`KaraokeScene` draws three layers: Sky, Glow (blurred by the window) and Text. FormattedText and
gradient brushes are cached and rebuilt only when the text, size, theme, DPI or loop range changes.

- **Soft edge:** the gold fill advances with a feathered edge (gradient mask) and a glow, instead of
  a hard cut. The edge is cached per quarter pixel, so it steps by at most 0.25 px and is never more
  than 0.125 px from its exact position.
- **Line-change fade:** the incoming line brightens and the outgoing one dims with the same eased
  scroll progress (about 0.4 s at the default speed).
- **Current line grows:** the sung line grows to about 108% while it glides into the centre, and
  returns to normal size when it leaves.
- **Smooth scrolling:** a time-driven `smootherstep` path eases each line to the centre with zero
  velocity and acceleration at both ends. Only a real discontinuity (seek, resize, font change,
  new song) starts a residual, which a critically damped spring removes in about 0.35 s without
  overshooting.
- **Line bursts:** a short, deterministic ring of small stars appears after each line ends.

The window sets `KaraokeScene.PixelsPerDip` from `VisualTreeHelper.GetDpi(this)` when it loads, on
`DpiChanged` and when it moves to another monitor. FormattedText therefore keeps crisp glyphs on a
scaled display. The recorder and the Preview tool leave it at 1.0 because they render offscreen at
96 DPI.

`FrameRatePolicy` gates the rendering callback: a hidden, minimised or fully covered window does no
scene work and stops the player poll timer; a paused song ticks at a slow exact divisor; a playing
song renders at an integer divisor of the window monitor's refresh rate (Match display, Half
refresh or Third refresh; Match display is the default). Frame time comes from
`RenderingEventArgs.RenderingTime`, so a 120 or 144 Hz display runs at its own rate rather than a
fixed 60. The plugin never changes WPF's process-wide `Timeline.DesiredFrameRateProperty`, so it
cannot slow down other WPF plugins in MusicBee.

## Auto-open and the sidecar watcher

`AutoOpenRule` is a plain decision table, free of WPF and MusicBee: the setting, the lyrics kind
(none, line-timed, word-timed), whether playback is running, whether the window exists/is visible,
whether the user dismissed it for this song, and the unsupported-song action. `DecideForSidecar`
applies the same table when a sidecar for the playing song appears; unsupported songs never change
the window from a background sidecar event.

The plugin keeps one `SidecarWatcher` for the playing song while the window is open, and also while
it is closed when auto-open is on. Track changes dispose it before the next song's watcher is
created. The watcher's callback reads the new sidecar's lyrics kind and the live play state on its
timer thread, then marshals the decision to MusicBee's UI thread: an auto-open uses
`AutoOpenFocus`; an existing hidden window is shown; an existing visible window just reloads its
lyrics.

## LyricLoom integration

`LyricLoomLocator` finds the executable in this order: the configured path, `HKCU\Software\LyricLoom`
(`Executable`, then `InstallPath\LyricLoom.exe`), `%LOCALAPPDATA%\Programs\LyricLoom\LyricLoom.exe`,
then the Program Files folder. `LyricLoomLauncher` starts it with `UseShellExecute =
false`, a quoted path and no window; it validates that the path has no quote.

`LyricLoomRequestGuard` remembers the last launch time per song and refuses a second launch within
ten seconds. A failed launch forgets the entry so the user can retry immediately. The window shows
`Sent to LyricLoom — the lyrics appear here when they are ready`; the status is cleared when a
sidecar for that song arrives or the track changes. The plugin itself performs no network access;
the download page is opened only after the user confirms the question.

## Settings and per-song data

Settings live in `mb_StarryKaraoke.xml` in MusicBee's persistent storage folder. Unknown enum values
and malformed numeric fields are repaired before deserialization, so one bad field does not discard
the rest. A file that cannot be read is kept as `*.bad-<timestamp>` and reported instead of being
silently overwritten. Saves use a temporary file and `File.Replace` (with a copy/move fallback).

Per-song lyric delays live in `mb_StarryKaraoke.offsets.json`, written atomically and keyed by the
song's URL. They are separate from `Settings.LyricsOffsetMs`, which remains the base delay for every
song. Deleting the plugin through MusicBee removes the settings, their backups, the offsets and the
log.

## Video recording

`StarryKaraoke.Recorder.exe` renders the whole song in contiguous segments on several STA threads.
Each segment is encoded by ffmpeg into a part file; the parts are joined without re-encoding and the
song's audio is muxed in, then the finished file is committed atomically.

- **ffmpeg discovery** (plugin side): the explicit setting, the ffmpeg bundled with an installed
  LyricLoom (`_internal\imageio_ffmpeg\binaries` or `imageio_ffmpeg\binaries`), then `PATH`.
- **Inputs:** the plugin writes the lyrics and settings into a per-run
  `%TEMP%\StarryKaraoke\rec-<guid>` folder and passes those paths to the recorder. The recorder
  deletes its owned copies after reading them. The plugin and the recorder both sweep stale `rec-*`
  folders older than 24 hours at start-up; nothing else in `%TEMP%` is touched.
- **Output safety:** the recorder compares canonical paths (symlinks/junctions and 8.3 names
  included) so the output can never be the audio, the lyrics, the settings or ffmpeg. ffmpeg writes
  a unique partial file in the target folder; the target is replaced only after the new file is
  complete, with the old target kept as a backup until the swap succeeds.
- **Cancellation:** a job object owns the ffmpeg processes, so cancel and timeout kill the whole
  tree; a forced close cannot leave ffmpeg running.

## Diagnostics

`DiagnosticsReport.Build` contains the plugin version, MusicBee version and API revision, the romaji
dictionary path and status, ffmpeg path and version, LyricLoom path and the log path. It never
contains lyrics. The log `mb_StarryKaraoke.log` is written next to the plugin DLL and falls back to
MusicBee's persistent storage folder; it rotates at 1 MB to `.old`. The `Safe` helpers run every
window callback and notification through one exception handler, log the error and show one message
instead of letting an exception escape into MusicBee.

## How it is built

- .NET Framework 4.8, like Desktop Lyrics. MusicBee is a 32-bit process; the recorder builds AnyCPU
  and prefers 64-bit so ffmpeg and WPF have room.
- The window is **WPF**, which draws with hardware acceleration. Glow (BlurEffect), a gradient
  opacity mask, scale and fade run smoothly at the display's refresh rate, even in fullscreen.
- RomajiCore is included as a copy in `external/RomajiCore`, so the repository stays self-contained.
- Unit tests (xunit) cover the parser, the per-character timings, the per-word romaji, the theme
  presets, auto-open and sidecar decisions, the LyricLoom guard, the recorder's output safety and
  temp sweep, and the window controls.
- `build.ps1` runs the tests, builds the plugin and recorder, and produces the zip with contents
  ready to go into the Plugins folder.
