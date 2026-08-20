param(
    [string]$SnapshotFile = "$PSScriptRoot\..\runtime\dashboard_snapshot.json",
    [string]$Port = 'COM7',
    [int]$Baud = 115200
)

$ErrorActionPreference = 'Stop'
$snapshot = Get-Content -LiteralPath $SnapshotFile -Raw -Encoding UTF8 | ConvertFrom-Json
$states = @{ idle=0; run_right=1; run_left=2; wave=3; jump=4; failed=5; waiting=6; working=7; review=8 }
$stateName = ([string]$snapshot.status).ToLowerInvariant()
if (-not $states.ContainsKey($stateName)) { $stateName = 'idle' }

function Set-U32([byte[]]$buffer, [int]$offset, [uint32]$value) {
    $buffer[$offset] = [byte]($value -band 0xFF)
    $buffer[$offset + 1] = [byte](($value -shr 8) -band 0xFF)
    $buffer[$offset + 2] = [byte](($value -shr 16) -band 0xFF)
    $buffer[$offset + 3] = [byte](($value -shr 24) -band 0xFF)
}

function Get-Crc32([byte[]]$data, [int]$count) {
    [uint32]$crc = 0xFFFFFFFFL
    for ($i = 0; $i -lt $count; $i++) {
        $crc = $crc -bxor [uint32]$data[$i]
        for ($bit = 0; $bit -lt 8; $bit++) {
            if ($crc -band 1) { $crc = ($crc -shr 1) -bxor [uint32]0xEDB88320L }
            else { $crc = $crc -shr 1 }
        }
    }
    return [uint32]($crc -bxor [uint32]0xFFFFFFFFL)
}

[byte[]]$frame = New-Object byte[] 64
$frame[0] = 0xA5; $frame[1] = 0x5A; $frame[2] = 1; $frame[3] = [byte]$states[$stateName]
$sha = [Security.Cryptography.SHA256]::Create()
try { [byte[]]$sessionDigest = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]$snapshot.session_id)) }
finally { $sha.Dispose() }
[uint32]$sessionHash = [BitConverter]::ToUInt32($sessionDigest, 0)
Set-U32 $frame 4 $sessionHash
Set-U32 $frame 8 ([uint32]$snapshot.sequence)
Set-U32 $frame 12 ([uint32]([math]::Min([uint64][uint32]::MaxValue, [uint64]$snapshot.tokens)))
$frame[16] = [byte][math]::Max(0, [math]::Min(100, [int]$snapshot.remaining))
Set-U32 $frame 17 ([uint32]$snapshot.reset_minutes)
[byte[]]$title = [Text.Encoding]::GetEncoding(936).GetBytes([string]$snapshot.title)
if ($title.Length -gt 36) { $title = $title[0..35] }
$frame[21] = [byte]$title.Length
[Array]::Copy($title, 0, $frame, 22, $title.Length)
$crc = Get-Crc32 $frame 58
Set-U32 $frame 58 $crc
$frame[62] = 0x0D; $frame[63] = 0x0A

$serial = [IO.Ports.SerialPort]::new($Port, $Baud, 'None', 8, 'One')
$serial.ReadTimeout = 1200
$serial.DtrEnable = $false
$serial.RtsEnable = $false
try {
    $serial.Open()
    $serial.DiscardInBuffer()
    $serial.Write($frame, 0, $frame.Length)
    $deadline = [DateTime]::UtcNow.AddMilliseconds(1200)
    $reply = ''
    while ([DateTime]::UtcNow -lt $deadline) {
        $reply += $serial.ReadExisting()
        if ($reply -match 'SNAPSHOT_OK') { break }
        Start-Sleep -Milliseconds 20
    }
    if ($reply -notmatch 'SNAPSHOT_OK') { throw "Dashboard did not acknowledge snapshot. Reply: $reply" }
    [pscustomobject]@{ session=$sessionHash.ToString('X8'); sequence=$snapshot.sequence; status=$stateName; title=$snapshot.title; reply=$reply.Trim() }
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
