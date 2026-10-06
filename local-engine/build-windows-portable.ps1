param(
    [string]$OutputRoot = ".release\windows-portable",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$Python = (Get-Command python -ErrorAction Stop).Source
$OutputRoot = [System.IO.Path]::GetFullPath((Join-Path $ScriptDir $OutputRoot))
$DistRoot = Join-Path $OutputRoot "dist"
$WorkRoot = Join-Path $OutputRoot "work"
$PackageRoot = Join-Path $OutputRoot "GalaxyLocalEngine-Portable"
$ZipPath = Join-Path $OutputRoot "GalaxyLocalEngine-Portable-Windows-x64.zip"
$ChecksumsPath = Join-Path $OutputRoot "SHA256SUMS.txt"

if (Test-Path $OutputRoot) { Remove-Item -Recurse -Force $OutputRoot }
New-Item -ItemType Directory -Force -Path $DistRoot, $WorkRoot | Out-Null

if (-not $SkipInstall) {
    & $Python -m pip install --disable-pip-version-check -r (Join-Path $ScriptDir "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "pip install failed with exit code $LASTEXITCODE" }
}

# Run source-level regression gates before freezing anything.
& $Python (Join-Path $ScriptDir "state_tool.py") --self-test
if ($LASTEXITCODE -ne 0) { throw "state backup self-test failed with exit code $LASTEXITCODE" }
& $Python (Join-Path $ScriptDir "entrypoint.py") --self-test
if ($LASTEXITCODE -ne 0) { throw "entrypoint self-test failed with exit code $LASTEXITCODE" }

$Common = @(
    "--noconfirm", "--clean",
    "--distpath", $DistRoot,
    "--workpath", $WorkRoot
)

& $Python -m PyInstaller @Common --onedir --windowed --name GalaxyLocalEngine (Join-Path $ScriptDir "entrypoint.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller main build failed with exit code $LASTEXITCODE" }

& $Python -m PyInstaller @Common --onefile --windowed --name GalaxyStateTool (Join-Path $ScriptDir "state_tool.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller state tool build failed with exit code $LASTEXITCODE" }

$MainDist = Join-Path $DistRoot "GalaxyLocalEngine"
if (-not (Test-Path (Join-Path $MainDist "GalaxyLocalEngine.exe"))) {
    throw "GalaxyLocalEngine.exe was not produced"
}
if (-not (Test-Path (Join-Path $DistRoot "GalaxyStateTool.exe"))) {
    throw "GalaxyStateTool.exe was not produced"
}

Copy-Item -Recurse -Force $MainDist $PackageRoot
Copy-Item -Force (Join-Path $DistRoot "GalaxyStateTool.exe") (Join-Path $PackageRoot "GalaxyStateTool.exe")
Set-Content -Path (Join-Path $PackageRoot "portable.flag") -Value "1" -Encoding ASCII

foreach ($DataDir in @("assets", "static", "web-dashboard")) {
    $Source = Join-Path $ScriptDir $DataDir
    if (Test-Path $Source) {
        Copy-Item -Recurse -Force $Source (Join-Path $PackageRoot $DataDir)
    }
}

# Ship standalone yt-dlp and FFmpeg when available. The app can still use its
# Python-bundled yt-dlp path if these tools are absent, but release CI attempts
# to make the portable folder self-contained.
$YtDlp = Join-Path $ScriptDir "yt-dlp.exe"
if (Test-Path $YtDlp) { Copy-Item -Force $YtDlp (Join-Path $PackageRoot "yt-dlp.exe") }
foreach ($Tool in @("ffmpeg.exe", "ffprobe.exe")) {
    $Resolved = Get-Command $Tool -ErrorAction SilentlyContinue
    if ($Resolved) { Copy-Item -Force $Resolved.Source (Join-Path $PackageRoot $Tool) }
}

$MainExe = Join-Path $PackageRoot "GalaxyLocalEngine.exe"
$StateExe = Join-Path $PackageRoot "GalaxyStateTool.exe"

# Frozen executable regression gates. These prove the package, not only source.
$StateTest = Start-Process -FilePath $StateExe -ArgumentList "--self-test" -Wait -PassThru
if ($StateTest.ExitCode -ne 0) { throw "Frozen GalaxyStateTool self-test failed: $($StateTest.ExitCode)" }
$MainTest = Start-Process -FilePath $MainExe -ArgumentList "--self-test" -Wait -PassThru
if ($MainTest.ExitCode -ne 0) { throw "Frozen GalaxyLocalEngine self-test failed: $($MainTest.ExitCode)" }

# Exercise backup -> validate -> restore using the actual frozen state utility.
$StateDir = Join-Path $PackageRoot "state"
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
Set-Content -Path (Join-Path $StateDir "workspace-options.json") -Value '{"historyEnabled":true}' -Encoding UTF8
Set-Content -Path (Join-Path $StateDir "download-profiles.json") -Value '{"version":1,"profiles":[]}' -Encoding UTF8
Set-Content -Path (Join-Path $StateDir "telegram-upload-secret.json") -Value '{"botToken":"CI-SECRET-MUST-STAY-LOCAL"}' -Encoding UTF8
$BackupPath = Join-Path $OutputRoot "ci-roundtrip.galaxy-state.zip"

$BackupTest = Start-Process -FilePath $StateExe -ArgumentList @("--backup", $BackupPath) -Wait -PassThru
if ($BackupTest.ExitCode -ne 0 -or -not (Test-Path $BackupPath)) { throw "Frozen backup command failed" }
$ValidateTest = Start-Process -FilePath $StateExe -ArgumentList @("--validate", $BackupPath) -Wait -PassThru
if ($ValidateTest.ExitCode -ne 0) { throw "Frozen backup validation failed" }
Set-Content -Path (Join-Path $StateDir "workspace-options.json") -Value '{"historyEnabled":false}' -Encoding UTF8
Remove-Item -Force (Join-Path $StateDir "download-profiles.json")
$RestoreTest = Start-Process -FilePath $StateExe -ArgumentList @("--restore", $BackupPath) -Wait -PassThru
if ($RestoreTest.ExitCode -ne 0) { throw "Frozen restore command failed" }
if (-not (Test-Path (Join-Path $StateDir "download-profiles.json"))) { throw "Profile state was not restored" }
$RestoredWorkspace = Get-Content -Raw -Path (Join-Path $StateDir "workspace-options.json")
if ($RestoredWorkspace -notmatch '"historyEnabled"\s*:\s*true') { throw "Workspace state was not restored" }
$Secret = Get-Content -Raw -Path (Join-Path $StateDir "telegram-upload-secret.json")
if ($Secret -notmatch 'CI-SECRET-MUST-STAY-LOCAL') { throw "Secret sidecar was unexpectedly modified" }

# Final user package starts clean; CI-only state and backup are not shipped.
Remove-Item -Recurse -Force $StateDir
Remove-Item -Force $BackupPath

Compress-Archive -Path (Join-Path $PackageRoot "*") -DestinationPath $ZipPath -CompressionLevel Optimal
$Hashes = Get-ChildItem -File $MainExe, $StateExe, $ZipPath | ForEach-Object {
    $Hash = Get-FileHash -Algorithm SHA256 -Path $_.FullName
    "{0}  {1}" -f $Hash.Hash.ToLowerInvariant(), $_.Name
}
Set-Content -Path $ChecksumsPath -Value $Hashes -Encoding ASCII

$Manifest = [ordered]@{
    schema = "galaxy-local-engine-windows-build/v1"
    builtUtc = [DateTime]::UtcNow.ToString("o")
    mainExe = "GalaxyLocalEngine.exe"
    stateToolExe = "GalaxyStateTool.exe"
    zip = [IO.Path]::GetFileName($ZipPath)
    sourceSelfTest = $true
    frozenSelfTest = $true
    backupRestoreRoundtrip = $true
}
$Manifest | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $OutputRoot "build-manifest.json") -Encoding UTF8

Write-Host "WINDOWS_PORTABLE_BUILD_OK"
Write-Host "PACKAGE=$ZipPath"
Write-Host "CHECKSUMS=$ChecksumsPath"
