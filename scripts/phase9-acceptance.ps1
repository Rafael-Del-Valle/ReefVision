param(
    [switch]$RunAutomatedValidation
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

Write-Host "Phase 9 Project Interoperability acceptance" -ForegroundColor Cyan
Write-Host "Expected branch: feat/project-interoperability-phase9"

if ($RunAutomatedValidation) {
    & ".\.venv\Scripts\python.exe" -m ruff format --check apps\api
    & ".\.venv\Scripts\python.exe" -m ruff check apps\api
    & ".\.venv\Scripts\python.exe" -m mypy apps\api\reefvision
    & ".\.venv\Scripts\python.exe" -m pytest apps\api\reefvision\tests\test_project_exchange_phase9.py -v
    Push-Location apps\web
    npm run test -- --run
    npm run build
    Pop-Location
}

Write-Host ""
Write-Host "Manual acceptance:" -ForegroundColor Yellow
Write-Host "[ ] Create a metadata-only exchange and inspect it."
Write-Host "[ ] Confirm inspection warns that original media must be relinked."
Write-Host "[ ] Create an exchange with images and videos included."
Write-Host "[ ] Confirm section counts and checksums are present in the manifest."
Write-Host "[ ] Download the completed .reefvision.zip archive."
Write-Host "[ ] Inspect the downloaded archive and confirm it is compatible."
Write-Host "[ ] Confirm model weights are excluded unless explicitly selected."
Write-Host "[ ] Confirm unsafe ZIP paths and checksum changes are rejected."
Write-Host "[ ] Confirm the UI has no enabled Import action."
Write-Host "[ ] Restart ReefVision and confirm exchange history persists."
