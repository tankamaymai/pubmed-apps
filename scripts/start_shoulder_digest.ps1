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

function Get-ShoulderDigestServeProcess {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'shoulder_digest serve' }
}

function Test-ServeHealthy {
    param([int]$TargetPort)
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$TargetPort/healthz" -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Stop-ShoulderDigestServe {
    $existing = Get-ShoulderDigestServeProcess
    foreach ($proc in $existing) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($existing) {
        Start-Sleep -Seconds 2
    }
}

function Start-ShoulderDigestServe {
    param(
        [string]$FilePath,
        [string]$ArgumentList,
        [string]$LogPath
    )
    Stop-ShoulderDigestServe
    Start-BackgroundProcess -Name "shoulder_digest serve" -FilePath $FilePath -ArgumentList $ArgumentList -LogPath $LogPath
    Start-Sleep -Seconds 2
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

$serveHealthy = Test-ServeHealthy -TargetPort $Port
if ($Schedule -or -not $serveHealthy) {
    if ($Schedule) {
        Write-Host "Restarting shoulder_digest serve to apply daily scheduler."
    } elseif (Test-PortInUse -TargetPort $Port) {
        Write-Host "shoulder_digest port $Port is open but unhealthy. Restarting."
    } else {
        Write-Host "shoulder_digest is not running. Starting serve."
    }
    Start-ShoulderDigestServe -FilePath $python -ArgumentList $serveArgs -LogPath $serveLog
} else {
    Write-Host "shoulder_digest is healthy on port $Port."
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

$dailyTask = Get-ScheduledTask -TaskName "ShoulderPubMedDigest" -ErrorAction SilentlyContinue
if (-not $dailyTask) {
    Write-Host "Registering daily Windows task ShoulderPubMedDigest at 07:00."
    & (Join-Path $PSScriptRoot "install_windows_task.ps1")
}

if (-not (Test-ServeHealthy -TargetPort $Port)) {
    throw "shoulder_digest failed health check on http://127.0.0.1:$Port/healthz"
}

Write-Host "Startup complete. UI: http://127.0.0.1:$Port/"
