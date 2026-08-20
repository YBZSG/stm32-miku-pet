param(
    [string]$SnapshotFile = "$PSScriptRoot\..\runtime\dashboard_snapshot.json",
    [int]$UdpPort = 43210,
    [string]$LocalAddress,
    [string]$BroadcastAddress
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
    for ($i=0; $i -lt $count; $i++) {
        $crc = $crc -bxor [uint32]$data[$i]
        for ($bit=0; $bit -lt 8; $bit++) {
            if ($crc -band 1) { $crc = ($crc -shr 1) -bxor [uint32]0xEDB88320L }
            else { $crc = $crc -shr 1 }
        }
    }
    [uint32]($crc -bxor [uint32]0xFFFFFFFFL)
}

[byte[]]$frame = New-Object byte[] 64
$frame[0]=0xA5; $frame[1]=0x5A; $frame[2]=1; $frame[3]=[byte]$states[$stateName]
$sha=[Security.Cryptography.SHA256]::Create()
try { [byte[]]$digest=$sha.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]$snapshot.session_id)) }
finally { $sha.Dispose() }
[uint32]$sessionHash=[BitConverter]::ToUInt32($digest,0)
Set-U32 $frame 4 $sessionHash
Set-U32 $frame 8 ([uint32]$snapshot.sequence)
Set-U32 $frame 12 ([uint32]([math]::Min([uint64][uint32]::MaxValue,[uint64]$snapshot.tokens)))
$frame[16]=[byte][math]::Max(0,[math]::Min(100,[int]$snapshot.remaining))
Set-U32 $frame 17 ([uint32]$snapshot.reset_minutes)
[byte[]]$title=[Text.Encoding]::GetEncoding(936).GetBytes([string]$snapshot.title)
if ($title.Length -gt 36) { $title=$title[0..35] }
$frame[21]=[byte]$title.Length
[Array]::Copy($title,0,$frame,22,$title.Length)
Set-U32 $frame 58 (Get-Crc32 $frame 58)
$frame[62]=0x0D; $frame[63]=0x0A

if (-not $LocalAddress -or -not $BroadcastAddress) {
    $wifi = Get-NetIPConfiguration | Where-Object {
        $_.InterfaceAlias -eq 'WLAN' -and $_.NetAdapter.Status -eq 'Up' -and $_.IPv4Address
    } | Select-Object -First 1
    if (-not $wifi) { throw 'No active network adapter with an IPv4 gateway was found.' }
    $LocalAddress = $wifi.IPv4Address.IPAddress
    $prefix = [int]$wifi.IPv4Address.PrefixLength
    [byte[]]$ipBytes = ([Net.IPAddress]::Parse($LocalAddress)).GetAddressBytes()
    [uint32]$ipValue = ([uint32]$ipBytes[0] -shl 24) -bor ([uint32]$ipBytes[1] -shl 16) -bor ([uint32]$ipBytes[2] -shl 8) -bor $ipBytes[3]
    [uint32]$hostMask = if ($prefix -eq 32) { 0 } else { [uint32]([math]::Pow(2, 32 - $prefix) - 1) }
    [uint32]$broadcastValue = $ipValue -bor $hostMask
    $BroadcastAddress = '{0}.{1}.{2}.{3}' -f (($broadcastValue -shr 24) -band 255),(($broadcastValue -shr 16) -band 255),(($broadcastValue -shr 8) -band 255),($broadcastValue -band 255)
}

$endpoint = [Net.IPEndPoint]::new([Net.IPAddress]::Parse($LocalAddress), 0)
$udp=[Net.Sockets.UdpClient]::new($endpoint)
try {
    $udp.EnableBroadcast=$true
    1..3 | ForEach-Object {
        [void]$udp.Send($frame,$frame.Length,$BroadcastAddress,$UdpPort)
        Start-Sleep -Milliseconds 80
    }
    [pscustomobject]@{ transport='WiFi UDP'; local=$LocalAddress; destination="$BroadcastAddress`:$UdpPort"; sequence=$snapshot.sequence; status=$stateName; title=$snapshot.title }
} finally { $udp.Dispose() }
