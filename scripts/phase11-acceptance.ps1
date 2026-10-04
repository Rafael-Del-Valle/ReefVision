param(
    [switch]$RunFullSoftwareGate,
    [switch]$BuildMsi,
    [switch]$RequireCuda,
    [string]$ExpectedGpuSubstring = "",
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$Web = Join-Path $Repo "apps\web"
$Tauri = Join-Path $Web "src-tauri"
$ExpectedBranch = "feat/scientist-ready-phase11-packaging-hardware-20261004"

Set-Location $Repo

$Branch = (git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $Branch -ne $ExpectedBranch) {
    throw "Phase 11 acceptance must run on $ExpectedBranch (found: $Branch)"
}

$Head = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Could not determine source commit."
}
if (git status --porcelain) {
    git status --short
    throw "Phase 11 evidence must start from a clean committed source tree."
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "ReefVision virtual environment is missing: $Python"
}

$Stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$EvidenceRoot = Join-Path $Repo ".artifacts\phase11-$Stamp"
$HardwareReport = Join-Path $EvidenceRoot "hardware-profile.json"
$SummaryPath = Join-Path $EvidenceRoot "summary.json"
New-Item -ItemType Directory -Path $EvidenceRoot -Force | Out-Null

$Summary = [ordered]@{
    schema_version = "reefvision-phase11-acceptance-0001"
    started_at_utc = [DateTime]::UtcNow.ToString("o")
    completed_at_utc = $null
    branch = $Branch
    source_commit = $Head
    source_tree_clean_at_start = $true
    phase10d_visual_smoke_test = "DEFERRED_BY_USER"
    target_triple = $TargetTriple
    gates = [ordered]@{}
    installer = $null
    failure_reason = $null
}

function Save-Summary {
    $Summary | ConvertTo-Json -Depth 10 |
        Set-Content -LiteralPath $SummaryPath -Encoding UTF8
}

function Invoke-Phase11Gate {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    $Started = Get-Date
    Write-Host ""
    Write-Host "=== $Name ==="

    try {
        & $Action
        if ($LASTEXITCODE -ne 0) {
            throw "$Name failed with exit code $LASTEXITCODE."
        }

        $Summary.gates[$Name] = [ordered]@{
            status = "PASS"
            duration_seconds = [math]::Round(((Get-Date) - $Started).TotalSeconds, 3)
        }
        Save-Summary
    }
    catch {
        $Summary.gates[$Name] = [ordered]@{
            status = "FAIL"
            duration_seconds = [math]::Round(((Get-Date) - $Started).TotalSeconds, 3)
            detail = $_.Exception.Message
        }
        $Summary.failure_reason = "$Name`: $($_.Exception.Message)"
        $Summary.completed_at_utc = [DateTime]::UtcNow.ToString("o")
        Save-Summary
        throw
    }
}

Save-Summary

Write-Host ""
Write-Host "======================================================================"
Write-Host " REEFVISION SCIENTIST-READY PHASE 11"
Write-Host " PACKAGING + HARDWARE VALIDATION"
Write-Host "======================================================================"
Write-Host ""
Write-Host "Branch: $Branch"
Write-Host "Commit: $Head"
Write-Host "Evidence: $EvidenceRoot"

Invoke-Phase11Gate -Name "hardware_profile" -Action {
    $Arguments = @(
        (Join-Path $Repo "scripts\phase11-hardware-profile.py"),
        "--output",
        $HardwareReport
    )
    if ($RequireCuda) {
        $Arguments += "--require-cuda"
    }
    if ($ExpectedGpuSubstring) {
        $Arguments += @("--expected-gpu-substring", $ExpectedGpuSubstring)
    }
    & $Python @Arguments
}

Invoke-Phase11Gate -Name "desktop_backend_unit_tests" -Action {
    & $Python -m pytest apps/api/reefvision/tests/test_desktop.py apps/api/reefvision/tests/test_worker_resilience.py -q
}

Invoke-Phase11Gate -Name "frontend_desktop_recovery" -Action {
    Push-Location $Web
    try {
        npm test -- src/app/DesktopResumeRecovery.test.tsx
    }
    finally {
        Pop-Location
    }
}

Invoke-Phase11Gate -Name "rust_desktop_tests" -Action {
    Push-Location $Tauri
    try {
        cargo fmt --check
        if ($LASTEXITCODE -ne 0) { throw "cargo fmt --check failed." }
        cargo test
    }
    finally {
        Pop-Location
    }
}

