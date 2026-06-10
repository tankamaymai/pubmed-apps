$ErrorActionPreference = "Stop"
$out = Join-Path $PSScriptRoot "..\schemas\codex_app_server\generated"
New-Item -ItemType Directory -Force -Path $out | Out-Null
codex app-server generate-json-schema --out $out
Write-Host "Codex app-server schemas written to $out"

