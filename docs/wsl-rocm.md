# AMD GPUs on Windows with WSL 2 and ROCm

LyricLoom is a Windows application, but the heavy audio stages can run on an AMD GPU inside **WSL 2** using **ROCm**. The app stays on Windows; only the vocal separator and the forced-alignment workers cross into Linux.

This page is a complete, generic setup guide. It does not assume any particular Radeon model, Linux user name, drive letter or install path.

## Why WSL?

AMD's ROCm stack is primarily a Linux userspace. Native ROCm for Windows does not cover the PyTorch/audio-separator combination LyricLoom uses. WSL 2 with GPU paravirtualization gives the Linux ROCm userspace access to the Windows AMD driver, so the same PyTorch code can use the GPU without a second computer or a dual-boot.

What runs where:

| Stage | Where it runs with WSL/ROCm enabled |
|---|---|
| Library scan, lyrics search, writing `.lrc` | Windows |
| Whisper transcription (`whisper-cli`) | Windows, using the installed build (Vulkan if available; the release installer ships CPU) |
| Vocal separation (Mel-Band RoFormer) | WSL 2 / ROCm |
| MMS_FA forced alignment | WSL 2 / ROCm |
| English singing model (LyricsAlignment-MTL) | WSL 2 / ROCm |

If WSL, the distro or its Python environment is unavailable, LyricLoom falls back to the CPU and continues. The status bar shows `Device: CPU (fallback)` in orange and the reason is written to the track's `log.txt`.

## Supported AMD GPUs

WSL GPU acceleration needs:

- A Windows AMD driver that supports WSL (install the current Adrenalin driver on Windows, not a Linux driver).
- WSL 2 with GPU paravirtualization.
- A ROCm release that supports your GPU.

AMD's support matrix changes over time. Check it before buying or installing:

- **Radeon RX 7000 series (RDNA 3):** supported by current ROCm releases on WSL, subject to AMD's list.
- **Radeon RX 9000 series (RDNA 4):** support depends on the ROCm release; check AMD's current matrix.
- **Radeon RX 6000 series (RDNA 2):** some cards work with `HSA_OVERRIDE_GFX_VERSION`, but they are not all officially supported. A card that works today can break after a ROCm upgrade.
- **Radeon Pro W6000/W7000:** check AMD's workstation support list.
- **Integrated Radeon graphics:** not supported by this setup.

**VRAM:** 8 GB or more is recommended for the default separator settings. 6 GB may work; close games, browsers and video players before a long queue. The separator uses batch size 1 and a segment size of 256 by default.

**Windows version:** Windows 11 is recommended. GPU paravirtualization is also available on Windows 10 21H2 or newer, but the WSL/ROCm documentation and drivers are primarily tested on Windows 11.

## 1. Install or update WSL 2

Open **PowerShell as Administrator**.

For a new installation:

```powershell
wsl --install -d Ubuntu
```

Restart Windows when asked. After the restart, Ubuntu opens and asks for a Linux user name and password. Use a normal user account; do not run the whole setup as root.

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

The distro name is used later in `wsl_distro`. In the examples below it is `Ubuntu`; use the exact name from `wsl -l -q` if yours is different.

### Install the Windows AMD driver

Install the current **AMD Software: Adrenalin Edition** driver for your GPU from AMD. This is the Windows driver that exposes the GPU to WSL. Do not install a Linux `amdgpu` driver on Windows, and do not install the Windows driver inside Ubuntu.

Reboot Windows after the driver installation.

Verify that WSL can see the GPU:

```powershell
wsl -d Ubuntu -- ls -l /dev/dri
```

You should see `card0` and `renderD128` (the numbers may differ). If `/dev/dri` is empty, the Windows driver or WSL GPU support is not working; fix that before continuing.

## 2. Install ROCm inside Ubuntu

The exact package URL changes with ROCm releases. Follow AMD's **"Install ROCm on WSL"** guide for your Ubuntu version and download the current `amdgpu-install` package from AMD's repository. The commands below show the shape of the installation; substitute the package file you downloaded.

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y wget gnupg

# Download the current amdgpu-install package for Ubuntu from AMD's repository
# (see AMD's ROCm WSL installation guide for the exact file).
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

`rocminfo` should list your GPU and a `gfx` target such as `gfx1030` or `gfx1100`. If it only shows the CPU, ROCm is not seeing the GPU. Check the Windows driver, the WSL version and AMD's supported-GPU list before continuing.

Some cards also need an architecture override. You can test it temporarily:

