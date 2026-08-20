param([string]$Port = 'COM7')

$ErrorActionPreference = 'Stop'
$taskName = 'Codex Pet Background Bridge'
$service = (Resolve-Path "$PSScriptRoot\codex_pet_service.ps1").Path
$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$service`" -Port $Port"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description 'Keeps the STM32 Codex Pet synchronized in the background.' -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Host "Installed and started: $taskName ($Port)"

