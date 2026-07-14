param(
    [string]$DataDir = (Join-Path $env:APPDATA "org.reefvision.desktop"),
    [string[]]$Only
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "ReefVision's Python environment is missing. Run .\scripts\bootstrap.ps1 first."
}

$Catalog = Join-Path $Root "config\model_catalog.json"
$Installer = Join-Path $PSScriptRoot "install-remaining-models.py"
$Repair = Join-Path $PSScriptRoot "repair-optional-model-catalog.py"
$ConfigDir = Join-Path $DataDir "config"

Write-Host "Closing ReefVision before modifying its managed model catalog..." -ForegroundColor Cyan
Get-Process *reefvision* -ErrorAction SilentlyContinue | Stop-Process -Force

New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null

# Force both the development shell and packaged backend to use the same model
# store and local catalogue override.
[Environment]::SetEnvironmentVariable("REEFVISION_CONFIG_DIR", $ConfigDir, "User")
[Environment]::SetEnvironmentVariable("REEFVISION_DESKTOP_DATA_DIR", $DataDir, "User")
$env:REEFVISION_CONFIG_DIR = $ConfigDir
$env:REEFVISION_DESKTOP_DATA_DIR = $DataDir

$Arguments = @(
    $Installer,
    "--data-dir", $DataDir,
    "--catalog", $Catalog
)
foreach ($Selection in $Only) {
    $Arguments += @("--only", $Selection)
}

Write-Host "Installing 18 optional ReefVision model checkpoints..." -ForegroundColor Cyan
& $Python @Arguments
$ExitCode = $LASTEXITCODE
if ($ExitCode -ne 0) {
    throw "The optional model pack completed with one or more failed checkpoints. Review the messages above."
}

Write-Host "Repairing optional-model availability metadata..." -ForegroundColor Cyan
& $Python $Repair "--data-dir" $DataDir
$RepairExitCode = $LASTEXITCODE
if ($RepairExitCode -ne 0) {
    throw "The optional model catalogue repair failed. Review the messages above."
}

Write-Host "Optional model pack installation completed." -ForegroundColor Green
Write-Host "Launch the latest branch with .\scripts\launch-latest-model-pack.ps1" -ForegroundColor Green
