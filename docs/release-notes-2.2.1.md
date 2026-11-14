# LyricLoom 2.2.1

This release ships **LyricLoom 2.2.1**, a bug-fix release. **Starry Karaoke stays at 1.3.1**; the
plugin in this release is unchanged.

> **Install this one by hand.** The update check in LyricLoom 2.1.0, 2.1.1 and 2.2.0 does not
> work, so those versions cannot find or install 2.2.1 on their own. Download
> `LyricLoom-Setup-2.2.1.exe` below and run it over your installation. From 2.2.1 on, updates
> arrive automatically again.

## Fixed

- **The update check works again.** Since 2.1.0 the app failed to read GitHub's answer, so the
  automatic check at start-up found nothing and never said so, and **Help > Check for updates…**
  showed `ResponseNotRead`. The check, the checksum file and the installer download were tested
  against the real 2.2.0 release for this fix.
- **Searching a large library no longer freezes the window.** With a sorted table, every change of
  the search text or the status filter sorted the whole library again in a slow way. In a library
  of 30,000 songs a keystroke took 2 to 11 seconds; it now takes about 0.15 seconds. Clicking a
  column header to sort went from about 10 seconds to 0.3 seconds. The selection stays on the
  same songs when the order changes, as before.

## Downloads

| Asset | What it is |
|---|---|
| `LyricLoom-Setup-2.2.1.exe` | Windows installer, per-user, no administrator rights |
| `LyricLoom-Setup.exe` | Stable copy of the latest installer, used by the in-app updater |
| `LyricLoom-2.2.1-win64.zip` | Portable Windows build; extract and run |
| `LyricLoom-2.2.1-linux-x86_64.tar.gz` | Linux bundle with a per-user `install.sh` |
| `StarryKaraoke-MusicBee-1.3.1.zip` | MusicBee plugin, recorder, romaji DLLs and dictionary (unchanged) |
| `SHA256SUMS` and per-file `*.sha256` | Checksums for every asset |

## Upgrade notes

- Settings, library choice, models, caches, GPU runtimes and kept vocal stems are kept.
- The engine version is unchanged, so no song is processed again because of this update.
- Everything else is as in [2.2.0](release-notes-2.2.0.md), including its known limitations.
- The installer is **not code-signed**, so Windows SmartScreen can warn. Verify the published
  SHA-256 before running it.
