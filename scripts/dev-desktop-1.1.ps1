# Laptop-first ReefVision 1.1 development launcher.
# Uses an isolated QA data root; does not change public package metadata,
# install an MSI, download model weights, or perform user acceptance tests.
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$WebModules = Join-Path $Root "apps\web\node_modules"
$DataRoot = Join-Path $env:LOCALAPPDATA "ReefVision\laptop-qa-1.1\desktop"

$CurrentBranch = (& git -C $Root branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $CurrentBranch -notmatch 'reefvision-1\.1') {
    throw "This launcher is reserved for the isolated ReefVision 1.1 development branch. Current: $CurrentBranch"
}
if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    throw "Missing .venv Python: $VenvPython. Set up the environment before launching."
}
if (-not (Test-Path -LiteralPath $WebModules -PathType Container)) {
    throw "Missing frontend modules: $WebModules. Install app dependencies before launching."
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "npm.cmd is unavailable on PATH."
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Cargo is unavailable on PATH."
}

$Previous = @{
    PYTHONPATH = $env:PYTHONPATH
    REEFVISION_DESKTOP_DATA_DIR = $env:REEFVISION_DESKTOP_DATA_DIR
    CUDA_VISIBLE_DEVICES = $env:CUDA_VISIBLE_DEVICES
    HF_HUB_OFFLINE = $env:HF_HUB_OFFLINE
    VITE_REEFVISION_DEV_LINE = $env:VITE_REEFVISION_DEV_LINE
}

try {
    New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null
    $env:PYTHONPATH = Join-Path $Root "apps\api"
    $env:REEFVISION_DESKTOP_DATA_DIR = $DataRoot
    $env:CUDA_VISIBLE_DEVICES = "-1"
    $env:HF_HUB_OFFLINE = "1"
    $env:VITE_REEFVISION_DEV_LINE = "1.1.0-dev"

    Write-Host "ReefVision 1.1 development — laptop" -ForegroundColor Cyan
    Write-Host "Source branch: $CurrentBranch"
    Write-Host "Data directory: $DataRoot"
    Write-Host "Display line: $env:VITE_REEFVISION_DEV_LINE"
    Write-Host "Base package version remains 1.0.2 pending Early Access packaging."

    Push-Location $Root
    try {
        & npm.cmd --prefix apps/web run desktop:dev
        if ($LASTEXITCODE -ne 0) {
            throw "ReefVision Tauri development launch failed: $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:PYTHONPATH = $Previous.PYTHONPATH
    $env:REEFVISION_DESKTOP_DATA_DIR = $Previous.REEFVISION_DESKTOP_DATA_DIR
    $env:CUDA_VISIBLE_DEVICES = $Previous.CUDA_VISIBLE_DEVICES
    $env:HF_HUB_OFFLINE = $Previous.HF_HUB_OFFLINE
    $env:VITE_REEFVISION_DEV_LINE = $Previous.VITE_REEFVISION_DEV_LINE
}
