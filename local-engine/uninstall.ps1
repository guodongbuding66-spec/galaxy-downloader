param(
    [string]$InstallDir = ''
)

$ErrorActionPreference = 'Stop'
$ProtocolRoot = 'HKCU:\Software\Classes\galaxy-downloader'
$SourceDir = [System.IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))
if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = $SourceDir
}
$InstallDir = [System.IO.Path]::GetFullPath($InstallDir)

$ExistingEngine = Get-Process -Name 'GalaxyLocalEngine' -ErrorAction SilentlyContinue
if ($ExistingEngine) {
    $ExistingEngine | Stop-Process -Force
}

if (Test-Path $ProtocolRoot) {
    Remove-Item -Recurse -Force $ProtocolRoot
}

Write-Host 'Galaxy Downloader protocol registration removed.' -ForegroundColor Cyan
Write-Host "Portable folder remains at: $InstallDir"
Write-Host "Downloaded media remains at: $(Join-Path $InstallDir 'downloads')"
Write-Host 'Delete the extracted Galaxy Local Engine folder manually if you want to remove all program files.'
