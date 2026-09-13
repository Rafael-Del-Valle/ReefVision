param(
    [ValidateSet("x86_64-pc-windows-msvc", "i686-pc-windows-msvc", "aarch64-pc-windows-msvc")]
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [string]$CargoTargetDirectory = '',
    [switch]$SkipMsiVerification
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$BuildCommit = (git rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or (git status --porcelain)) {
    throw 'Production installers must be built from a clean committed source tree.'
}

if (-not $CargoTargetDirectory) {
    $CargoTargetDirectory = Join-Path $Root 'apps\web\src-tauri\target'
}
$CargoTargetDirectory = [System.IO.Path]::GetFullPath($CargoTargetDirectory)
if (-not $CargoTargetDirectory.StartsWith($Root + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'The cargo build directory must be inside this repository.'
}
$env:CARGO_TARGET_DIR = $CargoTargetDirectory

. (Join-Path $PSScriptRoot "lib\node-tools.ps1")
$NodeTools = Ensure-ReefVisionNodeTools
$RustTools = Ensure-ReefVisionRustTools -Purpose "build the ReefVision desktop installer" -TargetTriple $TargetTriple
Assert-ReefVisionPublicLockfile -NodeTools $NodeTools

function Build-ReefVisionSplitCabinetMsi {
    param([Parameter(Mandatory = $true)][string]$TargetTriple)

    $ReleaseRoot = Join-Path $CargoTargetDirectory "$TargetTriple\release"
    $WixRoot = Join-Path $ReleaseRoot "wix\x64"
    $WixSource = Join-Path $WixRoot "main.wxs"
    $WixObject = Join-Path $WixRoot "main.wixobj"
    $Locale = Join-Path $WixRoot "locale.wxl"
    $InstallerDirectory = Join-Path $ReleaseRoot "bundle\msi"
    $Installer = Join-Path $InstallerDirectory "ReefVision_$($TauriConfig.version)_x64_en-US.msi"
    $WixTools = Join-Path $env:LOCALAPPDATA "tauri\WixTools314"
    $Candle = Join-Path $WixTools "candle.exe"
    $Light = Join-Path $WixTools "light.exe"

    foreach ($requiredPath in @($WixSource, $Locale, $Candle, $Light)) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            throw "Split-cabinet MSI fallback requires: $requiredPath"
        }
    }

    $Source = Get-Content -LiteralPath $WixSource -Raw
    $EmbeddedMedia = '<Media Id="1" Cabinet="app.cab" EmbedCab="yes" />'
    $SplitMedia = '<MediaTemplate CabinetTemplate="rv{0}.cab" EmbedCab="no" MaximumUncompressedMediaSize="700" />'
    if (-not $Source.Contains($EmbeddedMedia)) {
        throw "Generated WiX source does not contain the expected single embedded cabinet definition."
    }
    Set-Content -LiteralPath $WixSource -Value $Source.Replace($EmbeddedMedia, $SplitMedia) -Encoding UTF8

    New-Item -ItemType Directory -Path $InstallerDirectory -Force | Out-Null
    Get-ChildItem -LiteralPath $InstallerDirectory -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @('.msi', '.cab', '.wixpdb') } |
        Remove-Item -Force

    Write-Host "Rebuilding WiX source with split external cabinets..."
    & $Candle -nologo -arch x64 $WixSource "-dSourceDir=$(Join-Path $ReleaseRoot 'ReefVision.exe')" -out $WixObject
    if ($LASTEXITCODE -ne 0) {
        throw "WiX candle.exe failed with exit code $LASTEXITCODE."
    }

    Write-Host "Linking split-cabinet ReefVision MSI..."
    & $Light -nologo -ext WixUIExtension -ext WixUtilExtension -cultures:en-us -loc $Locale -out $Installer $WixObject
    if ($LASTEXITCODE -ne 0) {
        throw "WiX light.exe failed with exit code $LASTEXITCODE."
    }

    if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
        throw "Split-cabinet WiX build did not produce the expected MSI: $Installer"
    }
    Write-Host "Split-cabinet MSI: $Installer" -ForegroundColor Green
}

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
$BundleScript = Join-Path $PSScriptRoot "stage-bundled-models.py"
$ModelCatalog = Join-Path $Root "config\model_catalog.json"
$BundledModels = Join-Path $Root ".desktop\bundled-models"

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
if ($BundleMetadata.asset_count -le 0) {
    throw "The desktop installer model bundle contains no checkpoints."
}
Write-Host "Bundling $($BundleMetadata.asset_count) verified checkpoints ($([math]::Round($BundleMetadata.total_size_bytes / 1MB, 1)) MB)." -ForegroundColor Green

