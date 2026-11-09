# AMD GPUs on Windows with WSL 2 and ROCm

LyricLoom is a Windows application, but the heavy audio stages can run on an AMD GPU inside **WSL 2**
using **ROCm**. The app stays on Windows; only the vocal separator, forced alignment and (optionally)
the English singing model cross into Linux.

This page starts with the setup assistant, which handles the normal case. The manual procedure later
on is the advanced path for an existing environment or when the assistant cannot finish.

## What runs where

| Stage | Where it runs with WSL/ROCm enabled |
|---|---|
| Library scan, lyrics search, writing `.lrc` | Windows |
| Whisper transcription (`whisper-cli`) | Windows, using the installed build (CPU by default; a custom Vulkan build if present) |
| Vocal separation (Mel-Band RoFormer) | WSL 2 / ROCm |
| MMS_FA forced alignment | WSL 2 / ROCm |
| English singing model (LyricsAlignment-MTL) | WSL 2 / ROCm when its code and checkpoint are inside the distro; otherwise the CPU fallback |

If WSL, the distro or its Python environment is unavailable, LyricLoom falls back to the CPU and
continues. The status bar shows `Device: CPU (fallback)` in orange and the reason is written to the
track's `log.txt`.

## The easy path: the setup assistant

Open **Help > Setup assistant… > Acceleration**. The page shows a suggestion and the reasons for it,
then offers these paths.

### Use an existing WSL GPU environment

Use this if the distro already has a working Python environment with PyTorch and audio-separator.

1. Click **Find WSL environments**. LyricLoom checks the configured `wsl_python`,
   `/opt/lyricloom/venv/bin/python` and every `/opt/*/bin/python` inside each WSL 2 distro.
2. The probe imports `torch`, `torchaudio`, `audio_separator`, `g2p_en`, `nltk` and `lyricloom`, and
   checks whether `torch.cuda.is_available()` is true. A failed candidate is listed with the reason;
   only a passing environment can be used.
3. Select an environment and click **Use this**. The app writes `wsl_gpu`, `wsl_distro` and
   `wsl_python`, and leaves `wsl_env` and `wsl_hsa_override` untouched.
4. Restart LyricLoom. WSL is read at start-up, so the old process keeps the previous settings.

The setup assistant never installs GPU drivers or ROCm into an existing environment.

### Create a new WSL environment with the bundled script

Use this for a fresh distro or a new `/opt/lyricloom/venv`.

1. Install WSL 2 and, for AMD, the Windows AMD driver and the ROCm stack first. The assistant can
   run **Install WSL now…** (Windows asks for administrator rights and may ask for a restart), but it
   does not install ROCm or a GPU driver. AMD's ROCm-on-WSL guide is linked by the script when ROCm
   is missing.
2. On **Acceleration**, choose a **Backend**:
   - **ROCm (AMD GPU)** requires a working `rocminfo` in the distro;
   - **CUDA (NVIDIA GPU)** installs the CUDA 12.4 PyTorch wheels;
   - **CPU only inside WSL** creates the environment without GPU support.
3. Click **Set up WSL…**. The bundled script streams its log into the page and drives the progress
   bar. It performs seven steps:
   1. `apt` installs `python3-venv` and `ffmpeg`;
   2. creates `/opt/lyricloom/venv`;
   3. updates pip, setuptools and wheel;
   4. installs PyTorch and torchaudio 2.5.1 from the matching ROCm 6.2, CUDA 12.4 or CPU index;
   5. installs `audio-separator`, `g2p_en` and `nltk`;
   6. installs the LyricLoom wheel bundled with the app (no dependencies);
   7. probes the interpreter and its imports.
4. If the probe passes, the app saves the WSL settings; restart LyricLoom. If the setup fails or is
   cancelled, the settings are not changed and partial downloads stay for a later retry.
5. The default distro is **Ubuntu 24.04** when no WSL 2 distro exists yet. The script only uses
   `sudo` for `apt`; the Python environment belongs to your normal Linux user.

