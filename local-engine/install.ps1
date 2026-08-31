param(
    [string]$InstallDir = '',
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

function Same-Path([string]$Left, [string]$Right) {
    try {
        return ([System.IO.Path]::GetFullPath($Left)).TrimEnd('\') -ieq ([System.IO.Path]::GetFullPath($Right)).TrimEnd('\')
    }
    catch {
        return $false
    }
}

$SourceDir = [System.IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))
if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    # Default to a portable in-place installation. Everything stays inside the
    # folder the user extracted, which is easier to understand and back up.
    $InstallDir = $SourceDir
}
$InstallDir = [System.IO.Path]::GetFullPath($InstallDir)

$EngineSource = Join-Path $SourceDir 'GalaxyLocalEngine.exe'
$YtDlpSource = Join-Path $SourceDir 'yt-dlp.exe'
$FfmpegSourceDir = Join-Path $SourceDir 'ffmpeg'
$FfmpegSource = Join-Path $FfmpegSourceDir 'bin\ffmpeg.exe'
$FfprobeSource = Join-Path $FfmpegSourceDir 'bin\ffprobe.exe'

$RequiredSources = @(
    $EngineSource,
    $YtDlpSource,
    $FfmpegSource,
    $FfprobeSource,
    (Join-Path $SourceDir 'VERSION')
)
foreach ($required in $RequiredSources) {
    if (-not (Test-Path $required)) {
        throw "The release package is incomplete: missing $required. Re-download the complete GalaxyLocalEngine-Windows.zip and extract all files before running install.cmd."
    }
}

Write-Step "Portable install folder: $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# Windows keeps a running executable locked. Stop an older Galaxy Local Engine
# before refreshing files or protocol registration.
$ExistingEngine = Get-Process -Name 'GalaxyLocalEngine' -ErrorAction SilentlyContinue
if ($ExistingEngine) {
    Write-Step 'Closing the currently running Galaxy Local Engine for upgrade'
    $ExistingEngine | Stop-Process -Force
    Start-Sleep -Milliseconds 500
}

# Normal users install in-place, so no copy is needed. The optional InstallDir
# parameter remains for CI/testing and advanced users who explicitly choose a
# different folder.
if (-not (Same-Path $SourceDir $InstallDir)) {
    Write-Step 'Copying the portable package to the selected install folder'
    Copy-Item -Force $EngineSource (Join-Path $InstallDir 'GalaxyLocalEngine.exe')
    Copy-Item -Force $YtDlpSource (Join-Path $InstallDir 'yt-dlp.exe')
    Copy-Item -Recurse -Force $FfmpegSourceDir (Join-Path $InstallDir 'ffmpeg')

    foreach ($name in @('install.cmd', 'install.ps1', 'uninstall.cmd', 'uninstall.ps1', 'README.md', '使用说明.txt', 'VERSION')) {
        $source = Join-Path $SourceDir $name
        if (Test-Path $source) {
            Copy-Item -Force $source (Join-Path $InstallDir $name)
        }
    }
}

$EngineExe = Join-Path $InstallDir 'GalaxyLocalEngine.exe'
$ExternalYtDlp = Join-Path $InstallDir 'yt-dlp.exe'
$FfmpegExe = Join-Path $InstallDir 'ffmpeg\bin\ffmpeg.exe'
$FfprobeExe = Join-Path $InstallDir 'ffmpeg\bin\ffprobe.exe'

foreach ($required in @($EngineExe, $ExternalYtDlp, $FfmpegExe, $FfprobeExe)) {
    if (-not (Test-Path $required)) {
        throw "Installation validation failed: missing $required"
    }
}

$YtDlpVersion = (& $ExternalYtDlp --version | Select-Object -Last 1).Trim()
if (-not $YtDlpVersion) {
    throw 'Bundled yt-dlp.exe could not be started.'
}
Write-Step "Bundled yt-dlp ready: $YtDlpVersion"
Write-Step 'Bundled FFmpeg ready - no first-run download required'

$DownloadDir = Join-Path $InstallDir 'downloads'
New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null

Write-Step 'Registering the galaxy-downloader:// protocol for this Windows account'
$ProtocolRoot = 'HKCU:\Software\Classes\galaxy-downloader'
New-Item -Force $ProtocolRoot | Out-Null
Set-Item -Path $ProtocolRoot -Value 'URL:Galaxy Downloader Local Engine'
New-ItemProperty -Path $ProtocolRoot -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
New-Item -Force "$ProtocolRoot\DefaultIcon" | Out-Null
Set-Item -Path "$ProtocolRoot\DefaultIcon" -Value ('"' + $EngineExe + '",0')
New-Item -Force "$ProtocolRoot\shell\open\command" | Out-Null
$Command = '"' + $EngineExe + '" "%1"'
Set-Item -Path "$ProtocolRoot\shell\open\command" -Value $Command

Write-Step 'Installation complete'
Write-Host ''
Write-Host 'Galaxy Local Engine is now a portable in-place installation.' -ForegroundColor Green
Write-Host 'FFmpeg and yt-dlp are already included in this folder; installation does not require GitHub access.' -ForegroundColor Green
Write-Host "Program folder: $InstallDir"
Write-Host "Download folder: $DownloadDir"
Write-Host ''
Write-Warn 'After installation, keep this folder in place. If you move it, run install.cmd again so Windows can refresh the protocol path.'
Write-Host ''
if (-not $NoLaunch) {
    Start-Process $EngineExe
}
