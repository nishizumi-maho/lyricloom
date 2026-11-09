# Builds the plugin, runs the tests and creates the release zip in dist\.
# The zip's contents go straight into MusicBee's Plugins folder.
param([string]$Configuration = 'Release')
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

dotnet test (Join-Path $root 'tests\StarryKaraoke.Tests') -c $Configuration -nologo
if ($LASTEXITCODE -ne 0) { throw 'tests failed' }
dotnet build (Join-Path $root 'src\StarryKaraoke.Recorder\StarryKaraoke.Recorder.csproj') -c $Configuration -nologo
if ($LASTEXITCODE -ne 0) { throw 'build failed' }

# the recorder's output folder holds the plugin and everything it needs
$bin = Join-Path $root "src\StarryKaraoke.Recorder\bin\$Configuration\net48"
$version = (Get-Item "$bin\mb_StarryKaraoke.dll").VersionInfo.FileVersion -replace '\.0$', ''
$dist = Join-Path $root 'dist'
$stage = Join-Path $dist "MusicBee-StarryKaraoke-$version"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force "$stage\RomajiLyrics\IpaDic", "$stage\StarryKaraoke\licenses" | Out-Null

Copy-Item "$bin\mb_StarryKaraoke.dll", "$bin\RomajiCore.dll", "$bin\LibNMeCab.dll",
          "$bin\StarryKaraoke.Recorder.exe", "$bin\StarryKaraoke.Recorder.exe.config" $stage
Copy-Item "$bin\IpaDic\*" "$stage\RomajiLyrics\IpaDic"
Copy-Item (Join-Path $root 'licenses\*') "$stage\StarryKaraoke\licenses"
Copy-Item (Join-Path $root 'README.md') "$stage\StarryKaraoke\README.md"
Copy-Item (Join-Path $root 'LICENSE') "$stage\StarryKaraoke\LICENSE.txt"

$zip = "$stage.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "$stage\*" -DestinationPath $zip
Write-Host "Created $zip"
