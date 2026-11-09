# Architecture

This page describes the pipeline, data flow, cache layout and extension points for contributors. It matches LyricLoom 2.0.0 (`ENGINE_VERSION = "7"`).

## The short version

```text
audio file
   │
   ├─ probe ────────────────► TrackMeta (artist, title, album, duration, probable language)
   │
   ├─ lyrics ───────────────► candidates from public sources (text, source, score, optional word timing)
   │
   ├─ separate ─────────────► vocals.wav + vocals16k.wav (and a kept lossless FLAC)
   │
   ├─ transcribe ───────────► Whisper word transcript (and optional AssemblyAI)
   │
   ├─ align ────────────────► per-word start/end + confidence
   │
   └─ write ────────────────► <song>.lrc (+ .original.lrc, script variants, .bak)
```

Every stage except `probe` has its own JSON cache. `write` also reads cached results; the audio file is never modified.

## Package layout

| Path | Responsibility |
|---|---|
| `lyricloom/cli.py` | `lyricloom` command: `process`, `models`, `doctor`. |
| `lyricloom/runner.py` | Orchestrates the six stages, caching, skip/force behavior, per-track errors. |
| `lyricloom/probe.py` | Reads tags with mutagen; determines probable language. |
| `lyricloom/lyrics/` | Source adapters, cleaning, metadata scoring, candidate choice. |
| `lyricloom/stages/separate.py` | Vocal separation, instrumental subtraction, kept-vocals handling. |
| `lyricloom/stages/transcribe.py` | whisper.cpp invocation and hallucination checks. |
| `lyricloom/stages/assemblyai.py` | Optional cloud transcript. |
| `lyricloom/stages/align.py` | Anchors → blocks → MTL/CTC → merge → refine → trim. |
| `lyricloom/stages/write.py` | LRC writing, backups, `.original.lrc`, Japanese variants. |
| `lyricloom/align/` | Anchor matching, CTC/MTL backends, consensus, confidence, merge, refine, trim. |
| `lyricloom/text/` | Japanese/Latin segmentation and readings; MMS tokenization. |
| `lyricloom/workers/` | Subprocess entry points for torch/audio-separator work. |
| `lyricloom/app/` | PySide6 window and pure model helpers. |
| `lyricloom/vendor/mtl/` | Vendored LyricsAlignment-MTL inference code (MIT). |
| `lyricloom/models.py` | Model catalog, per-language/per-track choices, verification status. |
| `lyricloom/downloads.py` | Verified, resumable HTTPS downloads (`.part` + size + SHA-256). |
| `lyricloom/runtime.py` | Model downloads and readiness checks. |
| `lyricloom/cache.py` | Per-track work directory and JSON cache. |
| `lyricloom/config.py` | Paths, settings, env vars, WSL/ROCm configuration. |
| `lyricloom/lrc.py` | Enhanced LRC parse/format. |

The engine has no Qt imports. The GUI imports the engine, not the other way around. Heavy stages run in separate processes, so the GUI never imports torch, torchaudio or audio-separator.

## Stage 1: probe

`probe(audio)` uses `mutagen.File(..., easy=True)` to read:

- artist
- title (falls back to the file stem)
- album
- duration
- probable language: `ja` when the artist or title contains kana/kanji, otherwise `other`

`TrackMeta` is not cached; it is cheap to read and changes when tags change.

The language is refined in `stages/align.lyric_lang` after transcription: Japanese tags or a Japanese transcript win; otherwise a transcript language of `pt` or `en` is used; everything else is `other`.

## Stage 2: lyrics

`lyrics/search.py` queries sources in this order:

1. `lrclib`
2. `netease`
3. `qq`
4. `utaten`
5. `genius`
6. `websearch` (DuckDuckGo, restricted to Genius/Uta-Net result pages)

For each source it tries title variants:

- the tag title;
- the title with bracketed text removed (`(TV Size)`, `[Single]`, etc.);
- for Japanese, a reading/romaji variant.

