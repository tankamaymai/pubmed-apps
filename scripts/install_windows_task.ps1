param(
    [string]$TaskName = "ShoulderPubMedDigest",
    [string]$Time = "07:00",
    [string]$Python = "python",
    [string]$WorkingDirectory = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "-m shoulder_digest run" `
    -WorkingDirectory $WorkingDirectory

$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

if ($DryRun) {
    Write-Host "Would register task '$TaskName'"
    Write-Host "WorkingDirectory: $WorkingDirectory"
    Write-Host "Command: $Python -m shoulder_digest run"
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

