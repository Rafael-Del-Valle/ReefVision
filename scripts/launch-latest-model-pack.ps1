param(
    [string]$DataDir = (Join-Path $env:APPDATA "org.reefvision.desktop")
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$ConfigDir = Join-Path $DataDir "config"
$CatalogPath = Join-Path $ConfigDir "model_catalog.json"
$ManifestPath = Join-Path $DataDir "models\catalog-models\manifest.json"

if (-not (Test-Path -LiteralPath $CatalogPath -PathType Leaf)) {
    throw "The optional model catalog is missing at $CatalogPath. Run .\scripts\install-remaining-models.ps1 first."
}
if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    throw "The managed model manifest is missing at $ManifestPath. Run .\scripts\install-remaining-models.ps1 first."
}

$Catalog = Get-Content -LiteralPath $CatalogPath -Raw | ConvertFrom-Json
$SegmentationModels = @(
    $Catalog.models | Where-Object {
        $_.task -eq "segment" -and
        $_.availability -eq "available" -and
        $_.selection_kind -eq "managed_catalog_model"
    }
)
if ($SegmentationModels.Count -eq 0) {
    throw "The local catalog contains no available segmentation models. Pull the latest branch and rerun .\scripts\install-remaining-models.ps1."
}

$env:REEFVISION_DESKTOP_DATA_DIR = $DataDir
$env:REEFVISION_CONFIG_DIR = $ConfigDir
[Environment]::SetEnvironmentVariable("REEFVISION_DESKTOP_DATA_DIR", $DataDir, "User")
[Environment]::SetEnvironmentVariable("REEFVISION_CONFIG_DIR", $ConfigDir, "User")

Write-Host "Using ReefVision data directory: $DataDir" -ForegroundColor Cyan
Write-Host "Using model catalog: $CatalogPath" -ForegroundColor Cyan
Write-Host "Available segmentation models: $($SegmentationModels.Count)" -ForegroundColor Green
$SegmentationModels | Select-Object display_name, catalog_id, installation_state | Format-Table -AutoSize

Get-Process *reefvision* -ErrorAction SilentlyContinue | Stop-Process -Force

Write-Host "Launching the latest ReefVision branch..." -ForegroundColor Cyan
npm.cmd run dev:desktop
