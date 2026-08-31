param(
    [Parameter(Mandatory = $true)]
    [string]$PackageDir
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Write-Step([string]$Message) {
    Write-Host "[Galaxy Bundle] $Message" -ForegroundColor Cyan
}

$PackageDir = [System.IO.Path]::GetFullPath($PackageDir)
New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null

# Bundle FFmpeg into the release package so end users do not need to download
# anything during installation. The CI runner performs the network fetch once,
# verifies the publisher checksum, and ships ffmpeg.exe + ffprobe.exe in the ZIP.
$FfmpegBin = Join-Path $PackageDir 'ffmpeg\bin'
$FfmpegExe = Join-Path $FfmpegBin 'ffmpeg.exe'
$FfprobeExe = Join-Path $FfmpegBin 'ffprobe.exe'
if (-not (Test-Path $FfmpegExe) -or -not (Test-Path $FfprobeExe)) {
    Write-Step 'Downloading and verifying FFmpeg for the offline bundle'
    $FfmpegUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
    $ChecksumUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256'
    $TempRoot = Join-Path $env:TEMP ('galaxy-bundle-ffmpeg-' + [guid]::NewGuid().ToString('N'))
    $ZipPath = Join-Path $TempRoot 'ffmpeg.zip'
    $ChecksumPath = Join-Path $TempRoot 'ffmpeg.zip.sha256'
    $ExtractPath = Join-Path $TempRoot 'extract'

    try {
        New-Item -ItemType Directory -Force -Path $ExtractPath | Out-Null
        Invoke-WebRequest -UseBasicParsing -Uri $FfmpegUrl -OutFile $ZipPath
        Invoke-WebRequest -UseBasicParsing -Uri $ChecksumUrl -OutFile $ChecksumPath

        $ExpectedHash = ((Get-Content $ChecksumPath -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
        if ($ExpectedHash -notmatch '^[0-9a-f]{64}$') {
            throw "Invalid FFmpeg publisher checksum: '$ExpectedHash'"
        }
        $ActualHash = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($ActualHash -ne $ExpectedHash) {
            throw "FFmpeg SHA-256 verification failed. Expected $ExpectedHash but received $ActualHash."
        }

        Expand-Archive -Force -Path $ZipPath -DestinationPath $ExtractPath
        $SourceBin = Get-ChildItem -Path $ExtractPath -Directory | Select-Object -First 1 | ForEach-Object { Join-Path $_.FullName 'bin' }
        if (-not $SourceBin -or -not (Test-Path (Join-Path $SourceBin 'ffmpeg.exe')) -or -not (Test-Path (Join-Path $SourceBin 'ffprobe.exe'))) {
            throw 'FFmpeg archive did not contain ffmpeg.exe and ffprobe.exe.'
        }

        New-Item -ItemType Directory -Force -Path $FfmpegBin | Out-Null
        Copy-Item -Force (Join-Path $SourceBin 'ffmpeg.exe') $FfmpegExe
        Copy-Item -Force (Join-Path $SourceBin 'ffprobe.exe') $FfprobeExe
        Write-Step 'FFmpeg verified and bundled'
    }
    finally {
        Remove-Item -Recurse -Force $TempRoot -ErrorAction SilentlyContinue
    }
}

# Bundle the current official Windows yt-dlp executable too. This removes the
# previous first-run dependency on GitHub from the user's computer.
$YtDlpExe = Join-Path $PackageDir 'yt-dlp.exe'
if (-not (Test-Path $YtDlpExe)) {
    Write-Step 'Downloading and verifying yt-dlp for the offline bundle'
    $YtDlpUrl = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe'
    $YtDlpChecksumsUrl = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS'
    $TempRoot = Join-Path $env:TEMP ('galaxy-bundle-ytdlp-' + [guid]::NewGuid().ToString('N'))
    $TempExe = Join-Path $TempRoot 'yt-dlp.exe'
    $Checksums = Join-Path $TempRoot 'SHA2-256SUMS'

    try {
        New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null
        Invoke-WebRequest -UseBasicParsing -Uri $YtDlpUrl -OutFile $TempExe
        Invoke-WebRequest -UseBasicParsing -Uri $YtDlpChecksumsUrl -OutFile $Checksums

        $ChecksumText = Get-Content $Checksums -Raw
        $Match = [regex]::Match($ChecksumText, '(?im)^([0-9a-f]{64})\s+\*?yt-dlp\.exe\s*$')
        if (-not $Match.Success) {
            throw 'Official yt-dlp checksum list did not contain yt-dlp.exe.'
        }
        $ExpectedHash = $Match.Groups[1].Value.ToLowerInvariant()
        $ActualHash = (Get-FileHash $TempExe -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($ActualHash -ne $ExpectedHash) {
            throw "yt-dlp SHA-256 verification failed. Expected $ExpectedHash but received $ActualHash."
        }

        Copy-Item -Force $TempExe $YtDlpExe
        Write-Step 'yt-dlp verified and bundled'
    }
    finally {
        Remove-Item -Recurse -Force $TempRoot -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path $FfmpegExe) -or -not (Test-Path $FfprobeExe) -or -not (Test-Path $YtDlpExe)) {
    throw 'Offline dependency bundle is incomplete.'
}

$YtDlpVersion = (& $YtDlpExe --version | Select-Object -Last 1).Trim()
if (-not $YtDlpVersion) {
    throw 'Bundled yt-dlp.exe did not report a version.'
}
Write-Step "Offline bundle ready (yt-dlp $YtDlpVersion)"
