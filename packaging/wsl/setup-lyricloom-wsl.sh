#!/usr/bin/env bash
# Sets up a GPU-capable LyricLoom environment inside a WSL 2 distro.
#
# Run it as your normal WSL user: only apt uses sudo.  It never installs or changes GPU drivers or
# the ROCm/CUDA runtime itself; install AMD's ROCm-on-WSL stack first when using --backend rocm.
#
#   bash setup-lyricloom-wsl.sh --backend rocm --wheel /mnt/c/path/lyricloom-2.2.0-py3-none-any.whl
#
# It prints progress as "@@step <n>/<total> <text>" and one final JSON line.
set -euo pipefail

TORCH_VERSION="2.5.1"
ROCM_INDEX="https://download.pytorch.org/whl/rocm6.2"
CUDA_INDEX="https://download.pytorch.org/whl/cu124"
CPU_INDEX="https://download.pytorch.org/whl/cpu"
ROCM_WSL_GUIDE="https://rocm.docs.amd.com/projects/install-on-linux/en/latest/install/3rd-party/wsl-install.html"
VENV="/opt/lyricloom/venv"
TOTAL_STEPS=7

usage() {
    cat <<'EOF'
Usage: setup-lyricloom-wsl.sh --backend rocm|cuda|cpu --wheel <lyricloom wheel>

  --backend rocm   AMD GPU through ROCm (ROCm must already be installed)
  --backend cuda   NVIDIA GPU through CUDA
  --backend cpu    CPU-only PyTorch
  --wheel PATH     The LyricLoom wheel to install (a /mnt/... path is fine)
EOF
}

step() {
    printf '@@step %s/%s %s\n' "$1" "$TOTAL_STEPS" "$2"
}

backend=""
wheel=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --backend)
            [[ $# -ge 2 ]] || { echo "--backend needs a value" >&2; exit 2; }
            backend="$2"
            shift 2
            ;;
        --wheel)
            [[ $# -ge 2 ]] || { echo "--wheel needs a value" >&2; exit 2; }
            wheel="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ "$backend" != "rocm" && "$backend" != "cuda" && "$backend" != "cpu" ]]; then
    echo "--backend must be rocm, cuda or cpu" >&2
    usage >&2
    exit 2
fi
if [[ -z "$wheel" ]]; then
    echo "--wheel is required" >&2
    usage >&2
    exit 2
fi
if [[ ! -f "$wheel" ]]; then
    echo "the LyricLoom wheel does not exist: $wheel" >&2
    exit 2
fi

if [[ "$backend" == "rocm" ]]; then
    if ! command -v rocminfo >/dev/null 2>&1 && [[ ! -x /opt/rocm/bin/rocminfo ]]; then
        cat >&2 <<EOF
ROCm is not installed, so the GPU environment cannot be created.
Install AMD's ROCm stack for WSL 2 first (including the Windows driver), then run this again:
  $ROCM_WSL_GUIDE
EOF
        exit 1
    fi
fi

step 1 "Installing python3-venv and ffmpeg with apt"
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv ffmpeg

step 2 "Creating the Python environment in $VENV"
sudo mkdir -p /opt/lyricloom
sudo chown -R "$(id -u):$(id -g)" /opt/lyricloom
if [[ ! -x "$VENV/bin/python" ]]; then
    python3 -m venv "$VENV"
fi

step 3 "Updating pip, setuptools and wheel"
"$VENV/bin/python" -m pip install --upgrade pip setuptools wheel

step 4 "Installing PyTorch $TORCH_VERSION for $backend"
case "$backend" in
    rocm) index_url="$ROCM_INDEX" ;;
    cuda) index_url="$CUDA_INDEX" ;;
    cpu) index_url="$CPU_INDEX" ;;
esac
"$VENV/bin/pip" install --index-url "$index_url" \
    "torch==$TORCH_VERSION" "torchaudio==$TORCH_VERSION"

step 5 "Installing audio-separator, g2p_en and nltk"
# The separator worker is tested against this release (pyproject.toml pins the same one); it
# accepts the torch installed above (audio-separator 0.47.1 needs torch >=2.3,<3 on Linux).
"$VENV/bin/pip" install "audio-separator==0.47.1" g2p_en nltk

step 6 "Installing the LyricLoom wheel"
"$VENV/bin/pip" install --no-deps --ignore-requires-python "$wheel"

step 7 "Verifying the environment"
"$VENV/bin/python" - "$backend" <<'PY'
import json
import sys

backend = sys.argv[1]
result = {
    "ok": True,
    "backend": backend,
    "python": sys.executable,
    "torch_version": None,
    "gpu_available": False,
    "device_name": None,
    "imports": {},
    "error": None,
}
try:
    import torch

    result["torch_version"] = str(torch.__version__)
    result["gpu_available"] = bool(torch.cuda.is_available())
    if result["gpu_available"]:
        result["device_name"] = str(torch.cuda.get_device_name(0))
        result["backend"] = "rocm" if getattr(torch.version, "hip", None) else "cuda"
except Exception as exc:
    result["ok"] = False
    result["error"] = f"torch: {type(exc).__name__}: {exc}"

for name in ("torchaudio", "audio_separator", "g2p_en", "nltk", "lyricloom"):
    try:
        __import__(name)
        result["imports"][name] = True
    except Exception as exc:
        result["imports"][name] = False
        if result["error"] is None:
            result["error"] = f"{name}: {type(exc).__name__}: {exc}"
if not all(result["imports"].values()):
    result["ok"] = False

print(json.dumps(result))
raise SystemExit(0 if result["ok"] else 1)
PY
