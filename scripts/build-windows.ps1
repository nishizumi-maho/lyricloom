# Builds the Windows release: whisper.cpp helper, PyInstaller one-folder app,
# portable zip, Inno Setup installer and SHA256 files.
#
# Prerequisites:
#   * Python 3.11 x64 and .venv from scripts/setup-dev.ps1
#   * Visual Studio 2022 Build Tools with "Desktop development with C++"
#   * Inno Setup 6 (unless -SkipInstaller is used)
#   * Optional Vulkan SDK (detected automatically; otherwise whisper.cpp is CPU)
#
# Run from anywhere:
#   pwsh -File scripts/build-windows.ps1
#
# Outputs under dist\:
#   LyricLoom\                       PyInstaller one-folder bundle
#   LyricLoom-<version>-win64.zip    portable build
#   LyricLoom-Setup-<version>.exe    installer
#   LyricLoom-Setup.exe              stable name for the auto-updater
#   *.sha256                         checksums
[CmdletBinding()]
param(
    [switch]$Vulkan,
    [switch]$CpuOnly,
    [switch]$ForceWhisper,
    [switch]$SkipWhisper,
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venv = Join-Path $root '.venv'
$python = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw 'Python virtual environment not found. Run scripts/setup-dev.ps1 first.'
}

$pyVersion = (& $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($pyVersion -ne '3.11') {
    throw "The build environment uses Python $pyVersion; LyricLoom requires Python 3.11."
}

$initText = Get-Content (Join-Path $root 'lyricloom\__init__.py') -Raw
if ($initText -notmatch '(?m)^VERSION\s*=\s*"([^"]+)"') {
    throw 'Could not read VERSION from lyricloom/__init__.py.'
}
$version = $Matches[1]

$dist = Join-Path $root 'dist'
$buildDir = Join-Path $root 'build'
$toolsBin = Join-Path $root 'tools\bin'
$whisperSource = Join-Path $root 'tools\src\whisper.cpp'
$whisperCli = Join-Path $toolsBin 'whisper-cli.exe'
$venvScripts = Join-Path $venv 'Scripts'

if ($Vulkan -and $CpuOnly) {
    throw 'Use either -Vulkan or -CpuOnly, not both.'
}

function Get-VulkanSdk {
    if ($env:VULKAN_SDK -and (Test-Path $env:VULKAN_SDK)) {
        return $env:VULKAN_SDK
    }

    $roots = @()
    if ($env:ProgramFiles) { $roots += (Join-Path $env:ProgramFiles 'VulkanSDK') }
    if ($env:LOCALAPPDATA) { $roots += (Join-Path $env:LOCALAPPDATA 'VulkanSDK') }

    foreach ($dir in $roots) {
        if (Test-Path $dir) {
            $sdk = Get-ChildItem -Directory $dir | Sort-Object Name -Descending | Select-Object -First 1
            if ($sdk) { return $sdk.FullName }
        }
    }
    return $null
}

function Get-InnoCompiler {
    $candidates = @()
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
    if (${env:ProgramFiles(x86)}) {
        $candidates += (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe')
    }
    if ($env:ProgramFiles) {
        $candidates += (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
    }
    if ($env:LOCALAPPDATA) {
        $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
    }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
    return $null
}

function Get-SevenZip {
    $cmd = Get-Command 7z.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @()
    if ($env:ProgramFiles) { $candidates += (Join-Path $env:ProgramFiles '7-Zip\7z.exe') }
    if (${env:ProgramFiles(x86)}) {
        $candidates += (Join-Path ${env:ProgramFiles(x86)} '7-Zip\7z.exe')
    }
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Write-Sha256([string]$Path) {
    $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    $name = Split-Path -Leaf $Path
    $hashFile = "${Path}.sha256"
    # LF line ending so the file is directly usable with Linux sha256sum -c.
    [System.IO.File]::WriteAllText(
        $hashFile,
        "$hash  $name`n",
        (New-Object System.Text.ASCIIEncoding)
    )
}

# --------------------------------------------------------------------------- whisper.cpp
$useVulkan = $false
if (-not $CpuOnly) {
    $sdk = Get-VulkanSdk
    if ($sdk) {
        $env:VULKAN_SDK = $sdk
        $useVulkan = $true
    }
}
if ($Vulkan -and -not $useVulkan) {
    throw 'Vulkan was requested but VULKAN_SDK was not found. Install the Vulkan SDK or drop -Vulkan.'
}

$builtWhisper = $false
if ($SkipWhisper) {
    if (-not (Test-Path $whisperCli)) {
        throw "-SkipWhisper was used but $whisperCli does not exist."
    }
} elseif ($ForceWhisper -or -not (Test-Path $whisperCli)) {
    Write-Host "Building whisper.cpp v1.9.5 ($(if ($useVulkan) { 'Vulkan' } else { 'CPU' }))..."

    if (-not (Test-Path $whisperSource)) {
        $git = Get-Command git.exe -ErrorAction SilentlyContinue
        if (-not $git) { throw 'git is required to clone whisper.cpp.' }
        New-Item -ItemType Directory -Force (Split-Path -Parent $whisperSource) | Out-Null
        & git clone --depth 1 --branch v1.9.5 https://github.com/ggml-org/whisper.cpp.git $whisperSource
        if ($LASTEXITCODE -ne 0) { throw 'git clone of whisper.cpp failed.' }
    }

    $cmake = Join-Path $venvScripts 'cmake.exe'
    if (-not (Test-Path $cmake)) {
        Write-Host 'Installing CMake into the virtual environment...'
        & $python -m pip install cmake
        if ($LASTEXITCODE -ne 0) { throw 'Could not install CMake.' }
    }
    if (-not (Test-Path $cmake)) {
        throw 'cmake.exe was not found in .venv\Scripts after installation.'
    }

    $vulkanFlag = if ($useVulkan) { 'ON' } else { 'OFF' }
    $jobs = [Math]::Max(1, [Math]::Min(8, [Environment]::ProcessorCount))
    $whisperBuild = Join-Path $whisperSource 'build'

    & $cmake -S $whisperSource -B $whisperBuild -G 'Visual Studio 17 2022' -A x64 `
        "-DGGML_VULKAN=$vulkanFlag" `
        -DCMAKE_BUILD_TYPE=Release `
        -DBUILD_SHARED_LIBS=ON `
        -DWHISPER_BUILD_TESTS=OFF `
        -DWHISPER_BUILD_EXAMPLES=ON
    if ($LASTEXITCODE -ne 0) {
        throw 'CMake configuration of whisper.cpp failed. Install Visual Studio 2022 Build Tools with C++.'
    }

    & $cmake --build $whisperBuild --config Release --parallel $jobs
    if ($LASTEXITCODE -ne 0) { throw 'whisper.cpp compilation failed.' }

    $builtCli = Get-ChildItem $whisperBuild -Filter 'whisper-cli.exe' -File -Recurse |
        Select-Object -First 1
    if (-not $builtCli) { throw 'whisper-cli.exe was not produced by the whisper.cpp build.' }

    New-Item -ItemType Directory -Force $toolsBin | Out-Null
    Get-ChildItem $toolsBin -File |
        Where-Object { $_.Name -match '^(whisper-cli|whisper\.dll|whisper-|ggml)' } |
        Remove-Item -Force
    Copy-Item $builtCli.FullName $toolsBin -Force
    Get-ChildItem $builtCli.Directory -Filter '*.dll' -File |
        Copy-Item -Destination $toolsBin -Force
    $builtWhisper = $true
}

if (-not (Test-Path $whisperCli)) {
    throw "whisper-cli.exe is still missing from $toolsBin."
}

# --------------------------------------------------------------------------- PyInstaller
& $python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller is not installed. Run scripts/setup-dev.ps1 (it installs the dev extras).'
}

Write-Host "Building LyricLoom $version with PyInstaller..."
New-Item -ItemType Directory -Force $dist | Out-Null
New-Item -ItemType Directory -Force $buildDir | Out-Null
$appDir = Join-Path $dist 'LyricLoom'
if (Test-Path $appDir) { Remove-Item $appDir -Recurse -Force }
$workDir = Join-Path $buildDir 'LyricLoom'
if (Test-Path $workDir) { Remove-Item $workDir -Recurse -Force }

& $python -m PyInstaller --noconfirm --clean --distpath $dist --workpath $buildDir `
    (Join-Path $root 'packaging\pyinstaller\LyricLoom.spec')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

$guiExe = Join-Path $appDir 'LyricLoom.exe'
$workerExe = Join-Path $appDir 'LyricLoomWorker.exe'
if (-not (Test-Path $guiExe)) { throw "Missing $guiExe." }
if (-not (Test-Path $workerExe)) { throw "Missing $workerExe." }
if (-not (Test-Path (Join-Path $appDir '_internal\tools\bin\whisper-cli.exe'))) {
    throw 'whisper-cli.exe was not bundled under _internal\tools\bin.'
}

# --------------------------------------------------------------------------- portable zip
$zipPath = Join-Path $dist "LyricLoom-$version-win64.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Write-Host "Creating $zipPath..."
$sevenZip = Get-SevenZip
if ($sevenZip) {
    Push-Location $dist
    try {
        & $sevenZip a -tzip -mx=5 $zipPath 'LyricLoom' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw '7-Zip failed to create the portable archive.' }
    } finally {
        Pop-Location
    }
} else {
    Write-Warning '7-Zip not found; falling back to Compress-Archive (slower).'
    Compress-Archive -Path $appDir -DestinationPath $zipPath -CompressionLevel Optimal -Force
}
Write-Sha256 $zipPath

# --------------------------------------------------------------------------- installer
if (-not $SkipInstaller) {
    $iscc = Get-InnoCompiler
    if (-not $iscc) {
        throw 'Inno Setup 6 (ISCC.exe) was not found. Install it or pass -SkipInstaller.'
    }
    Write-Host "Compiling the installer with $iscc..."
    & $iscc "/DMyAppVersion=$version" (Join-Path $root 'packaging\windows\LyricLoom.iss')
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed.' }

    $setupVersioned = Join-Path $dist "LyricLoom-Setup-$version.exe"
    if (-not (Test-Path $setupVersioned)) {
        throw "Inno Setup did not produce $setupVersioned."
    }
    $setupStable = Join-Path $dist 'LyricLoom-Setup.exe'
    Copy-Item $setupVersioned $setupStable -Force

    Write-Sha256 $setupVersioned
    Write-Sha256 $setupStable
}

$whisperLabel = if ($builtWhisper) {
    if ($useVulkan) { 'Vulkan' } else { 'CPU' }
} else {
    'prebuilt'
}

Write-Host ''
Write-Host "Windows build complete (whisper.cpp: $whisperLabel)."
Write-Host "  App:     $appDir"
Write-Host "  Portable: $zipPath"
if (-not $SkipInstaller) {
    Write-Host "  Setup:    $setupVersioned"
    Write-Host "  Stable:   $setupStable"
}
