$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

. (Join-Path $PSScriptRoot "lib\node-tools.ps1")
$NodeTools = Ensure-ReefVisionNodeTools
$null = Ensure-ReefVisionRustTools -Purpose "run ReefVision in Tauri desktop development mode"
Assert-ReefVisionPublicLockfile -NodeTools $NodeTools

if (-not (Test-Path ".venv" -PathType Container)) {
    throw "Run .\scripts\bootstrap.ps1 first."
}

if (-not (Test-Path "apps\web\node_modules" -PathType Container)) {
    throw "Web dependencies are not installed. Run .\scripts\bootstrap.ps1 first."
}

$env:REEFVISION_DESKTOP_DATA_DIR = Join-Path $Root ".desktop\dev-data"
Write-Host "Desktop dev data: $env:REEFVISION_DESKTOP_DATA_DIR" -ForegroundColor DarkGray

Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @("--prefix", "apps/web", "run", "desktop:dev")