& (Join-Path $PSScriptRoot "build-desktop-backend.ps1") -TargetTriple $TargetTriple

Write-ReefVisionStep "Building the Tauri MSI installer"
$GeneratedWixDirectory = Join-Path $CargoTargetDirectory "$TargetTriple\release\wix\x64"
$InstallerDirectory = Join-Path $CargoTargetDirectory "$TargetTriple\release\bundle\msi"
foreach ($generatedPath in @(
    (Join-Path $GeneratedWixDirectory "main.wxs"),
    (Join-Path $GeneratedWixDirectory "main.wixobj")
)) {
    Remove-Item -LiteralPath $generatedPath -Force -ErrorAction SilentlyContinue
}
if (Test-Path -LiteralPath $InstallerDirectory -PathType Container) {
    Get-ChildItem -LiteralPath $InstallerDirectory -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @('.msi', '.cab', '.wixpdb') } |
        Remove-Item -Force
}
try {
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
catch {
    if ($TargetTriple -ne "x86_64-pc-windows-msvc") {
        throw
    }
    Write-Warning "Tauri's single embedded cabinet could not hold the release payload; retrying with split external cabinets."
    Build-ReefVisionSplitCabinetMsi -TargetTriple $TargetTriple
}

$StagedCatalog = Join-Path $Root "apps\web\src-tauri\binaries\reefvision-api\_internal\config\model_catalog.json"
if (-not (Test-Path $StagedCatalog -PathType Leaf)) {
    throw "Desktop packaging lost the required Model Hub catalog: $StagedCatalog"
}
$Installers = @(Get-ChildItem -LiteralPath $InstallerDirectory -Filter '*.msi' -File -ErrorAction SilentlyContinue)
if ($Installers.Count -eq 0) {
    throw "Tauri did not produce an MSI installer in $InstallerDirectory"
}
Write-Host "Desktop installer output: $InstallerDirectory" -ForegroundColor Green

if (-not $SkipMsiVerification) {
    Write-ReefVisionStep "Verifying the Windows MSI and packaged backend"
    & (Join-Path $PSScriptRoot "verify-windows-msi.ps1") `
        -TargetTriple $TargetTriple `
        -InstallerDirectory $InstallerDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "Windows MSI verification failed with exit code $LASTEXITCODE."
    }
}
else {
    Write-Warning "MSI verification was explicitly skipped. This build is not release-validated."
}

if ((git rev-parse HEAD) -ne $BuildCommit -or (git status --porcelain)) {
    throw 'Source tree changed while packaging; do not release these artifacts.'
}
$BuildArtifactRecords = @(Get-ChildItem -LiteralPath $InstallerDirectory -File |
    Where-Object { $_.Extension -in @('.msi', '.cab') } | ForEach-Object {
        [ordered]@{ name = $_.Name; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    })
[ordered]@{
    version = $TauriConfig.version
    source_commit = $BuildCommit
    source_tree_clean = $true
    msi_verified = (-not [bool]$SkipMsiVerification)
    files = $BuildArtifactRecords
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $InstallerDirectory 'build-provenance.json') -Encoding UTF8