```bash
export HSA_OVERRIDE_GFX_VERSION=10.3.0
rocminfo | grep gfx
```

Use the value for your GPU. `10.3.0` is the common override for `gfx1030` (RDNA 2); do not apply it to a card that ROCm already recognizes unless AMD's documentation says to.

## 3. Create the Python environment in `/opt/lyricloom/venv`

LyricLoom expects a Linux Python environment that can import `torch`, `torchaudio`, `audio_separator` and the `lyricloom` worker package. The recommended path is `/opt/lyricloom/venv`. The examples below use it consistently.

```bash
sudo apt install -y python3 python3-venv python3-pip ffmpeg git

sudo mkdir -p /opt/lyricloom
sudo chown "$USER":"$USER" /opt/lyricloom

python3 -m venv /opt/lyricloom/venv
/opt/lyricloom/venv/bin/pip install --upgrade pip wheel
```

Using `chown` means the rest of the setup does not need `sudo` for every `pip` command, and the worker runs as your user.

## 4. Install ROCm PyTorch

Install a ROCm build of PyTorch and torchaudio from the PyTorch wheel index that matches your ROCm version. For example, for ROCm 6.2:

```bash
/opt/lyricloom/venv/bin/pip install torch torchaudio \
  --index-url https://download.pytorch.org/whl/rocm6.2
```

Use the index for your installed ROCm release. LyricLoom 2.0.0's Windows environment pins torch 2.4.1, but the WSL worker only needs a compatible torch/torchaudio pair that audio-separator supports.

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

## 5. Install audio-separator and the LyricLoom worker package

```bash
/opt/lyricloom/venv/bin/pip install "audio-separator[cpu]>=0.40"
```

The `[cpu]` extra installs the CPU ONNX runtime. It does not replace the ROCm PyTorch you just installed; audio-separator's `torch` requirement is already satisfied. If pip offers to reinstall torch, stop and check the versions.

The WSL worker needs the `lyricloom` Python package so it can run `python -m lyricloom.workers.separate`. The Windows app does not automatically copy its Python package into WSL. Install the package **without dependencies** so it does not replace torch:

```bash
git clone --depth 1 https://github.com/nishizumi-maho/lyricloom.git /opt/lyricloom/src
/opt/lyricloom/venv/bin/pip install --no-deps --ignore-requires-python /opt/lyricloom/src
```

`--ignore-requires-python` is needed when the venv uses a Python other than 3.11, for example Ubuntu 24.04's Python 3.12. The project's `>=3.11,<3.12` pin is for the Windows app and its pinned dependencies. The worker uses only the venv's own torch, torchaudio and audio-separator, and it runs on Python 3.12.

If you already have a source checkout, install that path instead. `-e` keeps the worker in step with the checkout, so you do not reinstall after every change:

```bash
/opt/lyricloom/venv/bin/pip install --no-deps --ignore-requires-python -e /mnt/c/path/to/lyricloom
```

Verify the worker imports **from outside the source tree**. The installed app starts workers in its data folder, not in a checkout. A check run inside the checkout passes even when the package is not installed, because Python finds `lyricloom` in the current directory:

```bash
cd /tmp && /opt/lyricloom/venv/bin/python -c "import lyricloom, torch, torchaudio, audio_separator; print('worker imports ok')"
```

## 6. Models: copy or point

LyricLoom uses several model files. The Windows app and the WSL worker share some of them by path; others must exist inside the Linux filesystem. The settings below control the Linux paths.

### Separator model (Mel-Band RoFormer)

The separator checkpoint is passed from the Windows models folder and read through `/mnt/<drive>`. Keep this file in the Windows models directory:

```text
%LOCALAPPDATA%\LyricLoom\models\separator\vocals_mel_band_roformer.ckpt
```

Download it with the Windows app's Models window (Help > Models), or from a source/pipx install with:

```powershell
lyricloom models download separator
```

If loading it through `/mnt` is slow, copy the `separator` folder into the distro and set `wsl_models_dir` in **File > Settings** (or in `settings.json`) to that directory. It is optional; leaving it empty uses the Windows path through `/mnt`.

### MMS_FA alignment checkpoint

The MMS_FA checkpoint is cached by torchaudio under `$TORCH_HOME/hub/checkpoints`. LyricLoom sets `TORCH_HOME` from `wsl_torch_home`, which defaults to `/opt/lyricloom/models/torch`.

Download it once inside WSL:

