param(
    [string]$OutputRoot = ".release\windows-portable"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
$OutputRoot = [System.IO.Path]::GetFullPath((Join-Path $ScriptDir $OutputRoot))
$DistRoot = Join-Path $OutputRoot "dist"
$PackageRoot = Join-Path $OutputRoot "GalaxyLocalEngine-Portable"
$ZipPath = Join-Path $OutputRoot "GalaxyLocalEngine-Portable-Windows-x64.zip"
$ChecksumsPath = Join-Path $OutputRoot "SHA256SUMS.txt"
$MainDist = Join-Path $DistRoot "GalaxyLocalEngine"
$MainSourceExe = Join-Path $MainDist "GalaxyLocalEngine.exe"
$StateSourceExe = Join-Path $DistRoot "GalaxyStateTool.exe"

if (-not (Test-Path $MainSourceExe)) { throw "GalaxyLocalEngine.exe was not produced" }
if (-not (Test-Path $StateSourceExe)) { throw "GalaxyStateTool.exe was not produced" }
if (Test-Path $PackageRoot) { Remove-Item -Recurse -Force $PackageRoot }
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }

Copy-Item -Recurse -Force $MainDist $PackageRoot
Copy-Item -Force $StateSourceExe (Join-Path $PackageRoot "GalaxyStateTool.exe")
Set-Content -Path (Join-Path $PackageRoot "portable.flag") -Value "1" -Encoding ASCII

foreach ($DataDir in @("assets", "static", "web-dashboard")) {
    $Source = Join-Path $ScriptDir $DataDir
    if (Test-Path $Source) { Copy-Item -Recurse -Force $Source (Join-Path $PackageRoot $DataDir) }
}

foreach ($Tool in @("yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe")) {
    $Local = Join-Path $ScriptDir $Tool
    if (Test-Path $Local) {
        Copy-Item -Force $Local (Join-Path $PackageRoot $Tool)
        continue
    }
    $Resolved = Get-Command $Tool -ErrorAction SilentlyContinue
    if ($Resolved) { Copy-Item -Force $Resolved.Source (Join-Path $PackageRoot $Tool) }
}

$MainExe = Join-Path $PackageRoot "GalaxyLocalEngine.exe"
$StateExe = Join-Path $PackageRoot "GalaxyStateTool.exe"

function Invoke-CheckedProcess {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [int]$TimeoutSeconds = 180
    )

    $StdoutPath = [System.IO.Path]::GetTempFileName()
    $StderrPath = [System.IO.Path]::GetTempFileName()
    try {
        $Process = Start-Process `
            -FilePath $FilePath `
            -ArgumentList $Arguments `
            -PassThru `
            -RedirectStandardOutput $StdoutPath `
            -RedirectStandardError $StderrPath

        if (-not $Process.WaitForExit($TimeoutSeconds * 1000)) {
            try { Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue } catch {}
            $Stdout = if (Test-Path $StdoutPath) { Get-Content -Raw -Path $StdoutPath -ErrorAction SilentlyContinue } else { "" }
            $Stderr = if (Test-Path $StderrPath) { Get-Content -Raw -Path $StderrPath -ErrorAction SilentlyContinue } else { "" }
            if ($Stdout) { Write-Host "--- process stdout ---`n$Stdout" }
            if ($Stderr) { Write-Host "--- process stderr ---`n$Stderr" }
            throw "Process timed out after $TimeoutSeconds seconds: $FilePath $($Arguments -join ' ')"
        }

        $Stdout = if (Test-Path $StdoutPath) { Get-Content -Raw -Path $StdoutPath -ErrorAction SilentlyContinue } else { "" }
        $Stderr = if (Test-Path $StderrPath) { Get-Content -Raw -Path $StderrPath -ErrorAction SilentlyContinue } else { "" }
        if ($Stdout) { Write-Host "--- process stdout ---`n$Stdout" }
        if ($Stderr) { Write-Host "--- process stderr ---`n$Stderr" }

        if ($Process.ExitCode -ne 0) {
            throw "Process failed with exit code $($Process.ExitCode): $FilePath $($Arguments -join ' ')"
        }
    }
    finally {
        Remove-Item -Force -ErrorAction SilentlyContinue $StdoutPath, $StderrPath
    }
}

Write-Host "[verify] frozen GalaxyStateTool self-test"
Invoke-CheckedProcess -FilePath $StateExe -Arguments @("--self-test")
Write-Host "[verify] frozen GalaxyLocalEngine self-test"
Invoke-CheckedProcess -FilePath $MainExe -Arguments @("--self-test") -TimeoutSeconds 300

$StateDir = Join-Path $PackageRoot "state"
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
Set-Content -Path (Join-Path $StateDir "workspace-options.json") -Value '{"historyEnabled":true}' -Encoding UTF8
Set-Content -Path (Join-Path $StateDir "download-profiles.json") -Value '{"version":1,"profiles":[]}' -Encoding UTF8
Set-Content -Path (Join-Path $StateDir "telegram-upload-secret.json") -Value '{"botToken":"CI-SECRET-MUST-STAY-LOCAL"}' -Encoding UTF8
$BackupPath = Join-Path $OutputRoot "ci-roundtrip.galaxy-state.zip"

Write-Host "[verify] frozen backup"
Invoke-CheckedProcess -FilePath $StateExe -Arguments @("--backup", $BackupPath)
if (-not (Test-Path $BackupPath)) { throw "Frozen backup command did not produce an archive" }
Write-Host "[verify] frozen validate"
Invoke-CheckedProcess -FilePath $StateExe -Arguments @("--validate", $BackupPath)
Set-Content -Path (Join-Path $StateDir "workspace-options.json") -Value '{"historyEnabled":false}' -Encoding UTF8
Remove-Item -Force (Join-Path $StateDir "download-profiles.json")
Write-Host "[verify] frozen restore"
Invoke-CheckedProcess -FilePath $StateExe -Arguments @("--restore", $BackupPath)

if (-not (Test-Path (Join-Path $StateDir "download-profiles.json"))) { throw "Profile state was not restored" }
$RestoredWorkspace = Get-Content -Raw -Path (Join-Path $StateDir "workspace-options.json")
if ($RestoredWorkspace -notmatch '"historyEnabled"\s*:\s*true') { throw "Workspace state was not restored" }
$Secret = Get-Content -Raw -Path (Join-Path $StateDir "telegram-upload-secret.json")
if ($Secret -notmatch 'CI-SECRET-MUST-STAY-LOCAL') { throw "Secret sidecar was unexpectedly modified" }

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

Write-Host "WINDOWS_PORTABLE_VERIFY_OK"
Write-Host "PACKAGE=$ZipPath"
Write-Host "CHECKSUMS=$ChecksumsPath"
