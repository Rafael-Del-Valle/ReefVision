param(
    [switch]$RunAutomatedValidation
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

Write-Host "Phase 8 Advanced Providers acceptance" -ForegroundColor Cyan
Write-Host "Expected branch: feat/advanced-providers-phase8"

if ($RunAutomatedValidation) {
    & ".\.venv\Scripts\python.exe" -m ruff format --check apps\api
    & ".\.venv\Scripts\python.exe" -m ruff check apps\api
    & ".\.venv\Scripts\python.exe" -m mypy apps\api\reefvision
    & ".\.venv\Scripts\python.exe" -m pytest apps\api\reefvision\tests\test_advanced_providers_phase8.py apps\api\reefvision\tests\test_pose_active_learning_phase8.py -v
    Push-Location apps\web
    npm run test -- --run
    npm run build
    Pop-Location
}

Write-Host ""
Write-Host "Manual acceptance:" -ForegroundColor Yellow
Write-Host "[ ] Inspect every Provider Lab manifest."
Write-Host "[ ] Confirm original SAM is the only advanced provider currently marked executable."
Write-Host "[ ] Confirm Grounding DINO, OWLv2, Florence-2, SAM 2, MobileSAM, FastSAM, and Depth Anything V2 are blocked."
Write-Host "[ ] Confirm missing prompt fields appear as explicit blockers."
Write-Host "[ ] Confirm a checkpoint registered to another provider is rejected."
Write-Host "[ ] Confirm Depth Anything V2 is described as relative depth only."
Write-Host "[ ] Confirm blocked providers have no launch action."
Write-Host "[ ] Confirm output contracts map to existing proposal, mask, video, text, or array review paths."

Write-Host "[ ] Create a pose Active Learning frame acquisition round."
Write-Host "[ ] Create a pose Active Learning clip acquisition round."
Write-Host "[ ] Confirm score components include landmark, visibility, association, repeated-landmark, identity-break, and motion signals."
Write-Host "[ ] Confirm acquisition reasons and provenance SHA are visible."
Write-Host "[ ] Open a candidate directly in the Pose Annotation Editor."
Write-Host "[ ] Correct a repeated landmark and save the pose."
Write-Host "[ ] Confirm the candidate becomes verified only after scientist save/review."
Write-Host "[ ] Confirm an append-only pose correction audit event records Active Learning verification."
Write-Host "[ ] Confirm stale candidates are blocked before review."
Write-Host "[ ] Confirm the retraining provenance manifest contains verified pose SHA and track revision."
