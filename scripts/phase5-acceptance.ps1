param(
    [string]$ReportPath = ".desktop\acceptance\phase5-classification.md"
)

$ErrorActionPreference = "Stop"
$checks = @(
    "Open a project with at least two reviewed images and two active classes",
    "Assign exactly one image label in the same label set to each training image",
    "Create an immutable whole-image classification dataset",
    "Create a bounding-box crop classification dataset",
    "Create a mask-bound crop classification dataset",
    "Download one dataset archive and inspect train, val, test, and manifest contents",
    "Launch a one-epoch classification run using an installed Ultralytics classifier architecture",
    "Confirm top-1 and top-5 metrics appear in the completed job",
    "Confirm the best checkpoint is automatically registered as purpose classifier",
    "Run top-k inference on an image",
    "Accept one prediction and reject another",
    "Confirm the accepted prediction appears as a verified image label with model provenance",
    "Restart ReefVision and confirm image labels and reviewed predictions persist",
    "Run one detection and one segmentation job to check for regressions"
)

$directory = Split-Path -Parent $ReportPath
if ($directory) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

$lines = @(
    "# ReefVision Phase 5 Acceptance",
    "",
    "Branch: feat/classification-workflows-phase5",
    "Generated: $(Get-Date -Format o)",
    "",
    "Mark each item PASS, FAIL, or BLOCKED during the later validation session.",
    ""
)
foreach ($check in $checks) {
    $lines += "- [ ] **PENDING** — $check"
}
$lines += ""
$lines += "Phase 5 must remain unmerged until automated validation and every applicable item above passes."

Set-Content -Path $ReportPath -Value $lines -Encoding UTF8
Write-Host "Phase 5 acceptance checklist saved to $ReportPath"
