param(
    [string]$TaskName = "ShoulderPubMedDigestStartup",
    [int]$DelaySeconds = 30,
    [string]$WorkingDirectory = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$startScript = Join-Path $PSScriptRoot "start_shoulder_digest.ps1"
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`" -Schedule"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $arguments `
    -WorkingDirectory $WorkingDirectory

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
if ($DelaySeconds -gt 0) {
    $trigger.Delay = "PT${DelaySeconds}S"
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

if ($DryRun) {
    Write-Host "Would register startup task '$TaskName'"
    Write-Host "WorkingDirectory: $WorkingDirectory"
    Write-Host "Command: powershell.exe $arguments"
    Write-Host "Trigger: At logon for $env:USERNAME (delay ${DelaySeconds}s)"
    exit 0
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Start shoulder digest server and ngrok when the user logs in." `
    -Force | Out-Null

Write-Host "Registered Windows startup task '$TaskName'."
Write-Host "It starts serve --schedule and ngrok ${DelaySeconds}s after logon."
