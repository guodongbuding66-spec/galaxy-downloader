param(
    [string]$InstallDir = "$env:LOCALAPPDATA\GalaxyDownloader\LocalEngine",
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Write-Step([string]$Message) {
    Write-Host "[Galaxy] $Message" -ForegroundColor Cyan
}

function Write-Warn([string]$Message) {
    Write-Host "[Galaxy] $Message" -ForegroundColor Yellow
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
    $FfmpegUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
    $ChecksumUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256'
    $TempRoot = Join-Path $env:TEMP ('galaxy-ffmpeg-' + [guid]::NewGuid().ToString('N'))
    $ZipPath = Join-Path $TempRoot 'ffmpeg.zip'
    $ChecksumPath = Join-Path $TempRoot 'ffmpeg.zip.sha256'
    $ExtractPath = Join-Path $TempRoot 'extract'

    try {
        New-Item -ItemType Directory -Force -Path $ExtractPath | Out-Null
        Invoke-WebRequest -UseBasicParsing -Uri $FfmpegUrl -OutFile $ZipPath
        Invoke-WebRequest -UseBasicParsing -Uri $ChecksumUrl -OutFile $ChecksumPath

        $ExpectedHash = ((Get-Content $ChecksumPath -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
        if ($ExpectedHash -notmatch '^[0-9a-f]{64}$') {
            throw "The FFmpeg publisher checksum was invalid: '$ExpectedHash'"
        }
        $ActualHash = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($ActualHash -ne $ExpectedHash) {
            throw "FFmpeg SHA-256 verification failed. Expected $ExpectedHash but received $ActualHash."
        }
        Write-Step 'FFmpeg SHA-256 verified'

        Expand-Archive -Force -Path $ZipPath -DestinationPath $ExtractPath
        $SourceBin = Get-ChildItem -Path $ExtractPath -Directory | Select-Object -First 1 | ForEach-Object { Join-Path $_.FullName 'bin' }
        if (-not $SourceBin -or -not (Test-Path (Join-Path $SourceBin 'ffmpeg.exe'))) {
            throw 'FFmpeg download was extracted but ffmpeg.exe could not be found.'
        }
        if (-not (Test-Path (Join-Path $SourceBin 'ffprobe.exe'))) {
            throw 'FFmpeg download was extracted but ffprobe.exe could not be found.'
        }

        New-Item -ItemType Directory -Force -Path $FfmpegBin | Out-Null
        Copy-Item -Force (Join-Path $SourceBin 'ffmpeg.exe') $FfmpegBin
        Copy-Item -Force (Join-Path $SourceBin 'ffprobe.exe') $FfmpegBin
    }
    finally {
        Remove-Item -Recurse -Force $TempRoot -ErrorAction SilentlyContinue
    }
}

$ExternalYtDlp = Join-Path $InstallDir 'yt-dlp.exe'
if (-not (Test-Path $ExternalYtDlp)) {
    Write-Step 'Installing the official self-updatable yt-dlp extractor'
    $YtDlpUrl = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe'
    $YtDlpChecksumsUrl = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS'
    $YtDlpTemp = Join-Path $env:TEMP ('galaxy-ytdlp-' + [guid]::NewGuid().ToString('N'))
    $YtDlpTempExe = Join-Path $YtDlpTemp 'yt-dlp.exe'
    $YtDlpChecksums = Join-Path $YtDlpTemp 'SHA2-256SUMS'

    try {
        New-Item -ItemType Directory -Force -Path $YtDlpTemp | Out-Null
        Invoke-WebRequest -UseBasicParsing -Uri $YtDlpUrl -OutFile $YtDlpTempExe
        Invoke-WebRequest -UseBasicParsing -Uri $YtDlpChecksumsUrl -OutFile $YtDlpChecksums

        $ChecksumText = Get-Content $YtDlpChecksums -Raw
        $Match = [regex]::Match($ChecksumText, '(?im)^([0-9a-f]{64})\s+\*?yt-dlp\.exe\s*$')
        if (-not $Match.Success) {
            throw 'The official yt-dlp checksum list did not contain yt-dlp.exe.'
        }
        $ExpectedYtDlpHash = $Match.Groups[1].Value.ToLowerInvariant()
        $ActualYtDlpHash = (Get-FileHash $YtDlpTempExe -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($ActualYtDlpHash -ne $ExpectedYtDlpHash) {
            throw "yt-dlp SHA-256 verification failed. Expected $ExpectedYtDlpHash but received $ActualYtDlpHash."
        }

        Move-Item -Force $YtDlpTempExe $ExternalYtDlp
        Write-Step 'Official yt-dlp SHA-256 verified'
    }
    catch {
        Write-Warn "Could not install the external yt-dlp updater: $($_.Exception.Message)"
        Write-Warn 'Galaxy will continue with its embedded yt-dlp fallback.'
    }
    finally {
        Remove-Item -Recurse -Force $YtDlpTemp -ErrorAction SilentlyContinue
    }
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
$UninstallCmdSource = Join-Path $SourceDir 'uninstall.cmd'
if (Test-Path $UninstallCmdSource) {
    Copy-Item -Force $UninstallCmdSource (Join-Path $InstallDir 'uninstall.cmd')
}
$VersionSource = Join-Path $SourceDir 'VERSION'
if (Test-Path $VersionSource) {
    Copy-Item -Force $VersionSource (Join-Path $InstallDir 'VERSION')
}

Write-Step 'Installation complete'
Write-Host ''
Write-Host 'The Galaxy website can now launch local downloads with one click.' -ForegroundColor Green
Write-Host 'Galaxy will prefer the verified external yt-dlp extractor and keep it on the nightly channel.' -ForegroundColor Green
Write-Host "Download folder: $env:USERPROFILE\Downloads\Galaxy Downloader"
Write-Host ''
if (-not $NoLaunch) {
    Start-Process (Join-Path $InstallDir 'GalaxyLocalEngine.exe')
}
