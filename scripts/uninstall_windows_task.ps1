param(
    [string]$TaskName = "ShoulderPubMedDigest"
)

$ErrorActionPreference = "Stop"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Unregistered Windows scheduled task '$TaskName'."
} else {
    Write-Host "Scheduled task '$TaskName' was not found."
}