```bash
export TORCH_HOME=/opt/lyricloom/models/torch
/opt/lyricloom/venv/bin/python - <<'PY'
import torchaudio
torchaudio.pipelines.MMS_FA.get_model(with_star=False)
print("MMS_FA ready")
PY
```

Or copy the checkpoint from the Windows cache:

```bash
sudo mkdir -p /opt/lyricloom/models/torch/hub/checkpoints
sudo cp /mnt/c/Users/YOUR_USER/AppData/Local/LyricLoom/models/torch/hub/checkpoints/*.pth \
  /opt/lyricloom/models/torch/hub/checkpoints/
sudo chown -R "$USER":"$USER" /opt/lyricloom/models/torch
```

The exact checkpoint filename is owned by torchaudio; copying all `*.pth` files from the Windows cache is the simplest way to reuse it.

### LyricsAlignment-MTL code and checkpoint

The English singing model needs:

- the inference code (`model.py`, `utils.py`, `wrapper.py`) in `wsl_mtl_repo`;
- the checkpoint at `<wsl_mtl_checkpoint>/checkpoints/checkpoint_MTL`.

The `wsl_mtl_checkpoint` value is a **directory**, not the checkpoint file.

```bash
sudo mkdir -p /opt/lyricloom/mtl /opt/lyricloom/models/mtl/checkpoints
sudo cp /opt/lyricloom/src/lyricloom/vendor/mtl/*.py /opt/lyricloom/mtl/
sudo cp /mnt/c/Users/YOUR_USER/AppData/Local/LyricLoom/models/mtl/checkpoints/checkpoint_MTL \
  /opt/lyricloom/models/mtl/checkpoints/
sudo chown -R "$USER":"$USER" /opt/lyricloom/mtl /opt/lyricloom/models/mtl
```

If you do not have the Windows checkpoint yet, download it with the Models window, or from a source/pipx install with:

```powershell
lyricloom models download mtl
```

The checkpoint is small (about 66 MB). The code copy is needed because the worker changes into the checkpoint directory and imports `wrapper` from `wsl_mtl_repo`.

### NLTK data for the singing model

`g2p_en` uses three small NLTK corpora. Install them as the same Linux user that runs the worker (not with `sudo`):

```bash
/opt/lyricloom/venv/bin/python -m nltk.downloader \
  cmudict averaged_perceptron_tagger punkt
```

They go to `~/nltk_data` by default. The worker also tries to download missing corpora on first use, but an offline machine needs them present.

## 7. Configure LyricLoom

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
| `wsl_gpu` | `true` turns on the WSL/ROCm path for separation and forced alignment. It is read when the app starts, so restart LyricLoom after changing it. |
| `wsl_distro` | Exact distro name from `wsl -l -q`, for example `Ubuntu` or `Ubuntu-22.04`. |
| `wsl_python` | Absolute path to the Python interpreter inside the distro. `/opt/lyricloom/venv/bin/python` is the recommended path. |
| `wsl_torch_home` | Directory for torchaudio's cache. The MMS_FA checkpoint is under `<wsl_torch_home>/hub/checkpoints`. Defaults to `/opt/lyricloom/models/torch`. |
| `wsl_models_dir` | Optional. Directory inside the distro containing `vocals_mel_band_roformer.ckpt` and its YAML. Empty means the Windows models folder is read through `/mnt`. |
| `wsl_hsa_override` | Optional `HSA_OVERRIDE_GFX_VERSION` value, for example `10.3.0` for some RDNA 2 cards. Remove the key if your GPU does not need it. |
| `wsl_mtl_repo` | Directory containing `wrapper.py`, `model.py` and `utils.py`. Defaults to `/opt/lyricloom/mtl`. |
| `wsl_mtl_checkpoint` | Directory containing `checkpoints/checkpoint_MTL`. Defaults to `/opt/lyricloom/models/mtl`. |

### Optional `wsl_env`

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

Variables in `wsl_env` are passed to every WSL worker. `wsl_hsa_override` is a shortcut for `HSA_OVERRIDE_GFX_VERSION`.

These keys are also editable from **File > Settings** in the app; the WSL section writes the same `settings.json` values. Restart LyricLoom after changing them. You can still edit `settings.json` by hand with a JSON-aware editor; keep the commas valid. If the file is malformed, LyricLoom falls back to defaults.

## 8. Verify

From Windows, in a source or pipx install:

```powershell
lyricloom doctor
```

The packaged GUI is a windowed application and does not expose the console command in 2.0.0. If you use it, the status bar and the direct WSL test below are the verification; the Models window handles the Windows-side models.

