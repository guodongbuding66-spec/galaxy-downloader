$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$yt = Join-Path $root 'yt-dlp.exe'
$port = 17837
$allowedOrigins = @('http://127.0.0.1:17836','http://localhost:17836')

function Send-JsonResponse {
  param($Stream, [int]$StatusCode, $Payload, [string]$Origin = '')
  $reason = if ($StatusCode -eq 200) { 'OK' } elseif ($StatusCode -eq 204) { 'No Content' } elseif ($StatusCode -eq 400) { 'Bad Request' } elseif ($StatusCode -eq 403) { 'Forbidden' } elseif ($StatusCode -eq 404) { 'Not Found' } elseif ($StatusCode -eq 408) { 'Request Timeout' } else { 'Internal Server Error' }
  $body = if ($StatusCode -eq 204) { '' } else { $Payload | ConvertTo-Json -Depth 8 -Compress }
  $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)
  $cors = ''
  if ($Origin -and $allowedOrigins -contains $Origin) {
    $cors = "Access-Control-Allow-Origin: $Origin`r`nVary: Origin`r`n"
  }
  $headers = "HTTP/1.1 $StatusCode $reason`r`nContent-Type: application/json; charset=utf-8`r`nContent-Length: $($bodyBytes.Length)`r`n${cors}Access-Control-Allow-Methods: GET, OPTIONS`r`nAccess-Control-Allow-Headers: Content-Type, X-Galaxy-Preview`r`nCache-Control: no-store`r`nConnection: close`r`n`r`n"
  $headBytes = [System.Text.Encoding]::ASCII.GetBytes($headers)
  $Stream.Write($headBytes, 0, $headBytes.Length)
  if ($bodyBytes.Length -gt 0) { $Stream.Write($bodyBytes, 0, $bodyBytes.Length) }
  $Stream.Flush()
}

function Parse-Query {
  param([string]$Query)
  $map = @{}
  if ([string]::IsNullOrWhiteSpace($Query)) { return $map }
  foreach ($pair in $Query.TrimStart('?').Split('&')) {
    if (-not $pair) { continue }
    $eq = $pair.IndexOf('=')
    if ($eq -ge 0) {
      $rawKey = $pair.Substring(0, $eq)
      $rawValue = $pair.Substring($eq + 1)
    } else {
      $rawKey = $pair
      $rawValue = ''
    }
    $key = [Uri]::UnescapeDataString(($rawKey -replace '\+', ' '))
    $value = [Uri]::UnescapeDataString(($rawValue -replace '\+', ' '))
    $map[$key] = $value
  }
  return $map
}

function Quote-WindowsArgument {
  param([string]$Value)
  if ($null -eq $Value) { return '""' }
  # ProcessStartInfo.UseShellExecute is false, so shell metacharacters are not interpreted.
  # Quote every argument and follow Windows backslash-before-quote rules.
  $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
  $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
  return '"' + $escaped + '"'
}

function Invoke-YtDlpInspect {
  param([string]$Url, [string]$Browser)
  if (-not (Test-Path $yt)) { throw 'yt-dlp.exe not found.' }
  $uri = $null
  if (-not [Uri]::TryCreate($Url, [UriKind]::Absolute, [ref]$uri) -or $uri.Scheme -notin @('http','https')) { throw 'Only http/https URLs are allowed.' }
  if ($Url.Length -gt 8192 -or $Url -match '[\x00-\x1f"]') { throw 'URL contains unsupported characters.' }
  $allowedBrowsers = @('none','edge','chrome','firefox','brave')
  if ($Browser -notin $allowedBrowsers) { $Browser = 'none' }

  $args = @('--dump-single-json','--skip-download','--no-warnings','--no-playlist','--socket-timeout','20','--retries','1')
  if ($Browser -ne 'none') { $args += @('--cookies-from-browser', $Browser) }
  $args += $Url

  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $yt
  $psi.WorkingDirectory = $root
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
  $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
  $psi.Arguments = (($args | ForEach-Object { Quote-WindowsArgument $_ }) -join ' ')

  $proc = New-Object System.Diagnostics.Process
  $proc.StartInfo = $psi
  [void]$proc.Start()
  $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
  $stderrTask = $proc.StandardError.ReadToEndAsync()
  if (-not $proc.WaitForExit(45000)) {
    try { $proc.Kill() } catch {}
    throw 'Metadata inspection timed out after 45 seconds.'
  }
  $stdout = $stdoutTask.Result
  $stderr = $stderrTask.Result
  if ($proc.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($stdout)) {
    if ($stderr.Length -gt 900) { $stderr = $stderr.Substring(0,900) }
    throw $(if ($stderr) { $stderr.Trim() } else { "yt-dlp exited with code $($proc.ExitCode)." })
  }
  if ($stdout.Length -gt 24000000) { throw 'Metadata response is unexpectedly large.' }
  $info = $stdout | ConvertFrom-Json
  if ($info.entries -and $info.entries.Count -gt 0) { $info = $info.entries | Where-Object { $_ } | Select-Object -First 1 }
  if (-not $info) { throw 'No media entry was returned.' }

  $formats = @()
  foreach ($f in @($info.formats)) {
    if (-not $f) { continue }
    $formats += [pscustomobject]@{
      format_id = [string]$f.format_id
      ext = [string]$f.ext
      width = $f.width
      height = $f.height
      fps = $f.fps
      vcodec = [string]$f.vcodec
      acodec = [string]$f.acodec
      filesize = $f.filesize
      filesize_approx = $f.filesize_approx
      tbr = $f.tbr
      abr = $f.abr
      vbr = $f.vbr
      dynamic_range = [string]$f.dynamic_range
      format_note = [string]$f.format_note
      protocol = [string]$f.protocol
      language = [string]$f.language
    }
  }
  if ($formats.Count -gt 180) { $formats = @($formats | Select-Object -First 180) }
  return [pscustomobject]@{
    ok = $true
    media = [pscustomobject]@{
      id = [string]$info.id
      title = [string]$info.title
      extractor = [string]$(if ($info.extractor_key) { $info.extractor_key } else { $info.extractor })
      webpage_url = [string]$info.webpage_url
      thumbnail = [string]$info.thumbnail
      duration = $info.duration
      width = $info.width
      height = $info.height
      fps = $info.fps
      live_status = [string]$info.live_status
      formats = $formats
    }
  }
}

