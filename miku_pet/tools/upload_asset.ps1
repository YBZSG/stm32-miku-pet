param(
    [Parameter(Mandatory = $true)][string]$Port,
    [Parameter(Mandatory = $true)][string]$Asset,
    [int]$Baud = 115200
)

$ErrorActionPreference = 'Stop'
$assetPath = (Resolve-Path -LiteralPath $Asset).Path
$payload = [IO.File]::ReadAllBytes($assetPath)
if ($payload.Length -lt 20 -or [Text.Encoding]::ASCII.GetString($payload, 0, 4) -ne 'MPET') {
    throw 'Input is not an MPET package.'
}

function Get-Crc32([byte[]]$Data) {
    [uint32]$crc = [uint32]::MaxValue
    [uint32]$polynomial = [Convert]::ToUInt32('EDB88320', 16)
    foreach ($value in $Data) {
        $crc = $crc -bxor $value
        for ($bit = 0; $bit -lt 8; $bit++) {
            if (($crc -band 1) -ne 0) {
                $crc = ($crc -shr 1) -bxor $polynomial
            } else {
                $crc = $crc -shr 1
            }
        }
    }
    return $crc -bxor [uint32]::MaxValue
}

function Wait-DeviceLine($Serial, [string]$Expected, [int]$TimeoutSeconds) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $line = $Serial.ReadLine().Trim()
            if ($line) { Write-Host $line }
            if ($line.Contains($Expected)) { return }
        } catch [TimeoutException] {}
    }
    throw "Timed out waiting for $Expected"
}

[uint32]$crc = Get-Crc32 $payload
Write-Host ("Uploading {0} bytes, CRC32={1:X8}" -f $payload.Length, $crc)

$serial = [IO.Ports.SerialPort]::new($Port, $Baud, 'None', 8, 'One')
$serial.ReadTimeout = 1000
$serial.WriteTimeout = 10000
$serial.NewLine = "`n"
try {
    $serial.Open()
    Start-Sleep -Milliseconds 2000
    $serial.DiscardInBuffer()
    $command = [byte[]]@([byte][char]'U')
    $metadata = New-Object byte[] 8
    [BitConverter]::GetBytes([uint32]$payload.Length).CopyTo($metadata, 0)
    [BitConverter]::GetBytes($crc).CopyTo($metadata, 4)
    $serial.Write($command, 0, 1)
    $serial.BaseStream.Flush()
    Start-Sleep -Milliseconds 100
    $serial.Write($metadata, 0, $metadata.Length)
    Wait-DeviceLine $serial 'UPLOAD_READY' 60

    $sent = 0
    while ($sent -lt $payload.Length) {
        $count = [Math]::Min(256, $payload.Length - $sent)
        $serial.Write($payload, $sent, $count)
        $sent += $count
        Start-Sleep -Milliseconds 15
        if (($sent % 65536) -eq 0 -or $sent -eq $payload.Length) {
            Write-Host "$sent/$($payload.Length)"
        }
    }
    Wait-DeviceLine $serial 'UPLOAD_OK' 120
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
