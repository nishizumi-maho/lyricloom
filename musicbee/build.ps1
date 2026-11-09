# Builds the plugin, runs the tests and creates the release zip in dist\.
# The zip's contents go straight into MusicBee's Plugins folder.
param([string]$Configuration = 'Release')
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

$project = Join-Path $root 'src\StarryKaraoke\StarryKaraoke.csproj'
[xml]$projectXml = Get-Content -LiteralPath $project -Raw
$versionNode = $projectXml.SelectSingleNode('//PropertyGroup/Version')
if (-not $versionNode -or -not $versionNode.InnerText.Trim()) {
    throw "Could not read <Version> from $project."
}
$version = $versionNode.InnerText.Trim()

dotnet test (Join-Path $root 'tests\StarryKaraoke.Tests') -c $Configuration -nologo
if ($LASTEXITCODE -ne 0) { throw 'tests failed' }
dotnet build (Join-Path $root 'src\StarryKaraoke.Recorder\StarryKaraoke.Recorder.csproj') -c $Configuration -nologo
if ($LASTEXITCODE -ne 0) { throw 'build failed' }

# the recorder's output folder holds the plugin and everything it needs
$bin = Join-Path $root "src\StarryKaraoke.Recorder\bin\$Configuration\net48"
$dll = Join-Path $bin 'mb_StarryKaraoke.dll'
if (-not (Test-Path -LiteralPath $dll)) { throw "The plugin was not built at $dll." }
$fileVersion = (Get-Item -LiteralPath $dll).VersionInfo.FileVersion
if ($fileVersion -ne $version -and -not $fileVersion.StartsWith("$version.")) {
    throw "The built plugin reports version $fileVersion but the project says $version."
}

$dist = Join-Path $root 'dist'
$stage = Join-Path $dist "StarryKaraoke-MusicBee-$version"
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
if (-not (Test-Path -LiteralPath $zip)) { throw "The release zip was not created at $zip." }
Write-Host "Created $zip"
