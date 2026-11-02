# Creates .venv with Python 3.11 and installs LyricLoom in editable mode with
# test/build extras.  The CPU wheels are intentional: public builds use
# torch 2.4.1 CPU and must not accidentally pick a CUDA wheel.
param(
    [switch]$NoFfmpegShim
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venv = Join-Path $root '.venv'
$python = Join-Path $venv 'Scripts\python.exe'

if (-not (Test-Path $python)) {
    if (Test-Path $venv) {
        throw "$venv exists but does not contain a Python interpreter. Remove it and re-run this script."
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        Write-Host 'Creating .venv with Python 3.11...'
        & py -3.11 -m venv $venv
    } else {
        Write-Host 'Creating .venv with python on PATH (Python 3.11 required)...'
        & python -m venv $venv
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $python)) {
        throw 'Could not create the virtual environment. Install Python 3.11 x64 and try again.'
    }
}

$version = (& $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($version -ne '3.11') {
    throw "The virtual environment uses Python $version; LyricLoom requires Python 3.11. Remove .venv and re-run this script."
}

& $python -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }

Write-Host 'Installing CPU-only torch/torchaudio...'
& $python -m pip install "torch==2.4.1" "torchaudio==2.4.1" --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw 'torch installation failed.' }

Write-Host 'Installing LyricLoom in editable mode with dev extras...'
& $python -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw 'editable install failed.' }

& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'pip check reported a dependency conflict.' }

if (-not $NoFfmpegShim) {
    # audio-separator invokes `ffmpeg`; expose imageio-ffmpeg's static binary in
    # the venv only, so the developer's system PATH is untouched.
    try {
        $ffmpeg = (& $python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())").Trim()
        if ($LASTEXITCODE -eq 0 -and $ffmpeg) {
            Copy-Item $ffmpeg (Join-Path $venv 'Scripts\ffmpeg.exe') -Force
            Write-Host "ffmpeg shim installed: $venv\Scripts\ffmpeg.exe"
        }
    } catch {
        Write-Warning 'imageio-ffmpeg was not available; audio-separator may need ffmpeg on PATH.'
    }
}

Write-Host ''
Write-Host 'Development environment ready.'
Write-Host "  GUI:  $(Join-Path $venv 'Scripts\lyricloom-app.exe')"
Write-Host "  CLI:  $(Join-Path $venv 'Scripts\lyricloom.exe')"
Write-Host 'Models are downloaded by the app on first use; they are not installed by this script.'
