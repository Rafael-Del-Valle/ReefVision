param(
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$ExpectedBranch = "feat/scientist-ready-phase11-packaging-hardware-20261004"

Set-Location $Repo

$Branch = (git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $Branch -ne $ExpectedBranch) {
    throw "Phase 11B acceptance must run on $ExpectedBranch (found: $Branch)"
}

$Head = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Could not determine Phase 11B source commit."
}

if (git status --porcelain) {
    git status --short
    throw "Phase 11B must start from a clean committed source tree."
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "ReefVision Python environment is missing: $Python"
}

if (-not $OutputRoot) {
    $Stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    $OutputRoot = Join-Path $Repo ".artifacts\phase11b-$Stamp"
}
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)

$ArtifactsRoot = [System.IO.Path]::GetFullPath((Join-Path $Repo ".artifacts"))
if (-not $OutputRoot.StartsWith($ArtifactsRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Phase 11B output must remain below the repository .artifacts directory."
}
if (Test-Path -LiteralPath $OutputRoot) {
    throw "Phase 11B output already exists: $OutputRoot"
}

Write-Host ""
Write-Host "======================================================================"
Write-Host " REEFVISION SCIENTIST-READY PHASE 11B"
Write-Host " OFFLINE + PERSISTENCE + LARGE-MEDIA STRESS"
Write-Host "======================================================================"
Write-Host ""
Write-Host "Branch: $Branch"
Write-Host "Commit: $Head"
Write-Host "Evidence: $OutputRoot"
Write-Host ""
Write-Host "Synthetic stress inputs:"
Write-Host "  - 6000 x 4000 uncompressed TIFF"
Write-Host "  - 2560 x 1440, 30 fps, 12 second H.264 video"
Write-Host ""
Write-Host "Network policy:"
Write-Host "  - non-loopback Python socket access is blocked"
Write-Host "  - Hugging Face / Transformers offline mode enabled"
Write-Host ""

Write-Host "=== HARNESS CONTRACT TESTS ==="
& $Python -m pytest apps/api/reefvision/tests/test_phase11b_stress_harness.py -q
if ($LASTEXITCODE -ne 0) {
    throw "Phase 11B harness contract tests failed."
}

Write-Host ""
Write-Host "=== ISOLATED STRESS / RESTART RUN ==="
& $Python (Join-Path $Repo "scripts\phase11b-stress.py") --output $OutputRoot
if ($LASTEXITCODE -ne 0) {
    throw "Phase 11B stress harness failed."
}

$ReportPath = Join-Path $OutputRoot "report.json"
if (-not (Test-Path -LiteralPath $ReportPath -PathType Leaf)) {
    throw "Phase 11B did not produce report.json."
}

$Report = Get-Content -LiteralPath $ReportPath -Raw | ConvertFrom-Json
if ([string]$Report.status -ne "PASS") {
    throw "Phase 11B report did not record PASS."
}
if ([string]$Report.source_commit -ne $Head) {
    throw "Phase 11B evidence source commit does not match current HEAD."
}

$RequiredChecks = @(
    "large_image",
    "large_video",
    "restart_persistence",
    "results_package",
    "project_exchange",
    "offline_local_workflow"
)
foreach ($Check in $RequiredChecks) {
    $Entry = $Report.checks.$Check
    if ($null -eq $Entry -or [string]$Entry.status -ne "PASS") {
        throw "Phase 11B required check failed or is missing: $Check"
    }
}

if ([int64]$Report.synthetic_media.image.size_bytes -lt 50000000) {
    throw "Phase 11B large-image fixture was unexpectedly small."
}
if ([int]$Report.synthetic_media.video.width_px -lt 2560 -or [int]$Report.synthetic_media.video.height_px -lt 1440) {
    throw "Phase 11B video fixture did not meet the intended stress resolution."
}
if ([int]$Report.checks.offline_local_workflow.non_loopback_socket_attempts -ne 0) {
    throw "Phase 11B detected external network access during local workflows."
}

git diff --check
if ($LASTEXITCODE -ne 0) {
    throw "git diff --check failed after Phase 11B."
}

if (git status --porcelain) {
    git status --short
    throw "Phase 11B changed tracked source files."
}

Write-Host ""
Write-Host "======================================================================"
Write-Host " PHASE 11B PASSED"
Write-Host "======================================================================"
Write-Host ""
Write-Host "Evidence:"
Write-Host "  $ReportPath"
Write-Host ""
Write-Host "Large image:"
Write-Host "  $($Report.synthetic_media.image.width_px) x $($Report.synthetic_media.image.height_px)"
Write-Host "  $([math]::Round([int64]$Report.synthetic_media.image.size_bytes / 1MB, 2)) MiB"
Write-Host ""
Write-Host "Large video:"
Write-Host "  $($Report.synthetic_media.video.width_px) x $($Report.synthetic_media.video.height_px)"
Write-Host "  expected frames: $($Report.synthetic_media.video.expected_frames)"
Write-Host "  $([math]::Round([int64]$Report.synthetic_media.video.size_bytes / 1MB, 2)) MiB"
Write-Host ""
Write-Host "Confirmed:"
Write-Host "  - managed media checksums preserved"
Write-Host "  - large-image thumbnail path works"
Write-Host "  - image annotation survives restart"
Write-Host "  - video metadata/source survives restart"
Write-Host "  - registered model identity/file survives restart"
Write-Host "  - interrupted background job is recovered"
Write-Host "  - Results Package verifies before and after restart"
Write-Host "  - Project Exchange verifies after restart"
Write-Host "  - local workflow completes with zero non-loopback socket attempts"
Write-Host ""
Write-Host "NEXT:"
Write-Host "  Phase 11C — disposable Windows clean install / restart / uninstall"
Write-Host "  Upgrade remains conditional on a safe previous isolated-acceptance MSI."
