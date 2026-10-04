param(
    [string]$AcceptanceRoot = "C:\reefvision-disposable-acceptance",
    [string]$InstallerDirectory = "",
    [string]$PreviousInstallerPath = "",
    [switch]$PreviousInstallerSupportsIsolatedAcceptance,
    [switch]$DisposableTest,
    [switch]$PlanOnly,
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ExpectedBranch = "feat/scientist-ready-phase11-packaging-hardware-20261004"
$CleanHarness = Join-Path $Repo "scripts\acceptance-windows-clean-install.ps1"

Set-Location $Repo

if ($DisposableTest -and $PlanOnly) {
    throw "-DisposableTest and -PlanOnly are mutually exclusive."
}
if (-not $DisposableTest -and -not $PlanOnly) {
    throw "Choose -PlanOnly on a normal machine or -DisposableTest on a disposable Windows VM/machine."
}

$Branch = (git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $Branch -ne $ExpectedBranch) {
    throw "Phase 11C must run on $ExpectedBranch (found: $Branch)"
}

$Head = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Could not determine Phase 11C source commit."
}

if (git status --porcelain) {
    git status --short
    throw "Phase 11C requires a clean source tree."
}

if (-not $InstallerDirectory) {
    $InstallerDirectory = Join-Path $Repo "apps\web\src-tauri\target\x86_64-pc-windows-msvc\release\bundle\msi"
}
$InstallerDirectory = [System.IO.Path]::GetFullPath($InstallerDirectory)
if (-not (Test-Path -LiteralPath $InstallerDirectory -PathType Container)) {
    throw "Installer directory is missing: $InstallerDirectory"
}

$MsiFiles = @(Get-ChildItem -LiteralPath $InstallerDirectory -Filter "*.msi" -File)
if ($MsiFiles.Count -ne 1) {
    throw "Expected exactly one MSI in $InstallerDirectory; found $($MsiFiles.Count)."
}
$Msi = $MsiFiles[0]

$BuildProvenancePath = Join-Path $InstallerDirectory "build-provenance.json"
if (-not (Test-Path -LiteralPath $BuildProvenancePath -PathType Leaf)) {
    throw "Missing installer build provenance: $BuildProvenancePath"
}
$BuildProvenance = Get-Content -LiteralPath $BuildProvenancePath -Raw | ConvertFrom-Json
if (-not [bool]$BuildProvenance.source_tree_clean) {
    throw "Installer provenance says its source tree was dirty."
}
if (-not [bool]$BuildProvenance.msi_verified) {
    throw "Installer provenance says MSI package verification was skipped."
}

$MsiHash = (Get-FileHash -LiteralPath $Msi.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
$MsiRecord = @($BuildProvenance.files | Where-Object { [string]$_.name -eq $Msi.Name })
if ($MsiRecord.Count -ne 1) {
    throw "Build provenance does not contain exactly one record for $($Msi.Name)."
}
if ([string]$MsiRecord[0].sha256 -ne $MsiHash) {
    throw "Current MSI checksum does not match build-provenance.json."
}

$InstallerCom = New-Object -ComObject WindowsInstaller.Installer
$Database = $InstallerCom.OpenDatabase($Msi.FullName, 0)
$MediaView = $Database.OpenView("SELECT ``Cabinet`` FROM ``Media`` ORDER BY ``DiskId``")
$MediaView.Execute()
$RequiredCabs = @()
while ($true) {
    $Record = $MediaView.Fetch()
    if ($null -eq $Record) { break }
    $Cabinet = [string]$Record.StringData(1)
    if (-not [string]::IsNullOrWhiteSpace($Cabinet) -and -not $Cabinet.StartsWith("#")) {
        $RequiredCabs += $Cabinet
    }
}
$MediaView.Close()
foreach ($Cabinet in $RequiredCabs) {
    $CabinetPath = Join-Path $InstallerDirectory $Cabinet
    if (-not (Test-Path -LiteralPath $CabinetPath -PathType Leaf)) {
        throw "MSI references missing cabinet: $CabinetPath"
    }
}

if ($PreviousInstallerPath) {
    $PreviousInstallerPath = (Resolve-Path -LiteralPath $PreviousInstallerPath).Path
    if (-not $PreviousInstallerSupportsIsolatedAcceptance) {
        throw "A previous MSI requires -PreviousInstallerSupportsIsolatedAcceptance."
    }
}

$ExistingReports = @(
    Get-ChildItem -LiteralPath (Join-Path $Repo ".artifacts") -Directory -Filter "windows-clean-acceptance-*" -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName
)

Write-Host ""
Write-Host "======================================================================"
Write-Host " REEFVISION SCIENTIST-READY PHASE 11C"
Write-Host " CLEAN WINDOWS INSTALL / RESTART / UNINSTALL"
Write-Host "======================================================================"
Write-Host ""
Write-Host "Harness commit: $Head"
Write-Host "Installer source commit: $($BuildProvenance.source_commit)"
Write-Host "Installer: $($Msi.FullName)"
Write-Host "Installer SHA-256: $MsiHash"
Write-Host "External cabinets: $($RequiredCabs.Count)"
Write-Host "Acceptance root: $AcceptanceRoot"
Write-Host "Mode: $(if ($PlanOnly) { "PLAN ONLY" } else { "DISPOSABLE TEST" })"
Write-Host ""

$Arguments = @(
    "-NoLogo",
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $CleanHarness,
    "-InstallerPath",
    $Msi.FullName,
    "-AcceptanceRoot",
    $AcceptanceRoot
)

if ($PlanOnly) {
    $Arguments += "-PlanOnly"
}
else {
    $Arguments += "-DisposableTest"
}
if ($KeepArtifacts) {
    $Arguments += "-KeepArtifacts"
}
if ($PreviousInstallerPath) {
    $Arguments += @(
        "-PreviousInstallerPath",
        $PreviousInstallerPath,
        "-PreviousInstallerSupportsIsolatedAcceptance"
    )
}

& powershell.exe @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "Windows clean-install acceptance failed with exit code $LASTEXITCODE."
}