The script installs the MTL Python packages but not the MTL code and checkpoint. To run the English
singing model on the GPU, also copy its code and checkpoint into the distro as described in
[Models: copy or point](#6-models-copy-or-point), or set `wsl_mtl_repo` and `wsl_mtl_checkpoint` to
where they already are.

### Faster transcription

The **Faster transcription** section installs an official whisper.cpp Windows build or selects the
bundled one:

- **whisper.cpp BLAS (faster CPU)** — about 20 MB, speeds up CPU transcription on any machine;
- **whisper.cpp cuBLAS (NVIDIA GPU only)** — about 670 MB, needs a current NVIDIA driver;
- **Use the bundled whisper.cpp** — clears the custom `whisper_cli` setting.

The download is pinned by size and SHA-256, extracted safely to
`%LOCALAPPDATA%\LyricLoom\backends\whisper-<name>`, and tested with `whisper-cli.exe --help` before it
is selected. This is separate from the ROCm path: transcription stays on Windows.

### What the assistant writes

| Setting | Meaning |
|---|---|
| `wsl_gpu` | Turns the WSL path on. Read at app start-up; restart after changing it. |
| `wsl_distro` | Exact distro name, for example `Ubuntu` or `Ubuntu-24.04`. |
| `wsl_python` | Absolute interpreter path inside the distro, normally `/opt/lyricloom/venv/bin/python`. |

The assistant does not change `wsl_env`, `wsl_hsa_override`, `wsl_torch_home`, `wsl_models_dir`,
`wsl_mtl_repo` or `wsl_mtl_checkpoint`. Those remain editable in **Settings** and `settings.json`.

### If the assistant cannot finish

- If **Set up WSL…** is disabled, the build does not contain the WSL wheel (a source checkout does
  not). Use the manual path below.
- If the log ends with missing ROCm, install AMD's ROCm-on-WSL stack and the Windows AMD driver, then
  retry.
- If the environment is created but the probe fails, open the log and check the package or GPU error;
  a partial environment can be repaired by running the setup again or by following the manual steps.
- To go back to the CPU path, clear **Run separation and forced alignment in WSL** in **Settings** or
  set `"wsl_gpu": false`.

## Supported AMD GPUs

WSL GPU acceleration needs:

- a Windows AMD driver that supports WSL (install the current Adrenalin driver on Windows, not a
  Linux driver);
- WSL 2 with GPU paravirtualization;
- a ROCm release that supports your GPU.

AMD's support matrix changes over time. Check it before buying or installing:

- **Radeon RX 7000 series (RDNA 3):** supported by current ROCm releases on WSL, subject to AMD's
  list.
- **Radeon RX 9000 series (RDNA 4):** support depends on the ROCm release; check AMD's current
  matrix.
- **Radeon RX 6000 series (RDNA 2):** some cards work with `HSA_OVERRIDE_GFX_VERSION`, but they are
  not all officially supported. A card that works today can break after a ROCm upgrade.
- **Radeon Pro W6000/W7000:** check AMD's workstation support list.
- **Integrated Radeon graphics:** not supported by this setup.

**VRAM:** 8 GB or more is recommended for the default separator settings. 6 GB may work; close
games, browsers and video players before a long queue. The separator uses batch size 1 and a segment
size of 256 by default.

**Windows version:** Windows 11 is recommended. GPU paravirtualization is also available on Windows
10 21H2 or newer, but the WSL/ROCm documentation and drivers are primarily tested on Windows 11.

## Manual setup (advanced)

Use this if you already have a WSL environment or want to control every package. The commands use
`Ubuntu` as the distro name; substitute the exact name from `wsl -l -q`.

### 1. Install or update WSL 2

Open **PowerShell as Administrator**.

For a new installation:

```powershell
wsl --install -d Ubuntu
```

Restart Windows when asked. After the restart, Ubuntu opens and asks for a Linux user name and
password. Use a normal user account; do not run the whole setup as root.

For an existing WSL installation:

```powershell
wsl --update
wsl --set-default-version 2
wsl --shutdown
```

Check the result:

```powershell
wsl -l -v
```

The Ubuntu distro must show `VERSION 2`. If it shows `1`, convert it:

```powershell
wsl --set-version Ubuntu 2
```

Install the current **AMD Software: Adrenalin Edition** driver for your GPU from AMD. This is the
Windows driver that exposes the GPU to WSL. Do not install a Linux `amdgpu` driver on Windows, and do
not install the Windows driver inside Ubuntu. Reboot Windows after the driver installation.

Verify that WSL can see the GPU:

```powershell
wsl -d Ubuntu -- ls -l /dev/dri
```

You should see `card0` and `renderD128` (the numbers may differ). If `/dev/dri` is empty, the Windows
driver or WSL GPU support is not working; fix that before continuing.

### 2. Install ROCm inside Ubuntu

The exact package URL changes with ROCm releases. Follow AMD's **"Install ROCm on WSL"** guide for
your Ubuntu version and download the current `amdgpu-install` package from AMD's repository. The
commands below show the shape of the installation; substitute the package file you downloaded.

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y wget gnupg

# Download the current amdgpu-install package for Ubuntu from AMD's repository.
sudo apt install ./amdgpu-install_*.deb

sudo amdgpu-install --usecase=wsl,rocm --no-dkms
```

`--no-dkms` is important in WSL: the kernel driver comes from Windows, not from a Linux DKMS module.

Add your user to the GPU groups:

```bash
sudo usermod -aG render,video "$USER"
```

Close the Ubuntu shell, then restart WSL from PowerShell so the group change takes effect:

```powershell
wsl --shutdown
wsl -d Ubuntu
```

Verify inside Ubuntu:

```bash
rocminfo
```

`rocminfo` should list your GPU and a `gfx` target such as `gfx1030` or `gfx1100`. If it only shows
the CPU, ROCm is not seeing the GPU. Check the Windows driver, the WSL version and AMD's
supported-GPU list before continuing.

Some cards also need an architecture override. You can test it temporarily:

```bash
export HSA_OVERRIDE_GFX_VERSION=10.3.0
rocminfo | grep gfx
```

Use the value for your GPU. `10.3.0` is the common override for `gfx1030` (RDNA 2); do not apply it
to a card that ROCm already recognizes unless AMD's documentation says to.

### 3. Create the Python environment in `/opt/lyricloom/venv`

```bash
sudo apt install -y python3 python3-venv python3-pip ffmpeg git

sudo mkdir -p /opt/lyricloom
sudo chown "$USER":"$USER" /opt/lyricloom

python3 -m venv /opt/lyricloom/venv
/opt/lyricloom/venv/bin/pip install --upgrade pip wheel
```

Using `chown` means the rest of the setup does not need `sudo` for every `pip` command, and the
worker runs as your user.

### 4. Install ROCm PyTorch

The bundled setup script pins **torch/torchaudio 2.5.1** with the ROCm 6.2 index. A manual install
can use a different compatible pair; use the index for your installed ROCm release:

```bash
/opt/lyricloom/venv/bin/pip install torch==2.5.1 torchaudio==2.5.1 \
  --index-url https://download.pytorch.org/whl/rocm6.2
```

For NVIDIA, the script uses CUDA 12.4:

```bash
/opt/lyricloom/venv/bin/pip install torch==2.5.1 torchaudio==2.5.1 \
  --index-url https://download.pytorch.org/whl/cu124
```

Verify **inside WSL**:

```bash
/opt/lyricloom/venv/bin/python - <<'PY'
import torch
print("torch", torch.__version__)
print("cuda available", torch.cuda.is_available())
if torch.cuda.is_available():
    print("device", torch.cuda.get_device_name(0))
PY
```

If `cuda available` is `False`:

1. Check `rocminfo` again.
2. Check that you are using `/opt/lyricloom/venv/bin/python`, not the system Python.
3. Check the `render`/`video` groups and restart WSL.
4. Try the `HSA_OVERRIDE_GFX_VERSION` value for your GPU.
5. Reinstall torch and torchaudio together; do not mix a ROCm torch with a CPU torchaudio.

### 5. Install audio-separator, the MTL packages and LyricLoom

```bash
/opt/lyricloom/venv/bin/pip install "audio-separator>=0.40" g2p_en nltk
```

`g2p_en` and `nltk` are needed by the English singing model. The `audio-separator` install uses the
PyTorch already present; if pip offers to reinstall torch, stop and check the versions.

The WSL worker needs the `lyricloom` Python package so it can run
`python -m lyricloom.workers.separate`. The Windows app does not copy its Python package into WSL.
Install the wheel bundled with the app, or install a source checkout **without dependencies** so it
does not replace torch:

```bash
git clone --depth 1 https://github.com/nishizumi-maho/lyricloom.git /opt/lyricloom/src
/opt/lyricloom/venv/bin/pip install --no-deps /opt/lyricloom/src
```

If the distro's Python is not 3.11, add `--ignore-requires-python` to that last command:

```bash
/opt/lyricloom/venv/bin/pip install --no-deps --ignore-requires-python /opt/lyricloom/src
```

The project's `>=3.11,<3.12` pin is for the Windows app and its pinned dependencies. The worker uses
the venv's own torch, torchaudio and audio-separator, and it can run on a newer Python when the
package metadata is ignored. The bundled setup script does the same with the wheel it ships.

For an editable source checkout, use the same options:

```bash
/opt/lyricloom/venv/bin/pip install --no-deps --ignore-requires-python -e /mnt/c/path/to/lyricloom
```

Verify the worker imports **from outside the source tree**. The installed app starts workers in its
data folder, not in a checkout. A check run inside the checkout passes even when the package is not
installed, because Python finds `lyricloom` in the current directory:

```bash
cd /tmp && /opt/lyricloom/venv/bin/python -c "import lyricloom, torch, torchaudio, audio_separator; print('worker imports ok')"
```

### 6. Models: copy or point

The Windows app and the WSL worker share some files by path; others are faster inside the Linux
filesystem. **LyricLoom prefers a copy inside the distro when its size matches the catalog and falls
back to the Windows path through `/mnt`.** Loading through `/mnt` works but is slower.

#### Separator model

Keep the Windows copy, or copy the `separator` folder into the distro and set `wsl_models_dir` to
that directory. Inside the distro it should contain the checkpoint, its YAML and
`download_checks.json`:

```text
<wsl_models_dir>/
├── vocals_mel_band_roformer.ckpt
├── vocals_mel_band_roformer.yaml
└── download_checks.json
```

Leaving `wsl_models_dir` empty uses the Windows models folder through `/mnt`. The app's Models
window can download the Windows copy; a source/pipx install can use:

```powershell
lyricloom models download separator
```

#### MMS_FA checkpoint

The MMS_FA checkpoint lives under `$TORCH_HOME/hub/checkpoints`. LyricLoom sets `TORCH_HOME` from
`wsl_torch_home`, which defaults to `/opt/lyricloom/models/torch`. The catalog file is `model.pt`
(not a `*.pth` file). Download it inside WSL:

```bash
export TORCH_HOME=/opt/lyricloom/models/torch
/opt/lyricloom/venv/bin/python - <<'PY'
import torchaudio
torchaudio.pipelines.MMS_FA.get_model(with_star=False)
print("MMS_FA ready")
PY
```

Or copy the verified file from the Windows models folder:

```bash
sudo mkdir -p /opt/lyricloom/models/torch/hub/checkpoints
sudo cp "/mnt/c/Users/<user>/AppData/Local/LyricLoom/models/torch/hub/checkpoints/model.pt" \
  /opt/lyricloom/models/torch/hub/checkpoints/model.pt
sudo chown -R "$USER":"$USER" /opt/lyricloom/models/torch
```

#### LyricsAlignment-MTL code and checkpoint

The English singing model needs:

- the inference code (`model.py`, `utils.py`, `wrapper.py`) in `wsl_mtl_repo`;
- the checkpoint at `<wsl_mtl_checkpoint>/checkpoints/checkpoint_MTL`.

The `wsl_mtl_checkpoint` value is a **directory**, not the checkpoint file. Copy the code from the
checkout or from the installed wheel's `lyricloom/vendor/mtl` folder, and copy a verified checkpoint:

```bash
sudo mkdir -p /opt/lyricloom/mtl /opt/lyricloom/models/mtl/checkpoints
sudo cp /opt/lyricloom/src/lyricloom/vendor/mtl/*.py /opt/lyricloom/mtl/
sudo cp "/mnt/c/Users/<user>/AppData/Local/LyricLoom/models/mtl/checkpoints/checkpoint_MTL" \
  /opt/lyricloom/models/mtl/checkpoints/checkpoint_MTL
sudo chown -R "$USER":"$USER" /opt/lyricloom/mtl /opt/lyricloom/models/mtl
```

If you do not have the Windows checkpoint yet, download it with the Models window or
`lyricloom models download mtl`. The checkpoint is small (about 66 MB). The code copy is needed
because the worker changes into the checkpoint directory and imports `wrapper` from
`wsl_mtl_repo`.

#### NLTK data for the singing model

`g2p_en` needs `cmudict`, `averaged_perceptron_tagger`, `averaged_perceptron_tagger_eng`, `punkt`
and `punkt_tab`. The app downloads pinned copies into the Windows models root; the WSL worker reads
that folder through `NLTK_DATA`, so a copy inside the distro is optional. To keep them locally,
install them as the same Linux user that runs the worker (not with `sudo`):

```bash
/opt/lyricloom/venv/bin/python -m nltk.downloader \
  cmudict averaged_perceptron_tagger averaged_perceptron_tagger_eng punkt punkt_tab
```

They go to `~/nltk_data` by default. The worker never downloads NLTK data on its own; an offline
machine needs the corpora present.

### 7. Configure LyricLoom

Close LyricLoom. Open this file in a text editor:

```text
%LOCALAPPDATA%\LyricLoom\settings.json
```

Add the WSL settings. The file is JSON, so Windows backslashes in the library path must be doubled:

```json
{
  "library": "D:\\Music",
  "wsl_gpu": true,
  "wsl_distro": "Ubuntu",
  "wsl_python": "/opt/lyricloom/venv/bin/python",
  "wsl_torch_home": "/opt/lyricloom/models/torch",
  "wsl_models_dir": "/opt/lyricloom/models/separator",
  "wsl_hsa_override": "10.3.0",
  "wsl_mtl_repo": "/opt/lyricloom/mtl",
  "wsl_mtl_checkpoint": "/opt/lyricloom/models/mtl"
}
```

Keep any other keys already in the file. The important keys:

| Key | Meaning |
|---|---|
| `wsl_gpu` | `true` turns on the WSL path for separation, alignment and the MTL attempt. It is read when the app starts, so restart LyricLoom after changing it. |
| `wsl_distro` | Exact distro name from `wsl -l -q`, for example `Ubuntu` or `Ubuntu-22.04`. |
| `wsl_python` | Absolute path to the Python interpreter inside the distro. `/opt/lyricloom/venv/bin/python` is the recommended path. |
| `wsl_torch_home` | Directory for torchaudio's cache. MMS_FA is under `<wsl_torch_home>/hub/checkpoints`. Defaults to `/opt/lyricloom/models/torch`. |
| `wsl_models_dir` | Optional. Directory inside the distro containing the separator checkpoint, YAML and `download_checks.json`. Empty means the Windows models folder is read through `/mnt`. |
| `wsl_hsa_override` | Optional `HSA_OVERRIDE_GFX_VERSION` value, for example `10.3.0` for some RDNA 2 cards. Remove the key if your GPU does not need it. |
| `wsl_mtl_repo` | Directory containing `wrapper.py`, `model.py` and `utils.py`. Defaults to `/opt/lyricloom/mtl`. |
| `wsl_mtl_checkpoint` | Directory containing `checkpoints/checkpoint_MTL`. Defaults to `/opt/lyricloom/models/mtl`. |

#### Optional `wsl_env`

If AMD's documentation asks for extra environment variables, add them as an object:

```json
{
  "wsl_gpu": true,
  "wsl_distro": "Ubuntu",
  "wsl_python": "/opt/lyricloom/venv/bin/python",
  "wsl_env": {
    "HSA_ENABLE_SDMA": "0"
  }
}
```

Variables in `wsl_env` are passed to every WSL worker. `wsl_hsa_override` is a shortcut for
`HSA_OVERRIDE_GFX_VERSION`.

These keys are also editable in **Settings**; the WSL section writes the same `settings.json` values.
Restart LyricLoom after changing them. You can still edit `settings.json` by hand with a JSON-aware
editor; keep the commas valid. If the file is malformed, LyricLoom falls back to defaults.

### 8. Verify

From Windows, in a source or pipx install:

```powershell
lyricloom doctor
```

The packaged GUI has no console command; use **Help > Diagnostics…** and the direct WSL test below.
Expected with `wsl_gpu` enabled:

```text
wsl enabled    True
wsl distro     Ubuntu
wsl python     /opt/lyricloom/venv/bin/python
```

`torch ... (cuda=False)` on the Windows side is normal: the Windows PyTorch is CPU-only. The GPU is
used by the WSL interpreter.

Verify the WSL runtime directly:

```powershell
wsl -d Ubuntu -- /opt/lyricloom/venv/bin/python -c "import torch, torchaudio, audio_separator, g2p_en, nltk, lyricloom; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Then process one song. The status bar should show:

```text
Device: ROCm (WSL Ubuntu)
```

If it shows `Device: CPU (fallback)` in orange, hover the label for the reason and open the track
log:

```text
%LOCALAPPDATA%\LyricLoom\work\<hash>\log.txt
```

Common causes are a wrong `wsl_distro`, a missing interpreter, a missing `lyricloom` package in the
venv, a missing separator checkpoint, or `torch.cuda.is_available()` being false inside WSL.

`No module named 'lyricloom'` in the reason means the package is not installed in the venv (step 5).
It can appear only in the installed app and not in a source run: a source run starts workers in the
checkout, where Python finds the package without it being installed.

`lyricloom doctor` checks the **Windows** model cache for MMS_FA. A checkpoint that exists only in
`wsl_torch_home` will not make the Windows check turn green, but WSL alignment can still work. The
direct WSL import test above is the authoritative check for the Linux side.

## Performance notes

- **Separation is the big win.** On a CPU, separating a full song can take many times the song's
  length. On a supported GPU it is usually a small number of minutes, often under a minute for a
  short track. Actual times depend on the GPU, the song length, the separator overlap and thermals.
- **The first song is slower.** The separator and alignment models are loaded into memory, and the
  first run may compile kernels.
- **`/mnt` is slower than a Linux filesystem.** The audio is read from Windows drives through `/mnt`.
  This is convenient and avoids duplicating the library, but a local SSD and a fast Windows drive
  help. Copy the separator, MMS and MTL files into the distro when loading speed matters.
- **One song at a time.** LyricLoom processes a queue serially. Running two songs at once would
  compete for VRAM and usually make the queue slower.
- **VRAM.** Close games, browsers with hardware acceleration and video players. If separation runs
  out of memory, lower the separator overlap (`LYRICLOOM_SEPARATOR_OVERLAP`) or use the CPU path.
- **Overlap.** The default overlap is 2. Increasing it can improve separation at the edges but costs
  time and memory. `LYRICLOOM_SEPARATOR_OVERLAP` changes it.
- **CPU threads.** `LYRICLOOM_CPU_THREADS` caps the thread pools used by the workers. The default is
  the logical CPU count minus two, capped at 16.
- **MTL is partly CPU-bound.** The singing model's Viterbi decode is pure Python and stays on the CPU
  inside the worker. The GPU helps the acoustic model, but the decode can dominate.

## Uninstall or roll back

### Go back to CPU processing

1. Close LyricLoom.
2. Set `"wsl_gpu": false` in `settings.json`, or clear the WSL option in **Settings**.
3. Start LyricLoom again.

The app will use the Windows CPU path. You can leave the WSL environment installed; it is only used
when `wsl_gpu` is true.

### Remove the Linux environment

Inside Ubuntu:

```bash
rm -rf /opt/lyricloom
```

This removes the venv, the worker source and the Linux-side MMS/MTL models. It does not remove the
Windows app, the Windows models, your music or the `.lrc` files.

### Remove the distro

Only if you do not use Ubuntu for anything else:

```powershell
wsl --unregister Ubuntu
```

This **deletes the entire distro**, including files you created there. It cannot be undone.

### Remove ROCm

Use AMD's uninstall instructions for the `amdgpu-install` package. Do not remove the Windows AMD
driver if you still want GPU acceleration in Windows; that driver is separate from the Linux ROCm
packages.

### Troubleshooting a broken ROCm upgrade

If a ROCm or PyTorch upgrade breaks the worker, reinstall a known-good pair inside the venv:

```bash
/opt/lyricloom/venv/bin/pip install --force-reinstall torch==2.5.1 torchaudio==2.5.1 \
  --index-url https://download.pytorch.org/whl/rocm6.2
```

Then repeat the `torch.cuda.is_available()` check. If the GPU is no longer visible after a Windows
driver update, reboot Windows and run `wsl --shutdown` before retrying.

For general failures, see [docs/troubleshooting.md](troubleshooting.md#wsl) and
[docs/models.md](models.md).
