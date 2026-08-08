param(
    [string]$ReportPath = ".desktop\acceptance\phase6-video-tracking.md"
)

$ErrorActionPreference = "Stop"
$checks = @(
    "Import a real MP4, MOV, AVI, MKV, M4V, or WebM video into a project",
    "Confirm width, height, frame count, frame rate, and duration are correct",
    "Play the managed original video in the Video Tracking workspace",
    "Extract review frames at a stride greater than one",
    "Open several extracted frames by source frame number",
    "Create a manual fish track with at least three keyframes",
    "Verify linear interpolation aligns with intermediate fish positions",
    "Change the interpolation mode to hold and verify the expected behavior",
    "Edit the track class and keyframe boxes and confirm its revision increases",
    "Confirm path length, displacement, duration, mean speed, maximum speed, footprint, and occupancy summaries",
    "Launch detector plus ByteTrack using a registered detector",
    "Confirm unmapped detector labels are reported rather than assigned",
    "Review a machine-generated track and mark it verified",
    "Delete one track and confirm it disappears without removing the video",
    "Restart ReefVision and confirm videos, extraction state, tracks, provenance, and revisions persist",
    "Run detection, segmentation, semantic segmentation, classification, and coral measurement regression checks"
)

$directory = Split-Path -Parent $ReportPath
if ($directory) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

$lines = @(
    "# ReefVision Phase 6 Acceptance",
    "",
    "Branch: feat/video-fish-tracking-phase6",
    "Generated: $(Get-Date -Format o)",
    "",
    "Mark each item PASS, FAIL, or BLOCKED during the later validation session.",
    ""
)
foreach ($check in $checks) {
    $lines += "- [ ] **PENDING** — $check"
}
$lines += ""
$lines += "Phase 6 must remain unmerged until automated validation and every applicable item above passes."

Set-Content -Path $ReportPath -Value $lines -Encoding UTF8
Write-Host "Phase 6 acceptance checklist saved to $ReportPath"
