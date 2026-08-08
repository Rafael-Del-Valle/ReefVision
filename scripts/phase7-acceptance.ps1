param(
    [switch]$RunAutomatedValidation,
    [string]$ReportPath = ".desktop\acceptance\phase7-active-learning.md"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

Write-Host "Phase 7 Active Learning acceptance" -ForegroundColor Cyan
Write-Host "Expected hardening branch: agent/m7-acceptance-hardening"

if ($RunAutomatedValidation) {
    & ".\.venv\Scripts\python.exe" -m ruff format --check apps\api
    & ".\.venv\Scripts\python.exe" -m ruff check apps\api
    & ".\.venv\Scripts\python.exe" -m mypy apps\api\reefvision
    & ".\.venv\Scripts\python.exe" -m pytest apps\api\reefvision\tests\test_active_learning_phase7.py -v
    Push-Location apps\web
    npx prettier --check src\features\active-learning\ActiveLearningWorkspace.tsx src\features\active-learning\ActiveLearningWorkspace.test.tsx src\features\active-learning\activeLearningApi.ts
    npm run typecheck
    npm run test -- src\features\active-learning\ActiveLearningWorkspace.test.tsx
    Pop-Location
}

$checks = @(
    "Create a representative coral project with reviewed annotations, unlabeled candidates, and model predictions",
    "Train or register a model from a known immutable dataset version and run inference on candidate images",
    "Create an Uncertainty round and confirm lower-confidence or disagreement-heavy images rank ahead of confident images",
    "Create a Hybrid round and confirm mixed uncertainty, rarity, quality, and review-state signals are represented",
    "Create a Rare class round on an intentionally imbalanced coral dataset and confirm underrepresented-class candidates are promoted",
    "Create a Quality round with seeded QC issues/provenance problems and confirm those risks are promoted",
    "Confirm every selected image shows a human-readable why-selected explanation and numeric score",
    "Scope a round to a specific input dataset version and confirm the immutable version ID is retained",
    "Scope a round to one or more registered models and confirm candidates without those model signals are excluded",
    "Create an equivalent round and confirm the frozen historical selection is reused rather than silently regenerated",
    "Open the linked Review Queue and inspect selected images in the annotation workspace",
    "Edit or accept annotations as appropriate and explicitly mark reviewed images Reviewed",
    "Complete or skip every selected review item and confirm progress reaches 100 percent terminal",
    "Confirm a queue item marked complete but not scientifically Reviewed blocks round completion with a clear recovery message",
    "Complete the round and confirm a new immutable feedback dataset version is created from reviewed images",
    "Confirm the feedback dataset keeps verified boxes and verified polygon/raster masks with immutable checksums/provenance",
    "Confirm a parent input dataset reuses existing split assignments while newly reviewed images receive deterministic splits",
    "Use the feedback dataset in a subsequent training/export workflow and confirm the reviewed sample is present",
    "Run a later inference/acquisition cycle and confirm the workflow can continue without mutating the earlier round manifest",
    "Restart ReefVision and confirm round status, explanations, review progress, feedback dataset ID, and manifest checksum persist",
    "Run the Active Learning workspace in the packaged Windows desktop build",
    "Record selection-efficiency results against a random-review baseline on a real coral dataset"
)

$directory = Split-Path -Parent $ReportPath
if ($directory) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

$lines = @(
    "# ReefVision Phase 7 Acceptance",
    "",
    "Branch: agent/m7-acceptance-hardening",
    "Generated: $(Get-Date -Format o)",
    "",
    "Automated gates verify software behavior. Real coral-data selection quality and packaged-Windows acceptance remain separate release requirements.",
    ""
)
foreach ($check in $checks) {
    $lines += "- [ ] **PENDING** — $check"
}
$lines += ""
$lines += "Phase 7 must remain unmerged until M6 is promoted, GitHub-hosted gates execute successfully, and applicable real-data/desktop checks pass."
Set-Content -Path $ReportPath -Value $lines -Encoding UTF8

Write-Host "Phase 7 acceptance checklist saved to $ReportPath"