Each adapter returns `RawResult` objects: title, artist, duration, text, optional line/word timing, URL. `SourceBlocked` (401/403/429) stops that source for the current title variant; the search moves on. One broken source never stops the whole search.

`clean_lyrics` removes credit lines and site boilerplate. `score_meta` combines:

```text
0.4 * title similarity
0.3 * artist similarity
0.2 * duration similarity
0.1 * source weight
```

The candidate list is sorted by that metadata score, but the final choice happens after transcription, in `lyrics/score.choose`:

- If a transcript exists, the candidate's text must be phonetically similar to what was heard (`MIN_TRANSCRIPT_MATCH = 0.60`). The final score is `0.5 * metadata + 0.5 * heard`.
- If no usable transcript exists, only a very strong metadata match is trusted (`MIN_META_WITHOUT_TRANSCRIPT = 0.85`).
- The winner must still reach `MIN_ACCEPT = 0.55`.

A source's ready-made word timing (for example NetEase YRC) is stored on the candidate as `synced: list[Line]`. It is not trusted blindly; the align stage compares it with the audio.

If no candidate is accepted, the transcript becomes the lyric (`source = "transcription"`). That track is marked for review and no `.original.lrc` is written.

## Stage 3: separate

`stages/separate.py` does the following:

1. If a kept vocal stem exists at `vocals_root/<relative path>/<song>.vocals.flac`, copy it into the work directory as `vocals.wav`. No separator run is needed.
2. Otherwise, look for a same-folder instrumental:
   - same title plus an instrumental/off-vocal/inst/karaoke marker;
   - duration within 3 seconds of the song;
   - not the song itself.
3. If an instrumental is found, `stages/instrumental.py` aligns it to the mix with a short least-squares filter (delay, gain, slight EQ), block by block, and writes `mix - instrumental` only when the cancellation is convincing (at least 3 seconds that cancel by 25 dB or more).
4. Run the separator on the chosen source (full mix or subtracted mix):
   - in WSL/ROCm when `SEPARATOR_WSL_ENABLED`;
   - otherwise on Windows/Linux with the current Python.
5. Write `vocals.wav`, then a mono 16 kHz `vocals16k.wav`.
6. Keep a lossless FLAC copy outside the library.

The separator worker uses `audio-separator` with `vocals_mel_band_roformer.ckpt`, batch size 1, segment size 256, overlap from `LYRICLOOM_SEPARATOR_OVERLAP` (default 2), and device `auto`/`cuda`/`cpu`/`dml`.

If the WSL attempt fails, the exception tail is stored as `fallback`, the Windows/Linux worker runs on the CPU, and the track result records both the device and the fallback reason.

## Stage 4: transcribe

`stages/transcribe.py` calls:

```text
whisper-cli -m <models>/ggml-large-v3.bin -f vocals16k.wav
  -l ja|pt|en|auto -ojf -of <work>/<name>
  -ml 1 -sow --beam-size 5 --best-of 5 -t <threads> -np
  [--prompt "artist - title"] [extra flags]
```

It parses the JSON word tokens into `Word(text, start_ms, end_ms, prob)`.

`looks_hallucinated` flags output that is not a plausible transcript:

- fewer than 15 words per minute;
- at least 30% credit/subtitle markers;
- at least 30 words with five or fewer distinct normalized tokens (repetition).

Hallucinated output is not used as anchors or as the lyric text.

For tracks with no usable official lyric, `_extra_passes` runs two more transcriptions:

- the full mix (not just the vocal stem);
- the vocal stem at temperature 0.2.

`align/consensus.rover` fuses the passes word by word against the first pass. The first pass supplies the word skeleton and times; repeated refrains are reconciled separately with `refrain_consensus`.

Optional AssemblyAI is called only when `ASSEMBLYAI_ENABLED` (key file or env var) and the runner needs it. Its transcript is cached as `assemblyai_vocals.json` and can be reused without a second upload.

## Stage 5: align

`stages/align.py` is the core:

