# The LRC files LyricLoom writes

LyricLoom writes **enhanced LRC**: ordinary line timestamps plus word-level `<mm:ss.xx>` tags. The format is designed so a normal LRC player still shows the lyrics line by line, while a player that understands word tags can light up each word.

This page documents the files, tags and backup behavior. The exact output for a given song depends on the lyric source, the language and the alignment result.

## Files next to a song

For `01 - Synthetic Song.flac` in `D:\Music\Artist\Album\`:

| File | When it is written | Purpose |
|---|---|---|
| `01 - Synthetic Song.lrc` | Every successful run | The enhanced lyric with word timing. |
| `01 - Synthetic Song.original.lrc` | When the lyric came from an online source (not transcription or pasted lyrics) | The official lyric as found, kept for reference and recovery. |
| `01 - Synthetic Song.japanese.lrc` | When the lyric is resolved as Japanese | The Japanese-script version, even if the main `.lrc` is romaji. |
| `01 - Synthetic Song.romaji.lrc` | When the lyric is resolved as Japanese | The romanized version, even if the main `.lrc` is Japanese. |
| `01 - Synthetic Song.lrc.bak`, `.bak1`, ... | When an existing main `.lrc` is replaced | Backups of earlier main `.lrc` files. |

The audio file itself is never modified.

## A complete example

```lrc
[ti:Synthetic Song]
[ar:Demo Artist]
[re:LyricLoom 2.0.0]
[#source:uta-net conf:0.94]
[#engine:7]
[#models:transcribe=whisper-large-v3;separate=separator-mel-band-roformer;align=align-mms-fa]
[00:22.98]<00:22.98>こ<00:23.10>れ<00:23.30>は<00:23.50>合<00:24.05>成<00:24.30>の<00:24.62>歌<00:24.90>詞<00:25.12>で<00:25.30>す<00:25.62>
[00:26.10]<00:26.10>例<00:26.30>で<00:26.55>す<00:27.10>

Times are illustrative. What matters is the structure:

- `[00:22.98]` is the line start.
- `00:22.98`, `00:23.10`, ... are the starts of the segments that follow them.
- The final `<00:27.10>` has no text. It is the end of the last segment, not a word.
- The Japanese text has no spaces between segments. The text between tags is exactly what is displayed.
- A Latin line keeps the spaces in the text:

```lrc
[00:14.20]<00:14.20>Hello <00:14.55>from <00:14.80>the <00:15.05>other <00:15.40>side<00:15.90>
```

LyricLoom does not insert separators when it writes the file. If a word should have a trailing space, that space is part of the segment text. This is what keeps Japanese unspaced and English readable.

## Metadata tags

Tags are written at the top, in this order when present:

| Tag | Example | Meaning |
|---|---|---|
| `[ti:...]` | `[ti:Synthetic Song]` | Track title from the audio tags. Falls back to the file stem. |
| `[ar:...]` | `[ar:鈴木このみ]` | Artist from the audio tags. May be empty if the file has no artist tag. |
| `[re:...]` | `[re:LyricLoom 2.0.0]` | The application that wrote the file and its version. LyricLoom also accepts the legacy `LYRICS BOCA` marker when deciding whether a file is its own. |
| `[#source:...]` | `[#source:uta-net conf:0.94]` | Where the lyric came from, followed by the track confidence. Sources include `lrclib`, `netease`, `qq`, `utaten`, `genius`, `websearch`, `transcription` and `manual`. |
| `[#engine:...]` | `[#engine:7]` | The engine version that produced the timing. This is separate from the app version. A new engine version can change timings and cause reprocessing. |
| `[#models:...]` | `[#models:transcribe=whisper-large-v3;separate=separator-mel-band-roformer;align=align-mms-fa]` | The model each stage used for this song, as `stage=model-id` pairs separated by `;`. Written on every successful run. |
| `[#language:...]` | `[#language:ja]` | The resolved lyric language when it is known. It controls script variants and language-specific models. |
| `[#warning:...]` | `[#warning:no usable transcript; word timing unconfirmed]` | Warnings the app shows in the row tooltip. A track with a warning is marked review. |
| `[#lyrics:search-empty]` | `[#lyrics:search-empty]` | The lyric search returned no candidates. The next normal run retries it; it is never treated as a finished lyric search. |
| `[#review:...]` | `[#review:3,7,12]` | Zero-based line numbers whose confidence is below the review threshold or whose anchor was unusable. The app tints these rows orange. |

### About `[#models:...]`

`#models` records the model ids that produced the timing, for example:

```text
[#models:transcribe=whisper-large-v3;separate=separator-mel-band-roformer;align=align-mms-fa;singing=singing-mtl]
```

- `transcribe` is the Whisper model used for the transcript and anchors.
- `separate` is the vocal separator.
- `align` is the forced-alignment model (MMS_FA by default).
- `singing` is present only when the English singing model timed the words. When English falls
  back to CTC, or the song is another language, the tag has no `singing` entry.

The ids match `lyricloom models list` and the `model_choices` setting. A per-song
"Process with other models…" run records its own ids here, so the app can show that a lyric was
made with different models. Changing a model does **not** mark a finished song as pending; the tag
is the record of what was used, and a reprocess rewrites it.

### About `[#source:...]`

The confidence in `#source` is the **track confidence**, a duration-weighted average of the line confidences. It is not the lyric-search score. A value near 1.00 is strong; lower values mean more of the track is uncertain.

The source names map to the lyric providers:

- `lrclib` — LRCLIB
- `netease` — NetEase Cloud Music
- `qq` — QQ Music
- `utaten` — Uta-Net
- `genius` — Genius
- `websearch` — DuckDuckGo result that pointed at a supported page
- `transcription` — Whisper's own text, used only when no lyric source was accepted
- `manual` — lyrics pasted into the app and re-aligned

### About `[#review:...]`

`#review` lists **zero-based** line indices, comma-separated, in ascending order. The first lyric line is line `0`, not line `1`. The app uses the same indices for its orange tint and for the `Review` filter.

A track can have the `review` status without a `#review` tag when the chosen source is `transcription`. In that case the whole lyric is a fallback, even if every line happened to score above the threshold. The runner also writes `#warning:...` and marks every line when the anchor transcript was hallucinated or empty.

Editing a word does not automatically remove its line from `#review`. The tag describes what the engine was unsure about; a human edit is not a new confidence score. Reprocess the song, or remove the tag deliberately, if you want the track to leave the Review filter.

## Line timing without word timing

A line that could not be word-aligned is still written with a line timestamp and plain text:

```lrc
[00:42.10]This line is spoken, whispered or otherwise not alignable
```

This happens when the line has no sung words the aligner can use, when a block cannot be aligned, or when the text and audio disagree too much. The line is still displayed by any LRC player; it simply has no word-level movement.

When the whole lyric is in a script the aligner cannot romanize (Han, Hangul, Cyrillic, Thai, ...), every line is written with line timing, the track is marked `review`, and the `.lrc` says why in `[#warning:...]`. LyricLoom does not invent a romanization.

All segments in a line are either timed or the line falls back to a single untimed text segment. LyricLoom does not write a half-timed line.

## Timestamp resolution

- Times are formatted as `mm:ss.xx` in **centiseconds** (10 ms resolution).
- Values are rounded to the nearest centisecond when written.
- Minutes can exceed 59; the format does not use an hours field.
- LyricLoom never writes negative times. `refine` clamps starts and ends to the track duration.

## `.original.lrc`

The official lyric is kept as `<song>.original.lrc` so that a later edit or reprocess does not destroy the source text. It is written only when the chosen lyric came from an online source. It is **not** written for `transcription` or `manual`.

The file contains:

```lrc
[ti:Synthetic Song]
[ar:Demo Artist]
[#source:uta-net]
```

followed by either:

- the source's own line timing, if the source provided synced lyrics (without LyricLoom's word tags), or
- the plain lyric text, one line per line, if the source was plain text.

`original.lrc` is a reference and recovery file. It is overwritten atomically on each successful run that has an online source; it is not rotated into `.bak` files. It does not contain `[re:]`, `[#engine:]` or `[#review:]`.

## `.japanese.lrc` and `.romaji.lrc`

When the resolved lyric language is Japanese, LyricLoom writes both script variants:

- `<song>.japanese.lrc` — the original Japanese text and word timing.
- `<song>.romaji.lrc` — the same lines and word timing with each segment romanized.

The resolved language comes from the track's `language` tag, an explicit app/CLI override, kana in
the tags or transcript, or Japanese lyrics. Han characters alone are not enough: a Chinese lyric
such as 孤勇者 gets only the main `.lrc`, never Japanese or romaji variants.

The main `<song>.lrc` is a copy of one of them, chosen by the app's **Japanese script** setting:

- **Japanese: 日本語** → main `.lrc` is the Japanese version.
- **Japanese: romaji** → main `.lrc` is the romaji version.

Both variants are always kept, so changing the setting later does not require reprocessing. The app rewrites the main `.lrc` of every Japanese song under the current library when you change the setting.

Notes:

- Romanization uses MeCab/IPADic readings and pykakasi. Inline furigana such as `運命(さだめ)` is treated as the sung reading.
- The romaji file inserts spaces between segments for readability; the Japanese file does not.
- The `.japanese.lrc` and `.romaji.lrc` files are replaced atomically without `.bak` copies. The main `.lrc` still gets a backup when it is replaced, including when a script-preference change rewrites it.
- If an older LyricLoom version wrote a Japanese `.lrc` but not the two variants, changing the script preference creates the missing variants from the existing main file.
- Redo only moves aside `.japanese.lrc` / `.romaji.lrc` files that carry LyricLoom's `[re:]` marker; a sidecar from another tool is left alone.

## Backups and restoring

When LyricLoom replaces an existing **main** `.lrc`, it first renames it:

```text
01 - Synthetic Song.lrc       -> 01 - Synthetic Song.lrc.bak
01 - Synthetic Song.lrc       -> 01 - Synthetic Song.lrc.bak1   (if .bak exists)
01 - Synthetic Song.lrc       -> 01 - Synthetic Song.lrc.bak2   (if .bak1 exists)
```

The write itself is atomic: LyricLoom writes a temporary file and renames it into place. A crash during the write should leave either the old file or the new one, not a truncated `.lrc`.

The app's **Save** button uses the same path, so manual edits also keep the previous main file as a backup.

To restore a backup:

1. Close LyricLoom and any player that has the file open.
2. Rename the current `.lrc` out of the way.
3. Rename `.lrc.bak` (or `.bak1`, `.bak2`, ...) to `.lrc`.
4. Reopen the song.

`.original.lrc`, `.japanese.lrc` and `.romaji.lrc` do not get `.bak` copies. The `.original.lrc` is the source text rather than a previous enhanced version; use it if you need the untouched lyric.

## Compatibility

| Player / use | What it does with the file |
|---|---|
| Ordinary LRC player | Uses `[mm:ss.xx]`; ignores `<...>` tags and unknown metadata. Lyrics still scroll by line. |
| Enhanced LRC player | Uses `<...>` for word or segment highlighting. |
| MusicBee + Starry Karaoke | Uses the `<...>` tags for the gold word-by-word fill. |
| Text editor | UTF-8, LF line endings, no BOM. |
| LyricLoom itself | Recognizes its own `[re:]` marker (and the legacy `LYRICS BOCA` marker) when deciding whether to skip, back up or redo a file. A `.lrc` from another program is left alone and shown as `other` in the library. |

Because the text between tags is preserved verbatim, a player that does not understand `<...>` may display the tags literally. Use a player with enhanced LRC support for karaoke; use any player for line-level lyrics.

### What is not written

- No `[offset:]` tag. Use the player's offset setting if a whole file is consistently early or late.
- No translation or second-language line.
- No album art, no audio, no embedded tags in the audio file.
- No word timing for a line that could not be aligned; that line falls back to line-only timing.

## Manual edits and the file's contract

The app edits the same structure that is written to disk:

- Each line has a start time and a list of segments.
- Each segment has text, a start and an end.
- The line timestamp is the first timed segment's start.
- The final closing tag is the last timed segment's end.
- Timestamps are kept strictly increasing and non-overlapping by `refine` after every edit.

If you edit the file by hand, keep the tags paired and the times increasing. A malformed `<...>` tag may be ignored by a player, but LyricLoom's parser will not recover the intended segment. When in doubt, edit in the app and let it rewrite the file.

For the pipeline that produces these files, see [docs/architecture.md](architecture.md). For model and privacy details, see [docs/models.md](models.md) and [docs/privacy.md](privacy.md).
