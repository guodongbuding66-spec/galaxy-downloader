param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('x64', 'arm64')]
    [string]$Architecture,

    [Parameter(Mandatory = $true)]
    [string[]]$Path
)

$ErrorActionPreference = 'Stop'

function Get-PeMachine([string]$FilePath) {
    $Resolved = [System.IO.Path]::GetFullPath($FilePath)
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

$ExpectedMachine = if ($Architecture -eq 'arm64') { 0xAA64 } else { 0x8664 }
foreach ($Candidate in $Path) {
    $ActualMachine = Get-PeMachine $Candidate
    if ($ActualMachine -ne $ExpectedMachine) {
        throw ("PE architecture mismatch for {0}: expected {1} (0x{2:X4}), got 0x{3:X4}" -f $Candidate, $Architecture, $ExpectedMachine, $ActualMachine)
    }
    Write-Host ("Verified {0} as native {1} PE (0x{2:X4})" -f $Candidate, $Architecture, $ActualMachine)
}