$Reports = @(
    Get-ChildItem -LiteralPath (Join-Path $Repo ".artifacts") -Directory -Filter "windows-clean-acceptance-*" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending
)
$NewReportDirectory = $Reports | Where-Object { $_.FullName -notin $ExistingReports } | Select-Object -First 1
if ($null -eq $NewReportDirectory) {
    throw "Could not identify the new clean-install acceptance evidence directory."
}
$ReportPath = Join-Path $NewReportDirectory.FullName "report.json"
if (-not (Test-Path -LiteralPath $ReportPath -PathType Leaf)) {
    throw "Clean-install evidence report is missing: $ReportPath"
}
$Report = Get-Content -LiteralPath $ReportPath -Raw | ConvertFrom-Json

if ([bool]$Report.plan_only) {
    Write-Host ""
    Write-Host "Phase 11C PlanOnly validation passed." -ForegroundColor Yellow
    Write-Host "No MSI install, launch, restart, upgrade, or uninstall was performed."
    Write-Host "Evidence: $ReportPath"
    exit 0
}

$RequiredPass = @(
    "install",
    "shortcuts",
    "first_launch",
    "frontend_backend_connectivity",
    "project_persistence",
    "restart",
    "project_exchange",
    "uninstall",
    "data_retention"
)
foreach ($Name in $RequiredPass) {
    $Entry = $Report.$Name
    if ($null -eq $Entry -or [string]$Entry.status -ne "PASS") {
        throw "Phase 11C required evidence did not pass: $Name"
    }
}

if ($PreviousInstallerPath) {
    if ([string]$Report.upgrade.status -ne "PASS") {
        throw "A previous MSI was supplied but the upgrade gate did not pass."
    }
}
elseif ([string]$Report.upgrade.status -ne "SKIPPED") {
    throw "Upgrade should be explicitly SKIPPED when no previous safe MSI is supplied."
}

if (git status --porcelain) {
    git status --short
    throw "Phase 11C changed tracked source files."
}

Write-Host ""
Write-Host "======================================================================"
Write-Host " PHASE 11C PASSED"
Write-Host "======================================================================"
Write-Host ""
Write-Host "Evidence: $ReportPath"
Write-Host "Install: $($Report.install.status)"
Write-Host "Shortcuts: $($Report.shortcuts.status)"
Write-Host "First launch: $($Report.first_launch.status)"
Write-Host "Frontend/backend: $($Report.frontend_backend_connectivity.status)"
Write-Host "Project persistence: $($Report.project_persistence.status)"
Write-Host "Restart: $($Report.restart.status)"
Write-Host "Project Exchange: $($Report.project_exchange.status)"
Write-Host "Upgrade: $($Report.upgrade.status)"
Write-Host "Uninstall: $($Report.uninstall.status)"
Write-Host "Data retention: $($Report.data_retention.status)"
