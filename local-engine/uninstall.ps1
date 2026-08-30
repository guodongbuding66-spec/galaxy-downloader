param(
    [string]$InstallDir = "$env:LOCALAPPDATA\GalaxyDownloader\LocalEngine"
)

$ErrorActionPreference = 'Stop'
$ProtocolRoot = 'HKCU:\Software\Classes\galaxy-downloader'

if (Test-Path $ProtocolRoot) {
    Remove-Item -Recurse -Force $ProtocolRoot
}

Write-Host 'Galaxy Downloader protocol registration removed.' -ForegroundColor Cyan
Write-Host "Installed files remain at: $InstallDir"
Write-Host 'Close the local engine, then delete that folder if you want to remove all files.'
