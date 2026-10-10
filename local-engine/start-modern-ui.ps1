param([string]$ProtocolUrl = '')
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$engine = Join-Path $root 'GalaxyLocalEngineBackend.exe'
$url = 'http://127.0.0.1:17836/dashboard/'
$previewHelper = Join-Path $root 'media-preview-server.ps1'

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class GalaxyWindow {
  [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
}
"@ -ErrorAction SilentlyContinue

function Hide-GalaxyLegacyWindow {
  Get-Process -Name 'GalaxyLocalEngineBackend' -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.MainWindowHandle -ne 0) { [GalaxyWindow]::ShowWindowAsync($_.MainWindowHandle, 0) | Out-Null }
  }
}

function Test-PreviewHelper {
  try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:17837/health' -TimeoutSec 1
    return $r.StatusCode -eq 200
  } catch { return $false }
}

function Start-PreviewHelper {
  if (Test-PreviewHelper) { return }
  if (-not (Test-Path $previewHelper)) { return }
  $ps = (Get-Command powershell.exe -ErrorAction SilentlyContinue).Source
  if (-not $ps) { return }
  Start-Process -FilePath $ps -WorkingDirectory $root -WindowStyle Hidden -ArgumentList @('-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',('"' + $previewHelper + '"')) | Out-Null
  for ($i=0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 120
    if (Test-PreviewHelper) { break }
  }
}

function Test-GalaxyEngine {
  try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:17836/health' -TimeoutSec 1
    return $r.StatusCode -ge 200 -and $r.StatusCode -lt 500
  } catch { return $false }
}

if (-not (Test-GalaxyEngine)) {
  if (-not (Test-Path $engine)) { Write-Host 'GalaxyLocalEngineBackend.exe not found.'; exit 1 }
  Start-Process -FilePath $engine -WorkingDirectory $root -WindowStyle Hidden
  for ($i=0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 250
    if (Test-GalaxyEngine) { break }
  }
}

Hide-GalaxyLegacyWindow
if (-not [string]::IsNullOrWhiteSpace($ProtocolUrl)) {
  try {
    Start-Process -FilePath $engine -WorkingDirectory $root -WindowStyle Hidden -ArgumentList @($ProtocolUrl) | Out-Null
    Start-Sleep -Milliseconds 180
    Hide-GalaxyLegacyWindow
  } catch { }
}
Start-PreviewHelper
Start-Sleep -Milliseconds 120
Hide-GalaxyLegacyWindow

$edgeCandidates = @(
  (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
  (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'),
  (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\Application\msedge.exe')
)
$edge = $edgeCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($edge) {
  Start-Process -FilePath $edge -ArgumentList @("--app=$url", '--window-size=1500,920', '--disable-features=msEdgeSidebarV2')
} else {
  Start-Process $url
}
