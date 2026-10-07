param(
    [string]$OutputRoot = ".release\windows-portable"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
if (-not [IO.Path]::IsPathRooted($OutputRoot)) { $OutputRoot = Join-Path $ScriptDir $OutputRoot }
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
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

foreach ($name in @("install.cmd", "install.ps1", "uninstall.cmd", "uninstall.ps1", "README.md", "使用说明.txt", "VERSION")) {
    Copy-Item -Force (Join-Path $ScriptDir $name) (Join-Path $PackageRoot $name)
}

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
    throw "Missing portable tool: $Local. Supply real executables before verification."
}

$MainExe = Join-Path $PackageRoot "GalaxyLocalEngine.exe"
$StateExe = Join-Path $PackageRoot "GalaxyStateTool.exe"

function Invoke-CheckedProcess {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [int]$TimeoutSeconds = 180
    )

    $DiagnosticPath = [System.IO.Path]::GetTempFileName()
    $OldDiagnostic = $env:GALAXY_DIAGNOSTIC_LOG
    $env:GALAXY_DIAGNOSTIC_LOG = $DiagnosticPath
    $StdoutPath = [System.IO.Path]::GetTempFileName()
    $StderrPath = [System.IO.Path]::GetTempFileName()
    try {
        $Process = Start-Process `
            -FilePath $FilePath `
            -ArgumentList ($Arguments | ForEach-Object { '"' + $_ + '"' }) `
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
        $Diagnostic = Get-Content -Raw $DiagnosticPath -ErrorAction SilentlyContinue
        if ($Diagnostic) { Write-Host "Process diagnostic:`n$Diagnostic" }
        $env:GALAXY_DIAGNOSTIC_LOG = $OldDiagnostic
        Remove-Item -Force -ErrorAction SilentlyContinue $StdoutPath, $StderrPath, $DiagnosticPath
    }
}

# Run tool binaries without Chocolatey/Python on PATH so shims cannot pass.
$OriginalPath = $env:PATH
try {
    $env:PATH = "$env:SystemRoot/System32;$env:SystemRoot"
    Invoke-CheckedProcess -FilePath (Join-Path $PackageRoot "yt-dlp.exe") -Arguments @("--version")
    Invoke-CheckedProcess -FilePath (Join-Path $PackageRoot "ffmpeg.exe") -Arguments @("-version")
    Invoke-CheckedProcess -FilePath (Join-Path $PackageRoot "ffprobe.exe") -Arguments @("-version")
} finally { $env:PATH = $OriginalPath }

Write-Host "[verify] frozen GalaxyStateTool self-test"
Invoke-CheckedProcess -FilePath $StateExe -Arguments @("--self-test")
Write-Host "[verify] frozen GalaxyLocalEngine self-test"
Invoke-CheckedProcess -FilePath $MainExe -Arguments @("--self-test") -TimeoutSeconds 300
Write-Host "[verify] frozen desktop UI construction"
Invoke-CheckedProcess -FilePath $MainExe -Arguments @("--ui-smoke-test") -TimeoutSeconds 120
Write-Host "[verify] portable installer in-place"
& (Join-Path $PackageRoot "install.ps1") -NoLaunch
$Registered = (Get-Item "HKCU:/Software/Classes/galaxy-downloader/shell/open/command").GetValue("")
if ($Registered -ne ('"' + $MainExe + '" "%1"')) { throw "Protocol registration points to wrong executable" }
& (Join-Path $PackageRoot "uninstall.ps1")

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
foreach ($runtimeDir in @("cache", "downloads")) {
    $runtimePath = Join-Path $PackageRoot $runtimeDir
    if (Test-Path $runtimePath) { Remove-Item -Recurse -Force $runtimePath }
}
Remove-Item -Force $BackupPath

Compress-Archive -Path (Join-Path $PackageRoot "*") -DestinationPath $ZipPath -CompressionLevel Optimal
$Hashes = Get-ChildItem -File $MainExe, $StateExe, $ZipPath | ForEach-Object {
    $Hash = Get-FileHash -Algorithm SHA256 -Path $_.FullName
    "{0}  {1}" -f $Hash.Hash.ToLowerInvariant(), $_.Name
}
Set-Content -Path $ChecksumsPath -Value $Hashes -Encoding ASCII

$Manifest = [ordered]@{
    schema = "galaxy-local-engine-windows-build/v1"
    sourceCommit = (& git rev-parse HEAD).Trim()
    engineVersion = (Get-Content (Join-Path $ScriptDir "VERSION") -Raw).Trim()
    architecture = "x64"
    builtUtc = [DateTime]::UtcNow.ToString("o")
    mainExe = "GalaxyLocalEngine.exe"
    stateToolExe = "GalaxyStateTool.exe"
    zip = [IO.Path]::GetFileName($ZipPath)
    sourceSelfTest = $true
    frozenSelfTest = $true
    backupRestoreRoundtrip = $true
    frozenUiSmoke = $true
    portableTools = $true
    installerProtocol = $true
}
$Manifest | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $OutputRoot "build-manifest.json") -Encoding UTF8

Write-Host "WINDOWS_PORTABLE_VERIFY_OK"
Write-Host "PACKAGE=$ZipPath"
Write-Host "CHECKSUMS=$ChecksumsPath"
