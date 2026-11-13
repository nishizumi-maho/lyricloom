# LyricLoom 2.2.0

This release ships **LyricLoom 2.2.0**. It adds GPU processing on Windows without WSL and keeps
the interface English on any Windows language. **Starry Karaoke stays at 1.3.1**; the plugin in
this release is unchanged.

## Highlights

- **GPU on Windows, set up by the app.** The setup assistant's **Acceleration** page has a new
  **GPU on Windows** group. Choose a backend and click **Set up and use**: LyricLoom builds a GPU
  version of PyTorch in its own folder, runs a real operation on the graphics card and, only if
  that works, uses it from the next song. No WSL, no manual Python or CUDA installation and no
  restart.
  - **NVIDIA GPU (CUDA)** is preselected when an NVIDIA card is found. Vocal separation, forced
    alignment and the English singing model run on the GPU. It downloads about 3 GB and needs
    about 8 GB of free disk space and a current NVIDIA driver. RTX 50-series cards get the
    CUDA 12.8 build they need; other cards get CUDA 12.4.
  - **DirectML** is an experimental option for AMD, Intel and NVIDIA GPUs that runs **vocal
    separation**, the slow stage, on the GPU. MDX-Net and VR separator models work on any
    supported card. RoFormer models, including the suggested Mel-Band RoFormer, need about
    16 GB of video memory under DirectML, so **Run RoFormer models on the GPU too** is ticked
    for you only on such a card. Measured on a Radeon RX 6900 XT (16 GB): the suggested model
    3 to 4 times faster than the CPU with identical output, and MDX-Net Voc FT about 6 times
    faster. Both alignment models stay on the CPU; WSL with ROCm remains the path that puts
    every stage on an AMD GPU.
- **CPU stays the default and the safety net.** A cancelled or failed setup changes no setting
  and can simply be run again. If a GPU stage fails while a song is processed, that song finishes
  on the CPU and the status bar and the track log say why.
- **English everywhere.** Windows error messages appeared in the system's display language, and
  numbers and dates followed the Windows regional format; both are now English. On a non-English
  Windows, WSL without a distro was reported as "not installed"; that check no longer depends on
  the language. The lyrics web search no longer adds the Portuguese word "letra" to the query for
  songs that are not Portuguese.

## Downloads

| Asset | What it is |
|---|---|
| `LyricLoom-Setup-2.2.0.exe` | Windows installer, per-user, no administrator rights |
| `LyricLoom-Setup.exe` | Stable copy of the latest installer, used by the in-app updater |
| `LyricLoom-2.2.0-win64.zip` | Portable Windows build; extract and run |
| `LyricLoom-2.2.0-linux-x86_64.tar.gz` | Linux bundle with a per-user `install.sh` |
| `StarryKaraoke-MusicBee-1.3.1.zip` | MusicBee plugin, recorder, romaji DLLs and dictionary (unchanged) |
| `SHA256SUMS` and per-file `*.sha256` | Checksums for every asset |

No new model is needed: 2.2.0 uses the models you already have. The installer is the same size as
before; the GPU runtime is downloaded only if you ask for it.

## Upgrade notes

- **Nothing changes until you choose it.** After the update LyricLoom keeps the acceleration you
  had (CPU or WSL). To use an NVIDIA card on Windows, open **Help > Setup assistant… >
  Acceleration** and click **Set up and use** under **GPU on Windows**.
- **One acceleration choice is in effect at a time.** Selecting the Windows runtime turns the WSL
  path off, and selecting a WSL environment or **CPU only** deselects the runtime. An installed
  runtime is kept until you click **Remove…**.
- The engine version is unchanged, so no song is processed again because of this update.
- The GPU setup downloads from GitHub (`uv` and a standalone Python), `download.pytorch.org` and
  PyPI, only when you click the button. See [docs/privacy.md](privacy.md#windows-gpu-runtime-setup).
- Settings, library choice, models, caches and kept vocal stems are kept. The uninstaller now also
  removes the GPU runtimes and installed whisper.cpp builds when you ask it to delete LyricLoom's
  data.

## Known limitations

- **The CUDA runtime was developed without access to an NVIDIA card.** It is covered by automated
  tests and its package set was resolved for Windows, but its first real runs are on your
  hardware. The setup's own GPU test is what verifies it: if the test fails, nothing is changed
  and LyricLoom keeps using the CPU. Please report a failure with the text from
  **Help > Diagnostics…**.
- **RoFormer models on DirectML take nearly all of a 16 GB card's video memory** (15.5 GB at
  the peak in our test) because of how torch-directml allocates it. With a game or another
  GPU program open, the attempt fails and the song is separated on the CPU. On cards with less
  memory the option is off by default and RoFormer models stay on the CPU.
- DirectML was tested on one AMD card. Intel and NVIDIA cards are expected to work the same way
  but were not tested.
- Whisper transcription on an NVIDIA GPU is still a separate choice: install the **cuBLAS**
  whisper.cpp build under **Faster transcription** on the same page.
- The installer is **not code-signed**, so Windows SmartScreen can warn. Verify the published
  SHA-256 before running it.
