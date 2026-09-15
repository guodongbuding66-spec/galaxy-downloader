param(
    [Parameter(Mandatory = $true)]
    [string]$PackageDir,

    [ValidateSet('x64', 'arm64')]
    [string]$Architecture = 'x64'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Write-Step([string]$Message) {
    Write-Host "[Galaxy Bundle] $Message" -ForegroundColor Cyan
}

function Get-PeMachine([string]$Path) {
    $Resolved = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $Resolved -PathType Leaf)) {
        throw "PE file does not exist: $Resolved"
    }

    $Stream = [System.IO.File]::Open($Resolved, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
    $Reader = New-Object System.IO.BinaryReader($Stream)
    try {
        if ($Stream.Length -lt 64) {
            throw "File is too small to be a valid PE image: $Resolved"
        }
        if ($Reader.ReadUInt16() -ne 0x5A4D) {
            throw "File is not an MZ/PE image: $Resolved"
        }
        $Stream.Position = 0x3c
        $PeOffset = $Reader.ReadInt32()
        if ($PeOffset -lt 0 -or ($PeOffset + 6) -gt $Stream.Length) {
            throw "Invalid PE header offset in $Resolved"
        }
        $Stream.Position = $PeOffset
        if ($Reader.ReadUInt32() -ne 0x00004550) {
            throw "PE signature is missing in $Resolved"
        }
        return [int]$Reader.ReadUInt16()
    }
    finally {
        $Reader.Dispose()
        $Stream.Dispose()
    }
}

function Assert-PeArchitecture([string]$Path, [string]$ExpectedArchitecture) {
    $ExpectedMachine = if ($ExpectedArchitecture -eq 'arm64') { 0xAA64 } else { 0x8664 }
    $ActualMachine = Get-PeMachine $Path
    if ($ActualMachine -ne $ExpectedMachine) {
        throw ("PE architecture mismatch for {0}: expected {1} (0x{2:X4}), got 0x{3:X4}" -f $Path, $ExpectedArchitecture, $ExpectedMachine, $ActualMachine)
    }
    Write-Step ("Verified {0} as {1} PE" -f ([System.IO.Path]::GetFileName($Path)), $ExpectedArchitecture)
}

function Resolve-PublisherChecksum([string]$ChecksumText, [string]$AssetName) {
    $EscapedName = [regex]::Escape($AssetName)
    $Match = [regex]::Match($ChecksumText, "(?im)^([0-9a-f]{64})\s+\*?$EscapedName\s*$")
    if (-not $Match.Success) {
        throw "Publisher checksum list did not contain $AssetName."
    }
    return $Match.Groups[1].Value.ToLowerInvariant()
}

$PackageDir = [System.IO.Path]::GetFullPath($PackageDir)
New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null
Write-Step "Preparing $Architecture offline dependency bundle"

