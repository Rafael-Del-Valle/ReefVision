param(
    [ValidateSet("x86_64-pc-windows-msvc", "i686-pc-windows-msvc", "aarch64-pc-windows-msvc")]
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

. (Join-Path $PSScriptRoot "lib\node-tools.ps1")
$NodeTools = Ensure-ReefVisionNodeTools
$RustTools = Ensure-ReefVisionRustTools -Purpose "build the ReefVision desktop installer" -TargetTriple $TargetTriple
Assert-ReefVisionPublicLockfile -NodeTools $NodeTools

$TauriConfigPath = Join-Path $Root "apps\web\src-tauri\tauri.conf.json"
$TauriConfig = Get-Content -LiteralPath $TauriConfigPath -Raw | ConvertFrom-Json
if ($TauriConfig.bundle.resources.'binaries/' -ne 'backend/') {
    throw "Tauri must map the complete staged binaries directory to backend/."
}
if ($TauriConfig.bundle.resources.'../../../.desktop/bundled-models/' -ne 'bundled-models/') {
    throw "Tauri must package the verified catalog checkpoints as bundled-models/."
}

if (-not (Test-Path ".venv" -PathType Container)) {
    throw "Run .\scripts\bootstrap.ps1 first."
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$HydrateScript = Join-Path $PSScriptRoot "hydrate-desktop-model-catalog.py"
$BundleScript = Join-Path $PSScriptRoot "stage-bundled-models.py"
$SourceModelCatalog = Join-Path $Root "config\model_catalog.json"
$BundlePolicy = Join-Path $Root "config\desktop_ready_models.json"
$GeneratedConfig = Join-Path $Root ".desktop\generated-config"
$ModelCatalog = Join-Path $GeneratedConfig "model_catalog.json"
$BundledModels = Join-Path $Root ".desktop\bundled-models"

New-Item -ItemType Directory -Path $GeneratedConfig -Force | Out-Null

Write-ReefVisionStep "Resolving every required desktop model from pinned official releases"
& $VenvPython $HydrateScript `
    --catalog $SourceModelCatalog `
    --policy $BundlePolicy `
    --output $ModelCatalog
if ($LASTEXITCODE -ne 0) {
    throw "Failed to resolve the complete desktop model catalog."
}

$HydratedCatalog = Get-Content -LiteralPath $ModelCatalog -Raw | ConvertFrom-Json
$BundlePolicyMetadata = Get-Content -LiteralPath $BundlePolicy -Raw | ConvertFrom-Json
$RequiredCatalogIds = @($HydratedCatalog.desktop_bundle_required_ids)
$RequiredPolicyCount = @($BundlePolicyMetadata.required_models).Count
if ($RequiredCatalogIds.Count -ne $RequiredPolicyCount) {
    throw (
        "The hydrated catalog resolved $($RequiredCatalogIds.Count) required models, " +
        "but the desktop policy requires $RequiredPolicyCount."
    )
}

Write-ReefVisionStep "Auditing zero-input model delivery"
& $VenvPython $BundleScript --catalog $ModelCatalog --audit-only
if ($LASTEXITCODE -ne 0) {
    throw "The model catalog contains an available entry without a complete delivery path."
}

# Verified files already present in .desktop\bundled-models are reused, so only
# a changed catalog entry requires another network download on the build machine.
Write-ReefVisionStep "Staging verified pretrained catalog checkpoints"
& $VenvPython $BundleScript --catalog $ModelCatalog --output $BundledModels
if ($LASTEXITCODE -ne 0) {
    throw "Failed to stage the pretrained catalog checkpoints."
}
$BundledManifest = Join-Path $BundledModels "manifest.json"
if (-not (Test-Path $BundledManifest -PathType Leaf)) {
    throw "Model bundle staging did not produce its manifest: $BundledManifest"
}
$BundleMetadata = Get-Content -LiteralPath $BundledManifest -Raw | ConvertFrom-Json
if (-not $BundleMetadata.delivery_contract_complete) {
    throw "The desktop model bundle did not pass its zero-input delivery contract."
}
if ($BundleMetadata.asset_count -ne $BundleMetadata.managed_catalog_model_count) {
    throw "The desktop bundle omitted one or more available managed checkpoints."
}
$BundledCatalogIds = @(
    $BundleMetadata.assets.PSObject.Properties | ForEach-Object { $_.Name }
)
$MissingRequiredIds = @(
    $RequiredCatalogIds | Where-Object { $_ -notin $BundledCatalogIds }
)
if ($MissingRequiredIds.Count -gt 0) {
    throw (
        "The desktop bundle omitted required Ready models: " +
        ($MissingRequiredIds -join ", ")
    )
}
if ($BundleMetadata.asset_count -lt $RequiredPolicyCount) {
    throw (
        "The desktop installer contains $($BundleMetadata.asset_count) checkpoints, " +
        "but the Ready-model policy requires at least $RequiredPolicyCount."
    )
}
Write-Host (
    "Bundling $($BundleMetadata.asset_count) verified checkpoints " +
    "($([math]::Round($BundleMetadata.total_size_bytes / 1MB, 1)) MB) and " +
    "$($BundleMetadata.builtin_architecture_count) offline scratch architectures."
) -ForegroundColor Green

# build-desktop-backend.ps1 packages config\model_catalog.json. Replace it only
# for the duration of the build, then restore the source-controlled catalog byte-for-byte.
$OriginalCatalogBytes = [System.IO.File]::ReadAllBytes($SourceModelCatalog)
try {
    Copy-Item -LiteralPath $ModelCatalog -Destination $SourceModelCatalog -Force

    & (Join-Path $PSScriptRoot "build-desktop-backend.ps1") -TargetTriple $TargetTriple
    if ($LASTEXITCODE -ne 0) {
        throw "The packaged desktop backend build failed."
    }

    Write-ReefVisionStep "Building the Tauri MSI installer"
    Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @(
        "--prefix",
        "apps/web",
        "run",
        "desktop:build",
        "--",
        "--target",
        $TargetTriple
    ) -AdditionalPathEntries @(
        (Split-Path -Parent $RustTools.Cargo)
    )
}
finally {
    [System.IO.File]::WriteAllBytes($SourceModelCatalog, $OriginalCatalogBytes)
}

$InstallerDirectory = Join-Path $Root "apps\web\src-tauri\target\$TargetTriple\release\bundle\msi"
$StagedCatalog = Join-Path $Root "apps\web\src-tauri\binaries\reefvision-api\_internal\config\model_catalog.json"
if (-not (Test-Path $StagedCatalog -PathType Leaf)) {
    throw "Desktop packaging lost the required Model Hub catalog: $StagedCatalog"
}
$PackagedCatalog = Get-Content -LiteralPath $StagedCatalog -Raw | ConvertFrom-Json
$PackagedRequiredIds = @($PackagedCatalog.desktop_bundle_required_ids)
if (
    $PackagedRequiredIds.Count -ne $RequiredCatalogIds.Count -or
    @($RequiredCatalogIds | Where-Object { $_ -notin $PackagedRequiredIds }).Count -gt 0
) {
    throw "The packaged backend catalog lost one or more required Ready models."
}
$Installers = @(Get-ChildItem -LiteralPath $InstallerDirectory -Filter '*.msi' -File -ErrorAction SilentlyContinue)
if ($Installers.Count -eq 0) {
    throw "Tauri did not produce an MSI installer in $InstallerDirectory"
}
Write-Host "Desktop installer output: $InstallerDirectory" -ForegroundColor Green
