param(
    [string]$Port = 'COM7',
    [string]$StateFile = "$PSScriptRoot\..\runtime\codex_pet_state.txt",
    [string]$TitleFile = "$PSScriptRoot\..\runtime\codex_pet_session.txt",
    [string]$SessionFile,
    [int]$Baud = 115200
)

$ErrorActionPreference = 'Stop'
$commands = @{
    idle='0'; run_right='1'; run_left='2'; wave='3'; jump='4'; failed='5'
    waiting='6'; working='7'; review='8'; look_right='R'; look_left='L'
}
$stateIds = @{
    idle=0; run_right=1; run_left=2; wave=3; jump=4; failed=5
    waiting=6; working=7; review=8; look_right=9; look_left=10
}
$script:usageValid = $false
$script:totalTokens = 0
$script:remainingPercent = 0
$script:resetMinutes = 0

function Write-PetPacket([IO.Ports.SerialPort]$Serial, [string]$Packet) {
    # New firmware stores RX bytes in an interrupt-driven ring buffer.
    $Serial.Write($Packet)
}

function Send-PetTitle([IO.Ports.SerialPort]$Serial, [string]$Title) {
    if ([string]::IsNullOrWhiteSpace($Title)) { return }
    $clean = (($Title -replace '[\r\n\t]+', ' ') -replace '\s+', ' ').Trim()
    if ($clean.Length -gt 18) { $clean = $clean.Substring(0, 18) }
    $encoding = [Text.Encoding]::GetEncoding(936)
    [byte[]]$bytes = $encoding.GetBytes($clean)
    [byte[]]$prefix = @([byte][char]'@', [byte][char]'T', [byte][char]',')
    [byte[]]$packet = $prefix + $bytes + [byte[]]@([byte]10)
    # Keep the title frame separate from the immediately preceding dashboard
    # frame. The MCU may redraw the LCD as soon as it parses that first frame.
    Start-Sleep -Milliseconds 300
    # The interrupt-buffered firmware replies immediately. Verify delivery
    # briefly, with one retry only, so title reliability cannot stall status.
    for ($attempt = 1; $attempt -le 2; $attempt++) {
        $Serial.DiscardInBuffer()
        $Serial.Write($packet, 0, $packet.Length)
        $deadline = [DateTime]::UtcNow.AddMilliseconds(600)
        $reply = ''
        while ([DateTime]::UtcNow -lt $deadline) {
            $reply += $Serial.ReadExisting()
            if ($reply -match ("TITLE_OK\s+{0}" -f $bytes.Length)) {
                Write-Host "pet_title=$clean ack=ok attempt=$attempt"
                return
            }
            Start-Sleep -Milliseconds 20
        }
    }
    $replyVisible = $reply -replace "`r", '<CR>' -replace "`n", '<LF>'
    Write-Host ("pet_title={0} ack=timeout bytes={1} reply={2}" -f
        $clean, [BitConverter]::ToString($packet), $replyVisible)
}

function Send-PetSnapshot([IO.Ports.SerialPort]$Serial) {
    if (-not $script:usageValid -or -not $stateIds.ContainsKey($script:currentState)) { return }
    $packet = "@{0},{1},{2},{3}`n" -f $stateIds[$script:currentState],
        $script:totalTokens, $script:remainingPercent, $script:resetMinutes
    Write-PetPacket $Serial $packet
    Write-Host ("pet_state={0} tokens={1} remaining={2}% reset={3}min" -f
        $script:currentState, $script:totalTokens, $script:remainingPercent, $script:resetMinutes)
}

function Send-PetState([IO.Ports.SerialPort]$Serial, [string]$State) {
    $normalized = $State.Trim().ToLowerInvariant()
    if (-not $commands.ContainsKey($normalized)) { return }
    if ($script:currentState -eq $normalized) { return }
    $script:currentState = $normalized
    if ($script:usageValid) {
        Send-PetSnapshot $Serial
    } else {
        $Serial.Write($commands[$normalized])
        Write-Host "pet_state=$normalized usage=unavailable"
    }
}