$listener = New-Object System.Net.Sockets.TcpListener -ArgumentList @([System.Net.IPAddress]::Loopback, [int]$port)
try { $listener.Start() } catch { exit 0 }

while ($true) {
  $client = $null
  try {
    $client = $listener.AcceptTcpClient()
    $client.ReceiveTimeout = 65000
    $client.SendTimeout = 65000
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader -ArgumentList @($stream, [System.Text.Encoding]::ASCII, $false, 4096, $true)
    $requestLine = $reader.ReadLine()
    if ([string]::IsNullOrWhiteSpace($requestLine)) { continue }
    $requestHeaders = @{}
    while ($true) {
      $line = $reader.ReadLine()
      if ([string]::IsNullOrEmpty($line)) { break }
      $colon = $line.IndexOf(':')
      if ($colon -gt 0) {
        $name = $line.Substring(0, $colon).Trim()
        $value = $line.Substring($colon + 1).Trim()
        $requestHeaders[$name] = $value
      }
    }
    $origin = [string]$requestHeaders['Origin']
    $parts = $requestLine.Split(' ')
    if ($parts.Length -lt 2) { Send-JsonResponse $stream 400 @{ok=$false;error='Malformed request.'} $origin; continue }
    $method = $parts[0].ToUpperInvariant()
    $target = $parts[1]
    if ($origin -and $allowedOrigins -notcontains $origin) { Send-JsonResponse $stream 403 @{ok=$false;error='Origin not allowed.'}; continue }
    if ($method -eq 'OPTIONS') { Send-JsonResponse $stream 204 @{} $origin; continue }
    $uri = [Uri]("http://127.0.0.1:$port$target")
    if ($method -eq 'GET' -and $uri.AbsolutePath -eq '/health') {
      Send-JsonResponse $stream 200 @{ok=$true;service='Galaxy Media Preview';version='1.5.1';ytDlp=(Test-Path $yt)} $origin
      continue
    }
    if ($method -eq 'GET' -and $uri.AbsolutePath -eq '/inspect') {
      if ([string]$requestHeaders['X-Galaxy-Preview'] -ne '1') { Send-JsonResponse $stream 403 @{ok=$false;error='Missing preview request header.'} $origin; continue }
      $q = Parse-Query $uri.Query
      try { $payload = Invoke-YtDlpInspect -Url ([string]$q['url']) -Browser ([string]$q['browser']); Send-JsonResponse $stream 200 $payload $origin }
      catch { Send-JsonResponse $stream 500 @{ok=$false;error=$_.Exception.Message} $origin }
      continue
    }
    Send-JsonResponse $stream 404 @{ok=$false;error='Not found.'} $origin
  } catch {
    try { if ($client -and $client.Connected) { Send-JsonResponse $client.GetStream() 500 @{ok=$false;error='Preview helper error.'} } } catch {}
  } finally {
    if ($client) { try { $client.Close() } catch {} }
  }
}
