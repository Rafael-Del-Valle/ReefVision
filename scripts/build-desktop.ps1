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

if (-not (Test-Path ".venv" -PathType Container)) {
    throw "Run .\scripts\bootstrap.ps1 first."
}

& (Join-Path $PSScriptRoot "build-desktop-backend.ps1") -TargetTriple $TargetTriple

Write-ReefVisionStep "Building the Tauri NSIS installer"
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

$InstallerDirectory = Join-Path $Root "apps\web\src-tauri\target\$TargetTriple\release\bundle\nsis"
$StagedCatalog = Join-Path $Root "apps\web\src-tauri\binaries\reefvision-api\_internal\config\model_catalog.json"
if (-not (Test-Path $StagedCatalog -PathType Leaf)) {
    throw "Desktop packaging lost the required Model Hub catalog: $StagedCatalog"
}
$Installers = @(Get-ChildItem -LiteralPath $InstallerDirectory -Filter '*.exe' -File -ErrorAction SilentlyContinue)
if ($Installers.Count -eq 0) {
    throw "Tauri did not produce an NSIS installer in $InstallerDirectory"
}
Write-Host "Desktop installer output: $InstallerDirectory" -ForegroundColor Green