1. **Text preparation.** `split_line` splits Japanese with MeCab/IPADic (keeping inline furigana with its kanji) or Latin text into words with their trailing spaces. `reading` produces the romanized form used for matching.
2. **Anchors.** `align/anchors.find_anchors` aligns the lyric's romanized characters against the Whisper transcript's romanized words with Needleman–Wunsch. A lyric line becomes an anchor when at least 70% of its characters match. Anchors carry the Whisper start/end of the matched words.
3. **Blocks.** `blocks` turns anchors into short regions with 500 ms margins. Lines between anchors stay in the same block; unanchored intro/outro lines get their own block. Blocks prevent one alignment error from drifting across the song.
4. **Backend.**
   - **English + full-rate vocals + MTL available:** `align/mtl.align_lines_mtl` runs LyricsAlignment-MTL. This is the preferred English path.
   - **Everything else, or MTL failure:** `align/ctc.align_blocks` runs torchaudio MMS_FA CTC alignment per block.
   - MTL failure is caught and logged; processing falls back to CTC.
5. **Per-word results.** CTC returns a start, end and score per segment. MTL returns start/end; punctuation segments have no acoustic word and stay `None`.
6. **Ready-made timing.** `merge_presync` compares each line with a source's synced line by normalized text and character offsets. If the mean difference is at most 150 ms and every segment can be retimed, the source timing replaces ours and the line confidence rises to at least 0.9. Otherwise our timing is kept.
7. **Refine.** `align/refine.py` enforces strictly increasing starts, no overlaps, no times past the track end, and collapses any line that is only partly aligned into a single line-timed text segment.
8. **Trim.** `align/trim.py` finds where the isolated vocal actually goes quiet after the last word (20 ms RMS frames, 300 ms of quiet at 16 dB below the line's voiced level, minimum 150 ms) and moves the last end back. This stops a word from staying lit through an instrumental break.
9. **Confidence.** `line_conf` is `0.6 * mean(CTC score) + 0.4 * anchor score`; MTL lines use the anchor score (or 0.55 when Whisper did not hear the line). `track_conf` is duration-weighted. `REVIEW_THRESHOLD = 0.6`.

The result is a list of `Line(start_ms, segments, conf)` where each `Segment` has text, start, end and confidence. The line's displayed text is the concatenation of its segments, preserving the original spacing.

## Stage 6: write

`stages/write.py`:

- builds `[ti:]`, `[ar:]`, `[re:LyricLoom <app version>]`, `[#source:<name> conf:<track conf>]`, `[#engine:<ENGINE_VERSION>]`, and `[#review:<zero-based line indices>]` when needed;
- writes UTF-8 without BOM, LF line endings, via a temporary file and `os.replace`;
- renames an existing main `.lrc` to `.lrc.bak`, `.lrc.bak1`, ... before replacing it;
- writes `.original.lrc` for online sources;
- for Japanese lyrics, writes `.japanese.lrc` and `.romaji.lrc`, then writes the main `.lrc` in the chosen script.

See [docs/lrc-format.md](lrc-format.md) for the exact contract.

## Cache layout

`cache.work_dir(audio)` hashes:

```text
<resolved path>|<file size>|<mtime_ns>
```

with SHA-1 and takes the first 16 hex characters:

```text
<data>/work/<hash>/
├── lyrics.json
├── separate.json
├── transcribe.json
├── transcribe_extra.json
├── transcribe_extra_aai.json
├── assemblyai_vocals.json
├── whisper.json
├── whisper_mix.json
├── whisper_t02.json
├── vocals.wav
├── vocals16k.wav
├── minus_instrumental.wav
└── log.txt
```

Not every file exists for every track. `lyrics.json` contains candidates; `separate.json` contains model/device/fallback and paths; `transcribe.json` contains the transcript; the extra files are for fallback/voting passes.

Each JSON cache has a `_version` field. `runner.STAGE_VERSIONS` currently is:

```python
{"lyrics": "4", "separate": "4", "transcribe": "3",
 "transcribe_extra": "3", "transcribe_extra_aai": "3"}
```

Bump a stage version only when that stage's output would change. The whole-file `ENGINE_VERSION` (`"7"`) is written to `#engine`; a track is skipped only when the `[re:]` marker is ours and `#engine` matches. This lets an engine change that only affects alignment avoid redoing separation and transcription.

The kept vocal stems live outside the work cache:

```text
<data>/vocals/<artist>/<album>/<song>.vocals.flac
```

The relative path mirrors the library layout. If the song is outside the library, the path is derived from the two parent folder names. Kept vocals survive cache cleanup and are reused on later runs.

The library scan cache is one JSON per library:

```text
<data>/scan-<sha1(normalized library path)[:12]>.json
```

It stores the last row per audio path and the audio/`.lrc` modification stamps. A scan re-reads only tracks whose stamps changed.

## Worker model

The GUI must stay responsive and must not hold VRAM between stages. Heavy work runs in a subprocess:

- **Source checkout:** `python -m lyricloom.workers.<name>`.
- **Frozen build:** `LyricLoomWorker.exe <name>` next to the GUI; if missing, the frozen GUI's `--worker` mode.
- **WSL:** `wsl.exe -d <distro> --cd <cwd> --exec env KEY=VALUE ... <python> -m lyricloom.workers.<name>`.

The parent writes a JSON payload to the worker's stdin. The worker writes a single marked JSON result line to stdout:

```text
@@lyricloom-RESULT@@ {"...": ...}
```

Libraries may print to stdout, so only the marked line is parsed. A non-zero exit or missing result raises `WorkerError` with the stderr tail. WSL paths are translated with `wsl_path` (`F:\X` → `/mnt/f/X`) and back with `windows_path`.

This design:

- releases all VRAM when the worker exits;
- lets the WSL stages use a different Python interpreter;
- keeps torch/audio-separator imports out of the GUI process;
- turns a crash into a per-track failure instead of a dead app.

The trade-off is process startup and model load time per stage. The per-stage cache avoids repeating that work for the same song.

## GUI model

`app/model.py` contains no Qt:

- `read_status(audio)` reads the `.lrc` metadata and returns a `TrackRow`.
- `scan_cached(root)` uses the scan cache.
- `load_cached_rows(root)` shows the last scan immediately.
- edit helpers (`insert_word`, `delete_word`, `insert_line`, `merge_with_previous`, `apply_edits`) operate on `LrcDoc`/`Line`/`Segment`.
- `track_progress` estimates progress from stage and elapsed time; separation dominates the estimate.

`app/main.py` owns the Qt window, the `QMediaPlayer`, the queue thread and the editor table. The queue processes one track at a time and emits row updates. The UI never calls torch.

## Configuration

`config.py` resolves, in order:

- data root: `LYRICLOOM_DATA_DIR`, then platform default;
- models root: `LYRICLOOM_MODELS`, `models` setting, a developer `models/` folder, then the data root;
- library: `library` setting, then `~/Music`;
- vocals: `vocals` setting, then `<data>/vocals`;
- tools: `whisper_cli` setting / `LYRICLOOM_WHISPER_CLI`, bundled `tools/bin`, project `tools/bin`, `<data>/bin`, then `PATH`.

Environment variables that affect behavior:

| Variable | Effect |
|---|---|
| `LYRICLOOM_DATA_DIR` | Moves settings, cache, vocals and default models. |
| `LYRICLOOM_MODELS` | Moves only the models. |
| `LYRICLOOM_WHISPER_CLI` | Full path to a whisper.cpp `whisper-cli` (same as the `whisper_cli` setting). |
| `LYRICLOOM_WHISPER_MODEL` | Deprecated: the old filename override. Use `model_choices` / `lyricloom models use`. |
| `LYRICLOOM_SEPARATOR_DEVICE` | `auto`, `cpu`, `cuda` or `dml` for the separator worker. |
| `LYRICLOOM_SEPARATOR_OVERLAP` | Separator overlap (default 2). |
| `LYRICLOOM_CPU_THREADS` | Caps worker thread pools (default one quarter of logical CPUs). |
| `LYRICLOOM_ALIGN_DEVICE` | `auto`/`cpu`/`cuda` for CTC alignment. |
| `ASSEMBLYAI_API_KEY` | Enables optional cloud transcription. |

Settings are JSON at `<data>/settings.json`. WSL keys are documented in [docs/wsl-rocm.md](wsl-rocm.md#7-configure-lyricloom).

## Extension points

### Add a lyric source

Create `lyricloom/lyrics/sources/<name>.py` with:

```python
name = "example"

def search(meta: TrackMeta, client: httpx.Client) -> list[RawResult]:
    ...
```

Return `RawResult(title, artist, duration_s, text, synced, url)`. Use `check(response)` from `sources/base.py` so 401/403/429 raise `SourceBlocked`; do not work around blocks. Add the module to `SOURCES` in `lyrics/search.py` and a weight in `lyrics/score.SOURCE_WEIGHT` if appropriate.

Tests for parsers belong in `tests/sources/`; use recorded fixtures, not live network calls.

### Add or change an alignment backend

The output contract is a list of `Line` objects with `Segment` timings. `stages/align.py` chooses between MTL and CTC. To add a backend:

1. Add a module under `align/` and, if it needs torch, a worker under `workers/`.
2. Keep the worker protocol: JSON stdin, marked JSON stdout, no GUI imports.
3. Add the dispatch and fallback in `stages/align.py`.
4. Bump `ENGINE_VERSION` and any affected `STAGE_VERSIONS`.
5. Add a test with a synthetic or fixture transcript.

Do not silently drop words or invent times; the first pass's word skeleton is the source of truth in consensus code.

### Add a model

1. Add the download/readiness logic to `runtime.py`.
2. Add a worker download kind in `workers/download.py` if the download needs torch/audio-separator.
3. Add a CLI choice in `cli.py`.
4. Document the path, size and license in [docs/models.md](models.md) and [THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md).

Downloads must use a `.part` file and verify a checksum when the upstream publishes one.

### Change the output format

`lrc.py` is the parser/formatter; `stages/write.py` is the file policy. Changing either affects every downstream player. Update:

- `tests/test_lrc.py`, `tests/test_write.py`;
- `docs/lrc-format.md`;
- `ENGINE_VERSION` if existing files should be reprocessed;
- the Starry Karaoke parser if the plugin needs a new construct (separate repository).

## Concurrency and failure handling

- A folder run is serial. One track's exception is caught in `runner.process`, logged with a traceback, and returned as `TrackResult(status="failed")`; the queue continues.
- The GUI's Stop sets a flag; it takes effect after the current track.
- A stage cache miss recomputes only that stage (and later stages if `--stage` was used).
- A missing WSL runtime is a fallback, not a fatal error.
- A failed AssemblyAI call is logged and ignored; it never fails the track on its own.
- A failed MTL run falls back to CTC; a failed CTC block returns `None` segments and the line falls back to line timing.

## Tests and development

- `pytest` runs the default suite; `pytest -m gpu` runs tests that need real models or a GPU (deselected by default).
- Source adapters have recorded fixtures under `tests/fixtures` and `tests/sources`.
- `tests/test_lrc.py` and `tests/test_write.py` cover the file contract.
- `tests/test_runner.py`, `tests/test_cache.py`, `tests/test_align_stage.py` cover orchestration and caching.
- `ruff check .` enforces style; line length is 120.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for setup and pull-request guidance.

## Design constraints

- **Official lyrics first.** Whisper text is a fallback, not the default. The official lyric is kept in `.original.lrc`.
- **Local by default.** Only lyric search, model downloads and the optional AssemblyAI path use the network.
- **One song at a time.** Memory/VRAM predictability beats parallel throughput for a desktop tool.
- **Every expensive stage is cacheable and versioned.**
- **Never modify the audio.** Only read it; write sidecar files.
- **Failure is per track.** A bad file or a missing model must not kill a library run.
- **The `.lrc` is the contract.** The app, CLI and MusicBee plugin all meet there.