Expected with `wsl_gpu` enabled:

```text
wsl enabled    True
wsl distro     Ubuntu
wsl python     /opt/lyricloom/venv/bin/python
```

`torch ... (cuda=False)` on the Windows side is normal: the Windows PyTorch is CPU-only. The GPU is used by the WSL interpreter.

Verify the WSL runtime directly:

```powershell
wsl -d Ubuntu -- /opt/lyricloom/venv/bin/python -c "import torch, torchaudio, audio_separator, lyricloom; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Then process one song. The status bar should show:

```text
Device: ROCm (WSL Ubuntu)
```

If it shows `Device: CPU (fallback)` in orange, hover the label for the reason and open the track log:

```text
%LOCALAPPDATA%\LyricLoom\work\<hash>\log.txt
```

Common causes are a wrong `wsl_distro`, a missing interpreter, a missing `lyricloom` package in the venv, a missing separator checkpoint, or `torch.cuda.is_available()` being false inside WSL.

`No module named 'lyricloom'` in the reason means the package is not installed in the venv (step 5). It can appear only in the installed app and not in a source run: a source run starts workers in the checkout, where Python finds the package without it being installed.

Note that `lyricloom doctor` checks the **Windows** model cache for MMS_FA. A checkpoint that exists only in `wsl_torch_home` will not make the Windows check turn green, but the WSL alignment can still work. The direct WSL import test above is the authoritative check for the Linux side.

## 9. Performance notes

- **Separation is the big win.** On a CPU, separating a full song can take many times the song's length. On a supported GPU it is usually a small number of minutes, often under a minute for a short track. Actual times depend on the GPU, the song length, the separator overlap and thermals.
- **The first song is slower.** The separator and alignment models are loaded into memory, and the first run may compile kernels.
- **`/mnt` is slower than a Linux filesystem.** The audio and separator checkpoint are read from Windows drives through `/mnt`. This is convenient and avoids duplicating the library, but a local SSD and a fast Windows drive help. The MMS and MTL files are kept inside the Linux filesystem for the same reason.
- **One song at a time.** LyricLoom processes a queue serially. Running two songs at once would compete for VRAM and usually make the queue slower.
- **VRAM.** Close games, browsers with hardware acceleration and video players. If separation runs out of memory, lower the separator overlap (`LYRICLOOM_SEPARATOR_OVERLAP`) or use the CPU path.
- **Overlap.** The default overlap is 2. Increasing it can improve separation at the edges but costs time and memory. `LYRICLOOM_SEPARATOR_OVERLAP` changes it.
- **CPU threads.** `LYRICLOOM_CPU_THREADS` caps the thread pools used by the workers. The default is one quarter of the logical CPUs.
- **MTL is partly CPU-bound.** The singing model's Viterbi decode is pure Python and stays on the CPU inside the worker. The GPU helps the acoustic model, but the decode can dominate.

## 10. Uninstall or roll back

### Go back to CPU processing

1. Close LyricLoom.
2. Set `"wsl_gpu": false` in `settings.json`, or remove the WSL keys.
3. Start LyricLoom again.

The app will use the Windows CPU path. You can leave the WSL environment installed; it is only used when `wsl_gpu` is true.

### Remove the Linux environment

Inside Ubuntu:

```bash
rm -rf /opt/lyricloom
```

This removes the venv, the worker source, and the Linux-side MMS/MTL models. It does not remove the Windows app, the Windows models, your music or the `.lrc` files.

### Remove the distro

Only if you do not use Ubuntu for anything else:

```powershell
wsl --unregister Ubuntu
```

This **deletes the entire distro**, including files you created there. It cannot be undone.

### Remove ROCm

Use AMD's uninstall instructions for the `amdgpu-install` package. Do not remove the Windows AMD driver if you still want GPU acceleration in Windows; that driver is separate from the Linux ROCm packages.

### Troubleshooting a broken ROCm upgrade

If a ROCm or PyTorch upgrade breaks the worker, reinstall a known-good pair inside the venv:

```bash
/opt/lyricloom/venv/bin/pip install --force-reinstall torch torchaudio \
  --index-url https://download.pytorch.org/whl/rocm6.2
```

Then repeat the `torch.cuda.is_available()` check. If the GPU is no longer visible after a Windows driver update, reboot Windows and run `wsl --shutdown` before retrying.

For general failures, see [docs/troubleshooting.md](troubleshooting.md#wsl) and [docs/models.md](models.md).
