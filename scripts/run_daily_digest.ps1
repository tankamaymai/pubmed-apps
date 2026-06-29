param(
    [string]$WorkingDirectory = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
Set-Location $WorkingDirectory

& (Join-Path $PSScriptRoot "start_shoulder_digest.ps1") -WorkingDirectory $WorkingDirectory -Port $Port

python -m shoulder_digest run @args
