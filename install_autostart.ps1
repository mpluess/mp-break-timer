# Installs (or with -Uninstall removes) the MP Break Timer autostart shortcut.
param([switch]$Uninstall)

$ErrorActionPreference = "Stop"
$shortcut = Join-Path ([Environment]::GetFolderPath("Startup")) "MP Break Timer.lnk"

if ($Uninstall) {
    Remove-Item $shortcut -ErrorAction SilentlyContinue
    Write-Host "Autostart removed."
    return
}

uv sync --project $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

$exe = Join-Path $PSScriptRoot ".venv\Scripts\mp-break-timer.exe"
$link = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
$link.TargetPath = $exe
$link.WorkingDirectory = $PSScriptRoot
$link.Description = "MP Break Timer"
$link.Save()
Write-Host "Autostart installed: $shortcut"
Write-Host "Start it now with: & '$exe'"
