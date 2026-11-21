param(
    [string]$AcceptanceRoot = "C:\reefvision-disposable-acceptance",
    [string]$InstallerDirectory = "",
    [string]$PreviousInstallerPath = "",
    [switch]$PreviousInstallerSupportsIsolatedAcceptance,
    [switch]$DisposableTest,
    [switch]$PlanOnly,
    [switch]$KeepArtifacts,
    [switch]$TrackD16
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "lib\phase11c-track16.ps1")
$CleanHarness = Join-Path $Repo "scripts\acceptance-windows-clean-install.ps1"

Set-Location $Repo

if ($DisposableTest -and $PlanOnly) {
    throw "-DisposableTest and -PlanOnly are mutually exclusive."
}
if (-not $DisposableTest -and -not $PlanOnly) {
    throw "Choose -PlanOnly on a normal machine or -DisposableTest on a disposable Windows VM/machine."
}

$Branch = (git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Could not determine Phase 11C source branch."
}
[void](Assert-ReefVisionPhase11CBranch -ActualBranch $Branch -TrackD16:$TrackD16)

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
Assert-ReefVisionPhase11CBuildSource -HarnessHead $Head -InstallerSourceCommit ([string]$BuildProvenance.source_commit) -TrackD16:$TrackD16

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
$VersionView = $Database.OpenView("SELECT ``Value`` FROM ``Property`` WHERE ``Property`` = 'ProductVersion'")
$VersionView.Execute()
$VersionRecord = $VersionView.Fetch()
if ($null -eq $VersionRecord) {
    throw "The MSI has no ProductVersion property."
}
$MsiProductVersion = [string]$VersionRecord.StringData(1)
$VersionView.Close()
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

$CurrentReports = @(
    Get-ChildItem -LiteralPath (Join-Path $Repo ".artifacts") -Directory -Filter "windows-clean-acceptance-*" -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName
)
$NewReportDirectory = Assert-ReefVisionPhase11CUniqueNewReport -PriorDirectories $ExistingReports -CurrentDirectories $CurrentReports
$ReportPath = Join-Path $NewReportDirectory "report.json"
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

if ($TrackD16) {
    # Require the already-existing independent installed-science report verifier.
    # It checks 1.6 class visibility, QC review, persisted/replayed typed QC graphs,
    # timestamps, migration identity, offline model policy, and MSI digest.
    $verifier = Join-Path $Repo "scripts\validate_windows_acceptance_report.py"
    $python = Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $python) {
        throw "Track D 1.6 installed acceptance requires an existing Python interpreter for offline evidence verification."
    }
    $expectedUpgrade = if ($PreviousInstallerPath) { "passed" } else { "skipped" }
    & $python.Source $verifier --report $ReportPath --expected-version $MsiProductVersion --expected-upgrade $expectedUpgrade --installer $Msi.FullName
    if ($LASTEXITCODE -ne 0) {
        throw "Track D 1.6 installed class visibility, QC, and saved Workflow Builder evidence failed independent validation."
    }
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
