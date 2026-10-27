param(
    [ValidateSet("x86_64-pc-windows-msvc", "i686-pc-windows-msvc", "aarch64-pc-windows-msvc")]
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [string]$CargoTargetDirectory = '',
    [switch]$SkipMsiVerification
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Test-ReefVisionSourceTreeClean {
    git diff --quiet --ignore-submodules --
    if ($LASTEXITCODE -ne 0) { return $false }

    git diff --cached --quiet --ignore-submodules --
    if ($LASTEXITCODE -ne 0) { return $false }

    $Untracked = @(git ls-files --others --exclude-standard)
    if ($LASTEXITCODE -ne 0 -or $Untracked.Count -gt 0) { return $false }

    return $true
}

$BuildCommit = (git rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or -not (Test-ReefVisionSourceTreeClean)) {
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
if ($TauriConfig.bundle.resources.'../../../.desktop/release-1.0.3/backend/' -ne 'backend/') {
    throw "Tauri must map the complete weight-free release backend directory to backend/."
}
if ($TauriConfig.bundle.resources.'../../../.desktop/release-1.0.3/bundled-models/' -ne 'bundled-models/') {
    throw "Tauri must package the weight-free manifest as bundled-models/."
}

if (-not (Test-Path ".venv" -PathType Container)) {
    throw "Run .\scripts\bootstrap.ps1 first."
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$BundleScript = Join-Path $PSScriptRoot "stage-bundled-models.py"
$ModelCatalog = Join-Path $Root "config\model_catalog.json"
$BundledModels = Join-Path $Root ".desktop\release-1.0.3\bundled-models"

$ModelAuditScript = Join-Path $PSScriptRoot "audit-model-downloadability.py"

Write-ReefVisionStep "Checking ReefVision 1.0.3 public versions"
& $VenvPython (Join-Path $PSScriptRoot "check-release-version.py")
if ($LASTEXITCODE -ne 0) { throw "Release version consistency check failed." }

Write-ReefVisionStep "Auditing the architecture-first model catalog"
& $VenvPython $ModelAuditScript --catalog $ModelCatalog
if ($LASTEXITCODE -ne 0) { throw "No-pretrained model policy audit failed." }

# Use a separate release staging tree. Legacy bundles and researcher caches are preserved.
Write-ReefVisionStep "Staging the weight-free model manifest"
& $VenvPython $BundleScript --catalog $ModelCatalog --output $BundledModels
if ($LASTEXITCODE -ne 0) { throw "Failed to stage the weight-free manifest." }
& $VenvPython $ModelAuditScript --catalog $ModelCatalog --bundle-root $BundledModels
if ($LASTEXITCODE -ne 0) { throw "Staged model resource audit failed." }

& (Join-Path $PSScriptRoot "build-desktop-backend.ps1") -TargetTriple $TargetTriple

$ReleaseBackend = Join-Path $Root ".desktop\release-1.0.3\backend"
& $VenvPython $ModelAuditScript --catalog $ModelCatalog --bundle-root $BundledModels --runtime-root $ReleaseBackend
if ($LASTEXITCODE -ne 0) { throw "Release backend contains prohibited model assets." }

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
    if ($TargetTriple -ne "x86_64-pc-windows-msvc" -or
        -not (Test-Path -LiteralPath (Join-Path $GeneratedWixDirectory "main.wxs") -PathType Leaf)) {
        # A missing WiX source means Tauri failed BEFORE MSI linking.
        # Retain that actual failure rather than inventing a cabinet-overflow diagnosis.
        throw
    }
    Write-Warning "Tauri MSI creation failed after generating WiX source; attempting split external cabinets."
    Build-ReefVisionSplitCabinetMsi -TargetTriple $TargetTriple
}

# WiX emits external cabinets in the generated wix directory. Windows
# Installer requires every non-embedded cabinet referenced by the MSI Media
# table to be distributed beside the MSI.
$GeneratedCabFiles = @(
    Get-ChildItem `
        -LiteralPath $GeneratedWixDirectory `
        -Filter '*.cab' `
        -File `
        -ErrorAction SilentlyContinue
)

foreach ($GeneratedCab in $GeneratedCabFiles) {
    $DestinationCab = Join-Path $InstallerDirectory $GeneratedCab.Name

    if (Test-Path -LiteralPath $DestinationCab -PathType Leaf) {
        $SourceHash = (
            Get-FileHash `
                -LiteralPath $GeneratedCab.FullName `
                -Algorithm SHA256
        ).Hash

        $DestinationHash = (
            Get-FileHash `
                -LiteralPath $DestinationCab `
                -Algorithm SHA256
        ).Hash

        if ($SourceHash -ne $DestinationHash) {
            throw "Generated CAB conflicts with MSI output: $($GeneratedCab.Name)"
        }

        Remove-Item `
            -LiteralPath $GeneratedCab.FullName `
            -Force
    }
    else {
        Move-Item `
            -LiteralPath $GeneratedCab.FullName `
            -Destination $DestinationCab
    }

    Write-Host "External cabinet output: $DestinationCab" -ForegroundColor Green
}

$StagedCatalog = Join-Path $Root ".desktop\release-1.0.3\backend\reefvision-api\_internal\config\model_catalog.json"
if (-not (Test-Path $StagedCatalog -PathType Leaf)) {
    throw "Desktop packaging lost the required Model Hub catalog: $StagedCatalog"
}
$Installers = @(Get-ChildItem -LiteralPath $InstallerDirectory -Filter '*.msi' -File -ErrorAction SilentlyContinue)
if ($Installers.Count -eq 0) {
    throw "Tauri did not produce an MSI installer in $InstallerDirectory"
}
Write-Host "Desktop installer output: $InstallerDirectory" -ForegroundColor Green

if ($Installers.Count -ne 1) {
    throw "Expected exactly one MSI in $InstallerDirectory but found $($Installers.Count)."
}

$InstallerCom = New-Object -ComObject WindowsInstaller.Installer
$MsiDatabase = $InstallerCom.OpenDatabase($Installers[0].FullName, 0)
$MediaView = $MsiDatabase.OpenView(
    "SELECT ``DiskId``, ``Cabinet`` FROM ``Media`` ORDER BY ``DiskId``"
)
$MediaView.Execute()

$MissingExternalCabinets = @()

while ($true) {
    $MediaRecord = $MediaView.Fetch()

    if ($null -eq $MediaRecord) {
        break
    }

    $Cabinet = [string]$MediaRecord.StringData(2)

    if (
        [string]::IsNullOrWhiteSpace($Cabinet) -or
        $Cabinet.StartsWith("#")
    ) {
        continue
    }

    $ExpectedCabinet = Join-Path $InstallerDirectory $Cabinet

    if (-not (Test-Path -LiteralPath $ExpectedCabinet -PathType Leaf)) {
        $MissingExternalCabinets += $Cabinet
    }
}

$MediaView.Close()

if ($MissingExternalCabinets.Count -gt 0) {
    throw (
        "MSI references missing external cabinets: " +
        ($MissingExternalCabinets -join ", ")
    )
}

Write-Host "MSI external cabinet dependency check passed." -ForegroundColor Green

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

if ((git rev-parse HEAD) -ne $BuildCommit -or -not (Test-ReefVisionSourceTreeClean)) {
    throw 'Source tree changed while packaging; do not release these artifacts.'
}
# Hash installer payloads with the framework SHA256 implementation.
# Some Windows PowerShell build agents do not expose Get-FileHash inside
# the pipeline scriptblock at this stage of the packaging process.
function Get-ReefVisionArtifactSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $Stream = [System.IO.File]::OpenRead($Path)
    try {
        $Sha256 = [System.Security.Cryptography.SHA256]::Create()
        try {
            return ([System.BitConverter]::ToString($Sha256.ComputeHash($Stream))).Replace('-', '').ToLowerInvariant()
        }
        finally {
            $Sha256.Dispose()
        }
    }
    finally {
        $Stream.Dispose()
    }
}
$BuildArtifactRecords = @(
    Get-ChildItem -LiteralPath $InstallerDirectory -File |
        Where-Object { $_.Extension -in @('.msi', '.cab') } |
        ForEach-Object {
            [ordered]@{
                name = $_.Name
                sha256 = Get-ReefVisionArtifactSha256 -Path $_.FullName
            }
        }
)
[ordered]@{
    version = $TauriConfig.version
    source_commit = $BuildCommit
    source_tree_clean = $true
    msi_verified = (-not [bool]$SkipMsiVerification)
    files = $BuildArtifactRecords
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $InstallerDirectory 'build-provenance.json') -Encoding UTF8
