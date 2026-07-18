param(
    [switch]$RunAutomatedValidation
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

Write-Host "Phase 7 Active Learning acceptance" -ForegroundColor Cyan
Write-Host "Expected branch: feat/active-learning-phase7"

if ($RunAutomatedValidation) {
    & ".\.venv\Scripts\python.exe" -m ruff format --check apps\api
    & ".\.venv\Scripts\python.exe" -m ruff check apps\api
    & ".\.venv\Scripts\python.exe" -m mypy apps\api\reefvision
    & ".\.venv\Scripts\python.exe" -m pytest apps\api\reefvision\tests\test_active_learning_phase7.py -v
    Push-Location apps\web
    npm run test -- --run
    npm run build
    Pop-Location
}

Write-Host ""
Write-Host "Manual acceptance:" -ForegroundColor Yellow
Write-Host "[ ] Create a project with multiple images and model proposals."
Write-Host "[ ] Create Hybrid, Uncertainty, Rare class, and Quality rounds."
Write-Host "[ ] Confirm each round freezes a manifest and 64-character selection hash."
Write-Host "[ ] Create an equivalent round and confirm the historical round is reused."
Write-Host "[ ] Open the linked Review Queue and complete or skip selected items."
Write-Host "[ ] Confirm feedback progress updates without automatic annotation acceptance."
Write-Host "[ ] Confirm a round cannot close while selected items remain pending."
Write-Host "[ ] Close the round and confirm its final feedback summary persists after restart."
Write-Host "[ ] Confirm model-scoped rounds exclude images without proposals from that model."
Write-Host "[ ] Confirm dataset-version-scoped rounds retain the immutable version ID."
