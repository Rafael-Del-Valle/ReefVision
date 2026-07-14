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
$ConfigDir = Join-Path $DataDir "config"

Write-Host "Closing ReefVision before modifying its managed model catalog..." -ForegroundColor Cyan
Get-Process *reefvision* -ErrorAction SilentlyContinue | Stop-Process -Force

New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null

# The rebuilt desktop resolves this AppData catalog path automatically.
# Persisting the variable also lets the currently installed 1.7.0 shell discover
# the local catalog definition immediately after it is restarted.
[Environment]::SetEnvironmentVariable("REEFVISION_CONFIG_DIR", $ConfigDir, "User")
$env:REEFVISION_CONFIG_DIR = $ConfigDir

$Arguments = @(
    $Installer,
    "--data-dir", $DataDir,
    "--catalog", $Catalog
)
foreach ($Selection in $Only) {
    $Arguments += @("--only", $Selection)
}

Write-Host "Installing the optional ReefVision model pack..." -ForegroundColor Cyan
& $Python @Arguments
$ExitCode = $LASTEXITCODE
if ($ExitCode -ne 0) {
    throw "The optional model pack completed with one or more failed checkpoints. Review the messages above."
}

Write-Host "Optional model pack installation completed." -ForegroundColor Green
Write-Host "Rebuild and reinstall the latest branch revision, then reopen Model Hub and choose Refresh catalog." -ForegroundColor Green
