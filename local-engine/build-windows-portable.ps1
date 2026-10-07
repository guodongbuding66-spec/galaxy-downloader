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
    "--runtime-hook", (Join-Path $ScriptDir "frozen_stdio.py"),
    "--distpath", $DistRoot,
    "--workpath", $WorkRoot
)

& $Python -m PyInstaller @Common --onedir --windowed --name GalaxyLocalEngine --add-data "$(Join-Path $ScriptDir 'VERSION');." (Join-Path $ScriptDir "entrypoint.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller main build failed with exit code $LASTEXITCODE" }

& $Python -m PyInstaller @Common --onefile --windowed --name GalaxyStateTool (Join-Path $ScriptDir "state_tool.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller state tool build failed with exit code $LASTEXITCODE" }

# One verifier owns both local and CI acceptance and packaging.
& (Join-Path $ScriptDir "verify-windows-portable.ps1") -OutputRoot $OutputRoot