function Sync-PetAfterBoot([IO.Ports.SerialPort]$Serial) {
    # RESET only restarts the STM32; Windows keeps COM7 open.  The board loses
    # its RAM dashboard/title while the bridge still believes they were sent.
    # Re-send the complete snapshot after the firmware has finished booting.
    Start-Sleep -Milliseconds 3000
    $Serial.DiscardInBuffer()
    if ($script:usageValid) {
        Send-PetSnapshot $Serial
    } elseif ($commands.ContainsKey($script:currentState)) {
        $Serial.Write($commands[$script:currentState])
        Write-Host "pet_resync_state=$($script:currentState) usage=unavailable"
    }
    Start-Sleep -Milliseconds 500
    $title = (Get-Content -LiteralPath $TitleFile -Raw -Encoding UTF8).Trim()
    Send-PetTitle $Serial $title
    $script:lastSentTitle = $title
    Write-Host 'pet_boot_resync=complete'
}

function Process-SessionLine([IO.Ports.SerialPort]$Serial, [string]$Line) {
    if ([string]::IsNullOrWhiteSpace($Line)) { return }
    try {
        $event = $Line | ConvertFrom-Json
        if ($event.type -eq 'event_msg') {
            if ($event.payload.type -eq 'token_count' -and $event.payload.info) {
                $script:totalTokens = [uint64]$event.payload.info.total_token_usage.total_tokens
                if ($event.payload.rate_limits.primary) {
                    $used = [double]$event.payload.rate_limits.primary.used_percent
                    $script:remainingPercent = [math]::Max(0, [math]::Min(100, [math]::Round(100 - $used)))
                    $resetAt = [DateTimeOffset]::FromUnixTimeSeconds([int64]$event.payload.rate_limits.primary.resets_at)
                    $script:resetMinutes = [math]::Max(0, [math]::Ceiling(($resetAt - [DateTimeOffset]::UtcNow).TotalMinutes))
                    $script:usageValid = $true
                    Send-PetSnapshot $Serial
                }
            } elseif ($event.payload.type -eq 'task_complete') {
                Send-PetState $Serial 'idle'
            } elseif ($event.payload.type -eq 'user_message') {
                if (-not [string]::IsNullOrWhiteSpace($event.payload.message)) {
                    $title = (($event.payload.message -replace '[\r\n\t]+', ' ') -replace '\s+', ' ').Trim()
                    if ($title.Length -gt 18) { $title = $title.Substring(0, 18) }
                    [IO.File]::WriteAllText($TitleFile, $title, [Text.Encoding]::UTF8)
                    Send-PetTitle $Serial $title
                    $script:lastSentTitle = $title
                }
                Send-PetState $Serial 'working'
            } elseif ($event.payload.type -eq 'task_started') {
                Send-PetState $Serial 'working'
            } elseif ($event.payload.type -eq 'turn_aborted') {
                Send-PetState $Serial 'failed'
            }
        } elseif ($event.type -eq 'response_item' -and
                  $event.payload.type -eq 'custom_tool_call' -and
                  $event.payload.status -ne 'completed') {
            Send-PetState $Serial 'working'
        }
    } catch {
        Write-Host "Ignored malformed session line"
    }
}

$autoSession = -not $PSBoundParameters.ContainsKey('SessionFile')
if ($autoSession) {
    $SessionFile = Get-ChildItem "$env:USERPROFILE\.codex\sessions" -Recurse -File -Filter '*.jsonl' |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $SessionFile) { throw 'No Codex session log was found.' }

$stateDirectory = Split-Path -Parent $StateFile
if (-not (Test-Path -LiteralPath $stateDirectory)) {
    New-Item -ItemType Directory -Path $stateDirectory | Out-Null
}
if (-not (Test-Path -LiteralPath $StateFile)) {
    Set-Content -LiteralPath $StateFile -Value 'idle' -Encoding ascii
}
if (-not (Test-Path -LiteralPath $TitleFile)) {
    Set-Content -LiteralPath $TitleFile -Value 'STM32 PET' -Encoding utf8
}

