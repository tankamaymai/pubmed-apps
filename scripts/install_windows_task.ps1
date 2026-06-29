param(
    [string]$TaskName = "ShoulderPubMedDigest",
    [string]$Time = "07:00",
    [string]$PowerShell = "powershell.exe",
    [string]$WorkingDirectory = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$runScript = Join-Path $PSScriptRoot "run_daily_digest.ps1"
$action = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runScript`"" `
    -WorkingDirectory $WorkingDirectory

$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

if ($DryRun) {
    Write-Host "Would register task '$TaskName'"
    Write-Host "WorkingDirectory: $WorkingDirectory"
    Write-Host "Command: $PowerShell -File $runScript"
    Write-Host "Daily time: $Time"
    exit 0
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Daily PubMed shoulder digest via local Codex/ImageGen and LINE approval workflow." `
    -Force | Out-Null

Write-Host "Registered Windows scheduled task '$TaskName' at $Time."

