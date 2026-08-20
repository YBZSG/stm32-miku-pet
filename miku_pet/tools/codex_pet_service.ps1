param(
    [string]$Port = 'COM7',
    [int]$Baud = 115200
)

$ErrorActionPreference = 'Continue'
$bridge = Join-Path $PSScriptRoot 'codex_pet_bridge.ps1'
$runtime = Join-Path (Split-Path $PSScriptRoot -Parent) 'runtime'
$log = Join-Path $runtime 'codex_pet_service.log'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null

while ($true) {
    try {
        "$(Get-Date -Format s) starting bridge on $Port" | Add-Content -LiteralPath $log
        & $bridge -Port $Port -Baud $Baud *>> $log
    } catch {
        "$(Get-Date -Format s) $($_.Exception.Message)" | Add-Content -LiteralPath $log
    }
    Start-Sleep -Seconds 5
}