$serial = [IO.Ports.SerialPort]::new($Port, $Baud, 'None', 8, 'One')
$serial.DtrEnable = $false
$serial.RtsEnable = $false
$serial.Open()
Write-Host 'Codex Pet Bridge v3 (reliable tail + auto session follow)'
$filePosition = (Get-Item -LiteralPath $SessionFile).Length
$pendingText = ''
$script:currentState = ''
$lastStateWrite = [DateTime]::MinValue
$lastTitleWrite = [DateTime]::MinValue
$lastSessionEvent = [DateTime]::UtcNow
$lastBootResync = [DateTime]::MinValue

try {
    Send-PetState $serial ((Get-Content -LiteralPath $StateFile -Raw).Trim())
    Write-Host "Watching $SessionFile"
    while ($true) {
        if ($autoSession) {
            $newestSession = Get-ChildItem "$env:USERPROFILE\.codex\sessions" -Recurse -File -Filter '*.jsonl' |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
            if ($newestSession -and $newestSession -ne $SessionFile) {
                $SessionFile = $newestSession
                $filePosition = (Get-Item -LiteralPath $SessionFile).Length
                $pendingText = ''
                Write-Host "Switched to $SessionFile"
            }
        }
        $stateInfo = Get-Item -LiteralPath $StateFile
        if ($stateInfo.LastWriteTimeUtc -gt $lastStateWrite) {
            $lastStateWrite = $stateInfo.LastWriteTimeUtc
            Send-PetState $serial (Get-Content -LiteralPath $StateFile -Raw)
        }
        $titleInfo = Get-Item -LiteralPath $TitleFile
        if ($titleInfo.LastWriteTimeUtc -gt $lastTitleWrite) {
            $lastTitleWrite = $titleInfo.LastWriteTimeUtc
            $title = (Get-Content -LiteralPath $TitleFile -Raw -Encoding UTF8).Trim()
            if ($title -ne $script:lastSentTitle) {
                Send-PetTitle $serial $title
                $script:lastSentTitle = $title
            }
        }

        $sessionLength = (Get-Item -LiteralPath $SessionFile).Length
        if ($sessionLength -lt $filePosition) {
            $filePosition = 0
            $pendingText = ''
        }
        if ($sessionLength -gt $filePosition) {
            $readStream = [IO.File]::Open($SessionFile, 'Open', 'Read', 'ReadWrite')
            try {
                $readStream.Seek($filePosition, 'Begin') | Out-Null
                $byteCount = [int]($sessionLength - $filePosition)
                $bytes = New-Object byte[] $byteCount
                $actual = $readStream.Read($bytes, 0, $byteCount)
                $filePosition += $actual
            } finally {
                $readStream.Dispose()
            }
            if ($actual -gt 0) {
                $pendingText += [Text.Encoding]::UTF8.GetString($bytes, 0, $actual)
                $parts = $pendingText -split "`n", -1
                $pendingText = $parts[-1]
                for ($index = 0; $index -lt $parts.Count - 1; $index++) {
                    $lastSessionEvent = [DateTime]::UtcNow
                    Process-SessionLine $serial $parts[$index].TrimEnd("`r")
                }
            }
        }

        if ($script:currentState -eq 'working' -and
            ([DateTime]::UtcNow - $lastSessionEvent).TotalSeconds -gt 30) {
            Send-PetState $serial 'waiting'
        }

        # Firmware emits READY messages after an MCU RESET.  Since the USB
        # serial adapter itself does not disconnect, this is our reboot signal.
        $deviceText = $serial.ReadExisting()
        if ($deviceText -match '(?:UPLOAD|AUDIO|RADAR)_READY|MPET ready' -and
            ([DateTime]::UtcNow - $lastBootResync).TotalSeconds -gt 5) {
            $lastBootResync = [DateTime]::UtcNow
            Write-Host 'pet_boot_detected=1'
            Sync-PetAfterBoot $serial
        }
        Start-Sleep -Milliseconds 200
    }
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
