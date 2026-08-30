param(
    [string]$InstallDir = "$env:LOCALAPPDATA\GalaxyDownloader\LocalEngine"
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Write-Step([string]$Message) {
    Write-Host "[Galaxy] $Message" -ForegroundColor Cyan
}

$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$EngineSource = Join-Path $SourceDir 'GalaxyLocalEngine.exe'
if (-not (Test-Path $EngineSource)) {
    throw 'GalaxyLocalEngine.exe was not found next to install.ps1. Extract the complete release ZIP before running the installer.'
}

Write-Step "Installing to $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -Force $EngineSource (Join-Path $InstallDir 'GalaxyLocalEngine.exe')

$FfmpegBin = Join-Path $InstallDir 'ffmpeg\bin'
$FfmpegExe = Join-Path $FfmpegBin 'ffmpeg.exe'
if (-not (Test-Path $FfmpegExe)) {
    Write-Step 'Downloading the free FFmpeg essentials build'
    $TempRoot = Join-Path $env:TEMP ('galaxy-ffmpeg-' + [guid]::NewGuid().ToString('N'))
    $ZipPath = Join-Path $TempRoot 'ffmpeg.zip'
    $ExtractPath = Join-Path $TempRoot 'extract'
    New-Item -ItemType Directory -Force -Path $ExtractPath | Out-Null
    Invoke-WebRequest -UseBasicParsing -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $ZipPath
    Expand-Archive -Force -Path $ZipPath -DestinationPath $ExtractPath
    $SourceBin = Get-ChildItem -Path $ExtractPath -Directory | Select-Object -First 1 | ForEach-Object { Join-Path $_.FullName 'bin' }
    if (-not $SourceBin -or -not (Test-Path (Join-Path $SourceBin 'ffmpeg.exe'))) {
        throw 'FFmpeg download was extracted but ffmpeg.exe could not be found.'
    }
    New-Item -ItemType Directory -Force -Path $FfmpegBin | Out-Null
    Copy-Item -Force (Join-Path $SourceBin 'ffmpeg.exe') $FfmpegBin
    Copy-Item -Force (Join-Path $SourceBin 'ffprobe.exe') $FfmpegBin
    Remove-Item -Recurse -Force $TempRoot -ErrorAction SilentlyContinue
}

Write-Step 'Registering the galaxy-downloader:// protocol for this Windows account'
$ProtocolRoot = 'HKCU:\Software\Classes\galaxy-downloader'
New-Item -Force $ProtocolRoot | Out-Null
Set-Item -Path $ProtocolRoot -Value 'URL:Galaxy Downloader Local Engine'
New-ItemProperty -Path $ProtocolRoot -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
New-Item -Force "$ProtocolRoot\DefaultIcon" | Out-Null
Set-Item -Path "$ProtocolRoot\DefaultIcon" -Value ('"' + (Join-Path $InstallDir 'GalaxyLocalEngine.exe') + '",0')
New-Item -Force "$ProtocolRoot\shell\open\command" | Out-Null
$Command = '"' + (Join-Path $InstallDir 'GalaxyLocalEngine.exe') + '" "%1"'
Set-Item -Path "$ProtocolRoot\shell\open\command" -Value $Command

$UninstallSource = Join-Path $SourceDir 'uninstall.ps1'
if (Test-Path $UninstallSource) {
    Copy-Item -Force $UninstallSource (Join-Path $InstallDir 'uninstall.ps1')
}

Write-Step 'Installation complete'
Write-Host ''
Write-Host 'The Galaxy website can now launch local downloads with one click.' -ForegroundColor Green
Write-Host "Download folder: $env:USERPROFILE\Downloads\Galaxy Downloader"
Write-Host ''
Start-Process (Join-Path $InstallDir 'GalaxyLocalEngine.exe')
