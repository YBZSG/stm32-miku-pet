param(
    [string]$SessionFile,
    [string]$OutputFile = "$PSScriptRoot\..\runtime\dashboard_snapshot.json"
)

$ErrorActionPreference = 'Stop'
$utf8 = [Text.UTF8Encoding]::new($false)
$OutputFile = [IO.Path]::GetFullPath($OutputFile)

if (-not $SessionFile) {
    $SessionFile = Get-ChildItem "$env:USERPROFILE\.codex\sessions" -Recurse -File -Filter '*.jsonl' |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $SessionFile) { throw 'No Codex session was found.' }

$sessionId = ''
$title = 'CODEX PET'
$status = 'idle'
$eventTime = [DateTimeOffset]::MinValue
[uint64]$tokens = 0
$remaining = 0
$resetMinutes = 0

$stream = [IO.File]::Open($SessionFile, 'Open', 'Read', 'ReadWrite')
$reader = [IO.StreamReader]::new($stream, $utf8, $true, 65536)
try {
    while (($line = $reader.ReadLine()) -ne $null) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try { $event = $line | ConvertFrom-Json } catch { continue }
        $timestamp = [DateTimeOffset]::MinValue
        if ($event.timestamp) { [DateTimeOffset]::TryParse($event.timestamp, [ref]$timestamp) | Out-Null }

        if ($event.type -eq 'session_meta') {
            $sessionId = [string]$event.payload.session_id
            continue
        }
        if ($event.type -ne 'event_msg') { continue }

        switch ($event.payload.type) {
            'task_started' {
                $status = 'working'
                $eventTime = $timestamp
            }
            'user_message' {
                if (-not [string]::IsNullOrWhiteSpace($event.payload.message)) {
                    $title = (([string]$event.payload.message -replace '[\r\n\t]+', ' ') -replace '\s+', ' ').Trim()
                    if ($title.Length -gt 18) { $title = $title.Substring(0, 18) }
                }
                $status = 'working'
                $eventTime = $timestamp
            }
            'task_complete' {
                $status = 'idle'
                $eventTime = $timestamp
            }
            'turn_aborted' {
                $status = 'failed'
                $eventTime = $timestamp
            }
            'token_count' {
                if ($event.payload.info.total_token_usage) {
                    $tokens = [uint64]$event.payload.info.total_token_usage.total_tokens
                }
                if ($event.payload.rate_limits.primary) {
                    $used = [double]$event.payload.rate_limits.primary.used_percent
                    $remaining = [int][math]::Max(0, [math]::Min(100, [math]::Round(100 - $used)))
                    $resetAt = [DateTimeOffset]::FromUnixTimeSeconds([int64]$event.payload.rate_limits.primary.resets_at)
                    $resetMinutes = [int][math]::Max(0, [math]::Ceiling(($resetAt - [DateTimeOffset]::UtcNow).TotalMinutes))
                }
            }
        }
    }
} finally {
    $reader.Dispose()
    $stream.Dispose()
}

$previousSequence = 0
if (Test-Path -LiteralPath $OutputFile) {
    try { $previousSequence = [uint64]((Get-Content -LiteralPath $OutputFile -Raw -Encoding UTF8 | ConvertFrom-Json).sequence) } catch {}
}
$snapshot = [ordered]@{
    protocol = 1
    session_id = $sessionId
    sequence = $previousSequence + 1
    event_time = $eventTime.ToUniversalTime().ToString('o')
    generated_at = [DateTimeOffset]::UtcNow.ToString('o')
    status = $status
    title = $title
    tokens = $tokens
    remaining = $remaining
    reset_minutes = $resetMinutes
    source_file = $SessionFile
}

$directory = Split-Path -Parent $OutputFile
if (-not (Test-Path -LiteralPath $directory)) { New-Item -ItemType Directory -Path $directory -Force | Out-Null }
$temporary = "$OutputFile.tmp"
[IO.File]::WriteAllText($temporary, ($snapshot | ConvertTo-Json -Depth 4), $utf8)
if (Test-Path -LiteralPath $OutputFile) {
    [IO.File]::Copy($temporary, $OutputFile, $true)
    [IO.File]::Delete($temporary)
} else {
    [IO.File]::Move($temporary, $OutputFile)
}
$snapshot | ConvertTo-Json -Depth 4
