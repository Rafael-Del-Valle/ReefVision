param(
    [switch]$RunAutomatedValidation
)

$ErrorActionPreference = "Stop"

$Repo = Split-Path $PSScriptRoot -Parent
$ExpectedBranch = "feat/scientist-ready-phase10-workflow-integration-20261004"
$Python = Join-Path $Repo ".venv\Scripts\python.exe"

Set-Location $Repo

$CurrentBranch = (git branch --show-current).Trim()

if ($CurrentBranch -ne $ExpectedBranch) {
    throw "Phase 10 acceptance must run on $ExpectedBranch"
}

if (-not (Test-Path $Python)) {
    throw "ReefVision virtual environment not found."
}

Write-Host "Phase 10 workflow integration acceptance"
Write-Host "Expected branch: $ExpectedBranch"

& $Python -m ruff format --check `
    apps/api/reefvision/schemas/workflow_graphs.py `
    apps/api/reefvision/services/workflow_graphs.py `
    apps/api/reefvision/services/workflow_node_registry_v1.py `
    apps/api/reefvision/tests/test_workflow_pose_phase10.py

if ($LASTEXITCODE -ne 0) {
    throw "Phase 10 formatting check failed."
}

& $Python -m ruff check apps/api

if ($LASTEXITCODE -ne 0) {
    throw "Phase 10 Ruff validation failed."
}

& $Python -m mypy apps/api/reefvision

if ($LASTEXITCODE -ne 0) {
    throw "Phase 10 mypy validation failed."
}

& $Python -m pytest `
    apps/api/reefvision/tests/test_workflow_pose_phase10.py `
    apps/api/reefvision/tests/test_workflow_pose_runtime_phase10.py `
    apps/api/reefvision/tests/test_workflow_pose_review_resume_phase10.py `
    apps/api/reefvision/tests/test_workflow_results_package_phase10.py `
    apps/api/reefvision/tests/test_workflow_pose_training_phase10.py `
    apps/api/reefvision/tests/test_workflow_pose_registration_phase10.py `
    apps/api/reefvision/tests/test_workflow_phase10c_closeout.py `
    apps/api/reefvision/tests/test_workflow_review_phase10.py `
    apps/api/reefvision/tests/test_workflow_graphs_phase10.py `
    -q

if ($LASTEXITCODE -ne 0) {
    throw "Phase 10 focused workflow tests failed."
}

Write-Host ""
Write-Host "Phase 10A-3 scientist review checks:"
Write-Host "[ ] Pose Review pauses instead of silently promoting machine pose state."
Write-Host "[ ] Unreviewed unresolved identities block Pose Review approval."
Write-Host "[ ] Tracker identity breaks require explicit scientist verification."
Write-Host "[ ] Resume preserves succeeded upstream node artifacts without rerunning pose inference."
Write-Host "[ ] Active Learning Review requires a retraining-ready canonical round."
Write-Host "[ ] Only verified Active Learning truth reaches dataset freeze/export."
Write-Host ""
Write-Host "Phase 10B-1 Results Package workflow integration validated."

Write-Host "Phase 10B-2A Ultralytics pose retraining validated."

Write-Host "Phase 10B-2B trained pose registration validated."


Write-Host "Phase 10C resumability/provenance closeout validated."
Write-Host ""
Write-Host "Phase 10 final automated acceptance:"
Write-Host "[x] Succeeded nodes survive restart without recomputation."
Write-Host "[x] Persisted artifacts are checksum-verified before reuse."
Write-Host "[x] Pose inference retry reuses completed child science."
Write-Host "[x] Pose training retry reuses completed child science."
Write-Host "[x] Scientist review gates remain explicit truth boundaries."
Write-Host "[x] Verified pose truth freezes immutably before retraining."
Write-Host "[x] Trained pose models reuse the exact frozen schema revision."
Write-Host "[x] Results Packages verify after pose retraining."
Write-Host "[x] Terminal workflow provenance is canonical and inspectable."
Write-Host "[x] Saved scientist graph remains inspectable after reopen."
