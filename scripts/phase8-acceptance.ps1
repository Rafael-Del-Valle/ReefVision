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

Write-Host "Phase 8 Advanced Providers + Pose Active Learning acceptance" -ForegroundColor Cyan
Write-Host "Expected branch: feat/scientist-ready-phase8-pose-active-learning-20261003"

if ($RunAutomatedValidation) {
    Write-Host ""
    Write-Host "Automated validation:" -ForegroundColor Cyan

    & $python -m ruff format --check apps\api
    Require-Success "Phase 8 Ruff formatting failed."

    & $python -m ruff check apps\api
    Require-Success "Phase 8 Ruff lint failed."

    & $python -m mypy apps\api\reefvision
    Require-Success "Phase 8 mypy failed."

    & $python -m pytest `
        apps\api\reefvision\tests\test_advanced_providers_phase8.py `
        apps\api\reefvision\tests\test_advanced_provider_execution_schema.py `
        apps\api\reefvision\tests\test_advanced_provider_proposals.py `
        apps\api\reefvision\tests\test_advanced_provider_surfaces_phase8.py `
        apps\api\reefvision\tests\test_pose_provider_backends.py `
        apps\api\reefvision\tests\test_pose_uncertainty_contract_phase8.py `
        apps\api\reefvision\tests\test_pose_active_learning_phase8.py `
        -v

    Require-Success "Phase 8 focused backend acceptance failed."

    Push-Location apps\web
    try {
        npm run test -- --run
        Require-Success "Phase 8 frontend acceptance failed."

        npm run typecheck
        Require-Success "Phase 8 frontend typecheck failed."

        npm run build
        Require-Success "Phase 8 frontend build failed."
    }
    finally {
        Pop-Location
    }

    Write-Host ""
    Write-Host "Automated Phase 8 acceptance: PASS" -ForegroundColor Green
}

Write-Host ""
Write-Host "Manual / final-release acceptance:" -ForegroundColor Yellow
Write-Host "[ ] Confirm Segment Anything launches through Smart Mask / Annotation Editor, not Provider Lab."
Write-Host "[ ] Confirm Grounding DINO is identified as Provider Lab executable."
Write-Host "[ ] Confirm SAM 2 image assist is identified as Provider Lab executable."
Write-Host "[ ] Confirm SmolVLM is identified as Provider Lab executable."
Write-Host "[ ] Confirm nnU-Net is Provider Lab executable only when its external runtime is configured."
Write-Host "[ ] Confirm OWLv2, Florence-2, MobileSAM, FastSAM, and Depth Anything V2 remain blocked."
Write-Host "[ ] Confirm SAM 2 long-video propagation is not presented as implemented."
Write-Host "[ ] Confirm missing prompt fields appear as explicit blockers."
Write-Host "[ ] Confirm mismatched registered provider checkpoints are rejected."
Write-Host "[ ] Confirm Depth Anything V2 remains explicitly relative depth only."
Write-Host "[ ] Confirm blocked/existing-workflow providers have no Provider Lab launch action."
Write-Host "[ ] Confirm Grounding DINO and SAM 2 outputs remain review proposals, never automatic truth."
Write-Host "[ ] Confirm Ultralytics and SLEAP-NN do not claim heatmap/PAF evidence they do not expose."
Write-Host "[ ] Confirm native heatmap/PAF evidence enters scoring only when actually supplied."
Write-Host "[ ] Confirm cross-model disagreement retains comparison model/track provenance."
Write-Host "[ ] Confirm uncertainty-only pose acquisition."
Write-Host "[ ] Confirm uncertainty + diversity pose acquisition."
Write-Host "[ ] Confirm repeated landmarks remain order-independent during diversity scoring."
Write-Host "[ ] Open a selected candidate directly in Pose Annotation Editor."
Write-Host "[ ] Correct a repeated landmark and save the reviewed pose."
Write-Host "[ ] Confirm scientist save creates verified canonical pose provenance."
Write-Host "[ ] Confirm stale candidates are blocked."
Write-Host "[ ] Confirm the Phase 9 retraining manifest contains verified pose SHA and track revision."
Write-Host "[ ] Complete clean-machine packaged-provider validation with the final release candidate."
