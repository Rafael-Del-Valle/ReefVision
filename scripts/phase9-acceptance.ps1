param(
    [switch]$RunAutomatedValidation
)

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"

Set-Location $repo

function Require-Success([string]$Message) {
    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

Write-Host "Phase 9 pose training + project interoperability acceptance" -ForegroundColor Cyan
Write-Host "Expected branch: feat/scientist-ready-phase9-pose-training-datasets-20261003"

if ($RunAutomatedValidation) {
    & $python -m ruff format --check apps\api
    Require-Success "Phase 9 Ruff formatting failed."

    & $python -m ruff check apps\api
    Require-Success "Phase 9 Ruff lint failed."

    & $python -m mypy apps\api\reefvision
    Require-Success "Phase 9 mypy failed."

    & $python -m pytest `
        apps\api\reefvision\tests\test_pose_training_datasets_phase9.py `
        apps\api\reefvision\tests\test_pose_training_exports_phase9.py `
        apps\api\reefvision\tests\test_pose_active_learning_phase8.py `
        apps\api\reefvision\tests\test_pose_interoperability.py `
        apps\api\reefvision\tests\test_project_exchange_phase9.py `
        apps\api\reefvision\tests\test_mask_migration_lineage.py `
        apps\api\reefvision\tests\test_desktop_runtime_paths.py `
        -v

    Require-Success "Phase 9A/9B backend acceptance failed."

    Push-Location apps\web
    try {
        npm run test -- --run src/features/video/PoseActiveLearningPanel.test.tsx
        Require-Success "Phase 9A/9B frontend test failed."

        npm run typecheck
        Require-Success "Phase 9A frontend typecheck failed."

        npm run build
        Require-Success "Phase 9A frontend build failed."
    }
    finally {
        Pop-Location
    }
}

Write-Host ""
Write-Host "Phase 9A manual checks:" -ForegroundColor Yellow
Write-Host "[ ] Verify only scientist-verified candidates enter a frozen dataset."
Write-Host "[ ] Verify skipped/pending candidates never enter training truth."
Write-Host "[ ] Verify a pose changed after verification is blocked before materialization."
Write-Host "[ ] Verify live-track edits after freezing do not mutate the dataset."
Write-Host "[ ] Verify schema revision/content hash are visible in dataset provenance."
Write-Host "[ ] Verify model provider/version/checkpoint SHA are retained where a source model exists."
Write-Host "[ ] Verify the native ZIP is deterministic for an unchanged frozen dataset."
Write-Host "[ ] Verify Pose Active Learning UI can freeze a completed round."

Write-Host ""
Write-Host "Phase 9B manual checks:" -ForegroundColor Yellow
Write-Host "[ ] Confirm source-video SHA mismatch blocks every external export."
Write-Host "[ ] Confirm selected frames match their exact original zero-based frame indices."
Write-Host "[ ] Confirm exported PNG SHA-256 values match the files inside each bundle."
Write-Host "[ ] Confirm repeated landmark names remain recoverable through node_mapping."
Write-Host "[ ] Confirm COCO export opens with its bundled frame paths."
Write-Host "[ ] Confirm Ultralytics Pose export has images/train, labels/train, and data.yaml."
Write-Host "[ ] Confirm DeepLabCut export does not silently flatten multi-instance frames."
Write-Host "[ ] Confirm SLEAP and NWB exports fail clearly when the optional runtime is missing."
Write-Host "[ ] Confirm native-format losses are explicitly documented in the bundle manifest."
