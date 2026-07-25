param(
    [ValidateSet("x86_64-pc-windows-msvc", "i686-pc-windows-msvc", "aarch64-pc-windows-msvc")]
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Architecture = switch ($TargetTriple) {
    "x86_64-pc-windows-msvc" { "x64" }
    "i686-pc-windows-msvc" { "x86" }
    "aarch64-pc-windows-msvc" { "arm64" }
    default { throw "Unsupported target triple: $TargetTriple" }
}

$TauriRoot = Join-Path $Root "apps\web\src-tauri"
$ReleaseRoot = Join-Path $TauriRoot "target\$TargetTriple\release"
$WixWorkingDirectory = Join-Path $ReleaseRoot "wix\$Architecture"
$InstallerDirectory = Join-Path $ReleaseRoot "bundle\msi"
$TauriConfigPath = Join-Path $TauriRoot "tauri.conf.json"
$VerificationScript = Join-Path $PSScriptRoot "verify-windows-msi.ps1"
$WixToolsDirectory = Join-Path $env:LOCALAPPDATA "tauri\WixTools314"
$LightPath = Join-Path $WixToolsDirectory "light.exe"
$WixUtilExtension = Join-Path $WixToolsDirectory "WixUtilExtension.dll"
$WixUiExtension = Join-Path $WixToolsDirectory "WixUIExtension.dll"
$LocalePath = Join-Path $WixWorkingDirectory "locale.wxl"

foreach ($RequiredPath in @(
    $WixWorkingDirectory,
    $TauriConfigPath,
    $VerificationScript,
    $LightPath,
    $WixUtilExtension,
    $WixUiExtension,
    $LocalePath
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required WiX recovery input is missing: $RequiredPath"
    }
}

$WixObjects = @(
    Get-ChildItem -LiteralPath $WixWorkingDirectory -Filter "*.wixobj" -File |
        Sort-Object -Property Name
)
if ($WixObjects.Count -eq 0) {
    throw "No generated WiX object files were found in $WixWorkingDirectory"
}

$TauriConfig = Get-Content -LiteralPath $TauriConfigPath -Raw | ConvertFrom-Json
$SafeProductName = [regex]::Replace([string]$TauriConfig.productName, "[^A-Za-z0-9._-]+", "")
if (-not $SafeProductName) {
    throw "The Tauri product name cannot be converted to a safe MSI filename."
}
$Version = [string]$TauriConfig.version
$InstallerName = "{0}_{1}_{2}_en-US.msi" -f $SafeProductName, $Version, $Architecture
$RelinkedOutput = Join-Path $WixWorkingDirectory "reefvision-relinked.msi"
$FinalInstaller = Join-Path $InstallerDirectory $InstallerName

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$ArtifactDirectory = Join-Path $Root ".artifacts\wix-relink-$Timestamp"
$LightLog = Join-Path $ArtifactDirectory "light-sval.log"
$VerificationDirectory = Join-Path $ArtifactDirectory "msi-extraction"
New-Item -ItemType Directory -Path $ArtifactDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $InstallerDirectory -Force | Out-Null
Remove-Item -LiteralPath $RelinkedOutput -Force -ErrorAction SilentlyContinue

$PreviousWixMums = $env:WIX_MUMS
$PreviousWixMcslfs = $env:WIX_MCSLFS
$PreviousErrorActionPreference = $ErrorActionPreference
$ExitCode = 1
try {
    # Keep every cabinet well below WiX's 2 GB cabinet ceiling and allow an
    # individual large model file to be split across multiple cabinets.
    $env:WIX_MUMS = "512"
    $env:WIX_MCSLFS = "512"

    $Arguments = @(
        "-v",
        "-sval",
        "-ext", $WixUtilExtension,
        "-ext", $WixUiExtension,
        "-o", $RelinkedOutput,
        "-cultures:en-us",
        "-loc", $LocalePath
    ) + @($WixObjects | ForEach-Object { $_.FullName })

    Write-Host "Relinking the already-generated WiX objects without MSI ICE validation..." -ForegroundColor Cyan
    Write-Host "Verbose linker log: $LightLog" -ForegroundColor DarkGray
    Push-Location $WixWorkingDirectory
    try {
        # Windows PowerShell promotes native stderr to ErrorRecord instances.
        # WiX writes normal progress and warnings there, so only its exit code
        # determines success and every line is retained in the artifact log.
        $ErrorActionPreference = "Continue"
        & $LightPath @Arguments 2>&1 |
            Tee-Object -FilePath $LightLog |
            ForEach-Object { Write-Host ([string]$_) }
        $ExitCode = if ($null -eq $LASTEXITCODE) { 1 } else { $LASTEXITCODE }
    }
    finally {
        Pop-Location
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
}
finally {
    $env:WIX_MUMS = $PreviousWixMums
    $env:WIX_MCSLFS = $PreviousWixMcslfs
    $ErrorActionPreference = $PreviousErrorActionPreference
}

if ($ExitCode -ne 0 -or -not (Test-Path -LiteralPath $RelinkedOutput -PathType Leaf)) {
    throw "WiX relinking failed with exit code $ExitCode. Inspect $LightLog for the exact LGHT error."
}

Copy-Item -LiteralPath $RelinkedOutput -Destination $FinalInstaller -Force
Write-Host "Relinked MSI: $FinalInstaller" -ForegroundColor Green

& $VerificationScript -MsiPath $FinalInstaller -OutputDirectory $VerificationDirectory
if (-not $?) {
    throw "The relinked MSI failed ReefVision payload verification."
}

Write-Host "MSI relink and extracted-payload verification passed." -ForegroundColor Green
Write-Host "Installer: $FinalInstaller" -ForegroundColor Green
Write-Host "Evidence: $ArtifactDirectory" -ForegroundColor Green
