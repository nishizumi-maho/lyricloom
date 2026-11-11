# LyricLoom 2.1.1

This release ships **LyricLoom 2.1.1** and **Starry Karaoke 1.3.1** for MusicBee. It makes the
karaoke sweep follow the singing better, times words more precisely and makes Whisper's
transcription far more reliable.

## Highlights

- **Line-synced lyrics now sweep at the song's own pace**, in Starry Karaoke and in the app's views.
  Lyrics with a time per line and none per word (LRCLIB, lyrics embedded in the file, most other
  players) were swept at one fixed pace in the plugin: a slow line finished early and then waited
  for the next one, and every sweep started exactly at the line's time, which usually comes a little
  before the voice. The app stretched the sweep to the next line instead, crawling over
  instrumentals. Both now learn the pace from the song's own lines, spread each line by sung
  syllables rather than letters, start a moment after the line's time and finish before the next
  line. Simulated against 13 word-timed songs, words lit more than 0.5 s before they are sung fell
  from 28% to 13% in the plugin, and words lit more than 0.5 s late fell from 26% to 14% in the app.
- **More precise word timing.** Each line is now aligned together with the lines around it, so its
  first word can no longer start on the previous line's last note. In the measured songs, English
  word starts within 100 ms of human timing went from 71% to 82%. Japanese is aligned in one pass
  over the whole song: without cloud transcription, a test song went from 55% to 95% of its lines
  within 0.5 s of a human sync.
- **More reliable transcription.** Whisper no longer carries the text of one 30-second window into
  the next, which could make it repeat a window through a whole song. Measured against the official
  lyrics, the character error fell from 63% to 20% in English and from 155% and 72% to 26% and 33%
  in Japanese, while Portuguese stayed at 6–7%. Word times now come from Whisper's own attention
  alignment (DTW) for the official Whisper models, at no extra cost on the GPU.

## Downloads

| Asset | What it is |
|---|---|
| `LyricLoom-Setup-2.1.1.exe` | Windows installer, per-user, no administrator rights |
| `LyricLoom-Setup.exe` | Stable copy of the latest installer, used by the in-app updater |
| `LyricLoom-2.1.1-win64.zip` | Portable Windows build; extract and run |
| `LyricLoom-2.1.1-linux-x86_64.tar.gz` | Linux bundle with a per-user `install.sh` |
| `StarryKaraoke-MusicBee-1.3.1.zip` | MusicBee plugin, recorder, romaji DLLs and dictionary |
| `SHA256SUMS` and per-file `*.sha256` | Checksums for every asset |

No new model is needed: 2.1.1 uses the models you already have.

## Upgrade notes

- **Engine 10 re-times songs written by an older engine** the next time you process them or the
  library. The transcript and the word timing are redone; the separated vocals are reused, so no
  separation runs again. The previous `.lrc` is backed up first. Songs already written by engine 10
  are skipped unless you use **Force**.
- **A song may list a few more lines for review** than before: the new transcript confirms
  slightly fewer lines, but much more precisely. English songs timed by the singing model keep the
  same timing.
- **Starry Karaoke 1.3.1** changes only how lyrics without word timing are swept; word-timed `.lrc`
  files display as before. Update it with the installer's MusicBee task (with MusicBee closed) or
  the release ZIP.
- Settings, library choice, models, caches and kept vocal stems are kept.

## Known limitations

- Lyrics synced per line are still an estimate: no player can know when each word is sung from a
  line time alone. Process the song with LyricLoom for word timing.
- The installer is **not code-signed**, so Windows SmartScreen can warn. Verify the published SHA-256
  before running it.
- Native AMD GPU acceleration on Windows is not supported; use WSL 2 + ROCm.
- On native Linux, the English singing model (MTL) runs on the CPU.
- The default MMS_FA alignment weights are **CC-BY-NC 4.0 (non-commercial)**. See
  [`THIRD-PARTY-NOTICES.md`](https://github.com/nishizumi-maho/lyricloom/blob/v2.1.1/THIRD-PARTY-NOTICES.md) before commercial use.
- The interface is English-only.

## Verify the download

The release publishes a `.sha256` file for every asset and one aggregate `SHA256SUMS`. On Windows:

```powershell
Get-FileHash .\LyricLoom-Setup-2.1.1.exe -Algorithm SHA256
```

On Linux:

```bash
sha256sum -c LyricLoom-Setup-2.1.1.exe.sha256
sha256sum -c SHA256SUMS
```

A mismatch means the download is corrupt or not the file you think it is. Delete it and download it
again from this release. Because the installer is unsigned, the checksum is the integrity check.

Full documentation is in the repository's `docs/` folder, starting with
[`README.md`](https://github.com/nishizumi-maho/lyricloom/blob/v2.1.1/README.md) and [`install-windows.md`](https://github.com/nishizumi-maho/lyricloom/blob/v2.1.1/docs/install-windows.md).
The changes of 2.1.0 are in [`release-notes-2.1.0.md`](https://github.com/nishizumi-maho/lyricloom/blob/v2.1.1/docs/release-notes-2.1.0.md).
