param(
    [string]$WorkingDirectory = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [int]$Port = 8765,
    [switch]$Schedule
)

$ErrorActionPreference = "Stop"

function Test-PortInUse {
    param([int]$TargetPort)
    return [bool](Get-NetTCPConnection -LocalPort $TargetPort -State Listen -ErrorAction SilentlyContinue)
}

function Start-BackgroundProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string]$ArgumentList,
        [string]$LogPath
    )
    $command = "& '$FilePath' $ArgumentList *>> '$LogPath' 2>&1"
    Start-Process powershell.exe `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-Command", $command) `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden | Out-Null
    Write-Host "Started $Name. Log: $LogPath"
}

$logDir = Join-Path $WorkingDirectory ".pubmed_digest\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$serveLog = Join-Path $logDir "serve.log"
$ngrokLog = Join-Path $logDir "ngrok.log"

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
    throw "python was not found in PATH."
}

$serveArgs = "-m shoulder_digest serve --host 127.0.0.1 --port $Port"
if ($Schedule) {
    $serveArgs += " --schedule"
}

if (Test-PortInUse -TargetPort $Port) {
    Write-Host "shoulder_digest is already listening on port $Port."
} else {
    Start-BackgroundProcess -Name "shoulder_digest serve" -FilePath $python -ArgumentList $serveArgs -LogPath $serveLog
    Start-Sleep -Seconds 2
}

$ngrok = Get-Command ngrok -ErrorAction SilentlyContinue
if (-not $ngrok) {
    Write-Warning "ngrok was not found in PATH. LINE image delivery requires a public HTTPS tunnel."
} elseif (Get-Process ngrok -ErrorAction SilentlyContinue) {
    Write-Host "ngrok is already running."
} else {
    Start-BackgroundProcess -Name "ngrok" -FilePath $ngrok.Source -ArgumentList "http $Port" -LogPath $ngrokLog
    Start-Sleep -Seconds 2
}

if ($ngrok) {
    $syncResult = & $python -m shoulder_digest sync-ngrok-url --port $Port 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Updated .env with current ngrok URL."
        Write-Host $syncResult
    } else {
        Write-Warning "Could not sync ngrok URL to .env. LINE image delivery may fail until ngrok is running."
        Write-Warning $syncResult
    }
}

Write-Host "Startup complete. UI: http://127.0.0.1:$Port/"
