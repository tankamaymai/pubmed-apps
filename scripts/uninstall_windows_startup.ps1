param(
    [string]$TaskName = "ShoulderPubMedDigestStartup"
)

$ErrorActionPreference = "Stop"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Unregistered Windows startup task '$TaskName'."
} else {
    Write-Host "Startup task '$TaskName' was not found."
}