# Bundle FFmpeg into the release package so end users do not need to download
# anything during installation. x64 keeps the established Gyan source. Windows
# ARM64 uses BtbN's native winarm64 static build. Both paths verify publisher
# SHA-256 data before copying binaries into the package.
$FfmpegBin = Join-Path $PackageDir 'ffmpeg\bin'
$FfmpegExe = Join-Path $FfmpegBin 'ffmpeg.exe'
$FfprobeExe = Join-Path $FfmpegBin 'ffprobe.exe'
if (-not (Test-Path $FfmpegExe) -or -not (Test-Path $FfprobeExe)) {
    Write-Step "Downloading and verifying FFmpeg for $Architecture"
    $TempRoot = Join-Path $env:TEMP ('galaxy-bundle-ffmpeg-' + $Architecture + '-' + [guid]::NewGuid().ToString('N'))
    $ZipPath = Join-Path $TempRoot 'ffmpeg.zip'
    $ChecksumPath = Join-Path $TempRoot 'ffmpeg.sha256'
    $ExtractPath = Join-Path $TempRoot 'extract'

    try {
        New-Item -ItemType Directory -Force -Path $ExtractPath | Out-Null
        if ($Architecture -eq 'arm64') {
            $FfmpegAsset = 'ffmpeg-master-latest-winarm64-gpl.zip'
            $FfmpegUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/$FfmpegAsset"
            $ChecksumUrl = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256'
            Invoke-WebRequest -UseBasicParsing -Uri $FfmpegUrl -OutFile $ZipPath
            Invoke-WebRequest -UseBasicParsing -Uri $ChecksumUrl -OutFile $ChecksumPath
            $ExpectedHash = Resolve-PublisherChecksum (Get-Content $ChecksumPath -Raw) $FfmpegAsset
        }
        else {
            $FfmpegUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
            $ChecksumUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256'
            Invoke-WebRequest -UseBasicParsing -Uri $FfmpegUrl -OutFile $ZipPath
            Invoke-WebRequest -UseBasicParsing -Uri $ChecksumUrl -OutFile $ChecksumPath
            $ExpectedHash = ((Get-Content $ChecksumPath -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
            if ($ExpectedHash -notmatch '^[0-9a-f]{64}$') {
                throw "Invalid FFmpeg publisher checksum: '$ExpectedHash'"
            }
        }

        $ActualHash = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($ActualHash -ne $ExpectedHash) {
            throw "FFmpeg SHA-256 verification failed. Expected $ExpectedHash but received $ActualHash."
        }

        Expand-Archive -Force -Path $ZipPath -DestinationPath $ExtractPath
        $SourceBin = Get-ChildItem -Path $ExtractPath -Recurse -Directory |
            Where-Object { $_.Name -eq 'bin' -and (Test-Path (Join-Path $_.FullName 'ffmpeg.exe')) -and (Test-Path (Join-Path $_.FullName 'ffprobe.exe')) } |
            Select-Object -First 1 -ExpandProperty FullName
        if (-not $SourceBin) {
            throw 'FFmpeg archive did not contain ffmpeg.exe and ffprobe.exe.'
        }

        New-Item -ItemType Directory -Force -Path $FfmpegBin | Out-Null
        Copy-Item -Force (Join-Path $SourceBin 'ffmpeg.exe') $FfmpegExe
        Copy-Item -Force (Join-Path $SourceBin 'ffprobe.exe') $FfprobeExe
        Write-Step 'FFmpeg checksum verified and bundled'
    }
    finally {
        Remove-Item -Recurse -Force $TempRoot -ErrorAction SilentlyContinue
    }
}

# Bundle the matching official Windows yt-dlp executable. The ARM64 release is
# renamed to yt-dlp.exe inside Galaxy so all existing runtime lookup logic and
# installer contracts remain architecture-neutral.
$YtDlpExe = Join-Path $PackageDir 'yt-dlp.exe'
if (-not (Test-Path $YtDlpExe)) {
    $YtDlpAsset = if ($Architecture -eq 'arm64') { 'yt-dlp_arm64.exe' } else { 'yt-dlp.exe' }
    Write-Step "Downloading and verifying $YtDlpAsset"
    $YtDlpUrl = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/$YtDlpAsset"
    $YtDlpChecksumsUrl = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS'
    $TempRoot = Join-Path $env:TEMP ('galaxy-bundle-ytdlp-' + $Architecture + '-' + [guid]::NewGuid().ToString('N'))
    $TempExe = Join-Path $TempRoot $YtDlpAsset
    $Checksums = Join-Path $TempRoot 'SHA2-256SUMS'

    try {
        New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null
        Invoke-WebRequest -UseBasicParsing -Uri $YtDlpUrl -OutFile $TempExe
        Invoke-WebRequest -UseBasicParsing -Uri $YtDlpChecksumsUrl -OutFile $Checksums

        $ExpectedHash = Resolve-PublisherChecksum (Get-Content $Checksums -Raw) $YtDlpAsset
        $ActualHash = (Get-FileHash $TempExe -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($ActualHash -ne $ExpectedHash) {
            throw "yt-dlp SHA-256 verification failed. Expected $ExpectedHash but received $ActualHash."
        }

        Copy-Item -Force $TempExe $YtDlpExe
        Write-Step 'yt-dlp checksum verified and bundled'
    }
    finally {
        Remove-Item -Recurse -Force $TempRoot -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path $FfmpegExe) -or -not (Test-Path $FfprobeExe) -or -not (Test-Path $YtDlpExe)) {
    throw 'Offline dependency bundle is incomplete.'
}

# A checksum alone cannot detect accidentally mixing x64 and ARM64 tools. Read
# each PE COFF Machine field and fail the release if any bundled executable is
# for the wrong architecture.
Assert-PeArchitecture $FfmpegExe $Architecture
Assert-PeArchitecture $FfprobeExe $Architecture
Assert-PeArchitecture $YtDlpExe $Architecture

$YtDlpVersion = (& $YtDlpExe --version | Select-Object -Last 1).Trim()
if (-not $YtDlpVersion) {
    throw 'Bundled yt-dlp.exe did not report a version.'
}
Write-Step "Offline $Architecture bundle ready (yt-dlp $YtDlpVersion)"
