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
    & ".\.venv\Scripts\python.exe" -m pytest apps\api\reefvision\tests\test_advanced_providers_phase8.py -v
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