if ($RunFullSoftwareGate) {
    Invoke-Phase11Gate -Name "backend_ruff" -Action {
        & $Python -m ruff check apps/api
    }

    Invoke-Phase11Gate -Name "backend_format" -Action {
        & $Python -m ruff format --check apps/api
    }

    Invoke-Phase11Gate -Name "backend_mypy" -Action {
        & $Python -m mypy apps/api/reefvision
    }

    Invoke-Phase11Gate -Name "backend_full_pytest" -Action {
        & $Python -m pytest apps/api/reefvision/tests -q
    }

    Invoke-Phase11Gate -Name "frontend_format" -Action {
        Push-Location $Web
        try { npm run format:check } finally { Pop-Location }
    }

    Invoke-Phase11Gate -Name "frontend_typecheck" -Action {
        Push-Location $Web
        try { npm run typecheck } finally { Pop-Location }
    }

    Invoke-Phase11Gate -Name "frontend_full_vitest" -Action {
        Push-Location $Web
        try { npm test } finally { Pop-Location }
    }

    Invoke-Phase11Gate -Name "frontend_build" -Action {
        Push-Location $Web
        try { npm run build } finally { Pop-Location }
    }
}

if ($BuildMsi) {
    Invoke-Phase11Gate -Name "msi_build_and_verification" -Action {
        $BuildDesktopScript = Join-Path $Repo "scripts\build-desktop.ps1"
        & powershell.exe `
            -NoLogo `
            -NoProfile `
            -ExecutionPolicy Bypass `
            -File $BuildDesktopScript `
            -TargetTriple $TargetTriple
        if ($LASTEXITCODE -ne 0) {
            throw "build-desktop.ps1 failed with exit code $LASTEXITCODE."
        }
    }

    $InstallerDirectory = Join-Path $Repo "apps\web\src-tauri\target\$TargetTriple\release\bundle\msi"
    $MsiFiles = @(Get-ChildItem -LiteralPath $InstallerDirectory -Filter "*.msi" -File)
    if ($MsiFiles.Count -ne 1) {
        throw "Expected exactly one MSI after Phase 11 build; found $($MsiFiles.Count)."
    }

    $ProvenancePath = Join-Path $InstallerDirectory "build-provenance.json"
    if (-not (Test-Path -LiteralPath $ProvenancePath -PathType Leaf)) {
        throw "MSI build did not emit build-provenance.json."
    }

    $BuildProvenance = Get-Content -LiteralPath $ProvenancePath -Raw | ConvertFrom-Json
    if ([string]$BuildProvenance.source_commit -ne $Head) {
        throw "Installer source commit does not match Phase 11 HEAD."
    }
    if (-not [bool]$BuildProvenance.source_tree_clean) {
        throw "Installer provenance says the source tree was dirty."
    }
    if (-not [bool]$BuildProvenance.msi_verified) {
        throw "Installer provenance says MSI verification was skipped."
    }

    $Msi = $MsiFiles[0]
    $Summary.installer = [ordered]@{
        path = $Msi.FullName
        size_bytes = $Msi.Length
        sha256 = (Get-FileHash -LiteralPath $Msi.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        build_provenance = $ProvenancePath
        msi_verified = $true
    }
    Save-Summary

    Invoke-Phase11Gate -Name "clean_install_plan_only" -Action {
        $PlanRoot = Join-Path $env:SystemDrive "reefvision-phase11-disposable-plan"
        & (Join-Path $Repo "scripts\acceptance-windows-clean-install.ps1") -InstallerPath $Msi.FullName -AcceptanceRoot $PlanRoot -PlanOnly
    }
}

if (git status --porcelain) {
    git status --short
    throw "Phase 11 validation changed tracked source files."
}

$Summary.completed_at_utc = [DateTime]::UtcNow.ToString("o")
Save-Summary

Write-Host ""
Write-Host "======================================================================"
Write-Host " PHASE 11 LOCAL ACCEPTANCE PASSED"
Write-Host "======================================================================"
Write-Host ""
Write-Host "Evidence summary:"
Write-Host "  $SummaryPath"
Write-Host "Hardware profile:"
Write-Host "  $HardwareReport"
if ($Summary.installer) {
    Write-Host "Installer:"
    Write-Host "  $($Summary.installer.path)"
    Write-Host "SHA-256:"
    Write-Host "  $($Summary.installer.sha256)"
}
Write-Host ""
Write-Host "Still separate from this local gate:"
Write-Host "  - Phase 10D visual smoke test (deferred)"
Write-Host "  - disposable clean install / upgrade / uninstall execution"
Write-Host "  - large-media stress evidence"
Write-Host "  - packaged CPU/CUDA provider inference matrix"
