param(
    [switch]$RunAutomatedValidation
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

Write-Host "Phase 10 Workflow Graph Foundation acceptance" -ForegroundColor Cyan
Write-Host "Expected branch: feat/workflow-graph-foundation-phase10"

if ($RunAutomatedValidation) {
    & ".\.venv\Scripts\python.exe" -m ruff format --check apps\api
    & ".\.venv\Scripts\python.exe" -m ruff check apps\api
    & ".\.venv\Scripts\python.exe" -m mypy apps\api\reefvision
    & ".\.venv\Scripts\python.exe" -m pytest apps\api\reefvision\tests\test_workflow_graphs_phase10.py -v
    Push-Location apps\web
    npm run test -- --run
    npm run build
    Pop-Location
}

Write-Host ""
Write-Host "Manual acceptance:" -ForegroundColor Yellow
Write-Host "[ ] Inspect every node definition and confirm its ports match an existing ReefVision operation."
Write-Host "[ ] Validate the example segmentation-review-measurement graph after inserting a real segmenter model ID."
Write-Host "[ ] Confirm incompatible ports are rejected."
Write-Host "[ ] Confirm missing required parameters and connections are rejected."
Write-Host "[ ] Confirm a classifier cannot be connected to Detection Inference."
Write-Host "[ ] Confirm dataset, model, and video references must belong to the current project."
Write-Host "[ ] Confirm review gates appear as explicit pause steps."
Write-Host "[ ] Confirm the dry-run plan is topologically ordered."
Write-Host "[ ] Confirm every plan reports executable=false."
Write-Host "[ ] Confirm there is no enabled Run graph action and no visual node editor."
