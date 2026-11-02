# Opens the LyricLoom app.
$root = Split-Path -Parent $PSScriptRoot
Start-Process (Join-Path $root '.venv\Scripts\lyricloom-app.exe')
