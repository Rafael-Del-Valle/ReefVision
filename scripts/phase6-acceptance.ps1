param(
    [string]$ReportPath = ".desktop\acceptance\phase6-video-tracking.md"
)

$ErrorActionPreference = "Stop"
$checks = @(
    "Import a real MP4, MOV, AVI, MKV, M4V, or WebM fish video into a project",
    "Confirm width, height, frame count, frame rate, duration, SHA-256, and duplicate handling are correct",
    "Play the managed original video in the packaged Video Tracking workspace",
    "Extract review frames at a stride greater than one and confirm the extraction job completes",
    "Open several extracted frames by source frame number and confirm skipped stride frames are rejected",
    "Create a manual fish track with at least three keyframes",
    "Verify linear interpolation aligns with intermediate fish positions",
    "Change the interpolation mode to hold and verify the expected behavior",
    "Edit the track class and keyframe boxes and confirm its revision increases",
    "Save a physical distance-per-pixel calibration and confirm it persists after restart",
    "Confirm path length, displacement, duration, mean speed, maximum speed, footprint, and occupancy summaries",
    "Confirm calibrated physical distance and speed match a manually checked trajectory",
    "Confirm active and inactive time match a manually checked speed threshold",
    "Define a rectangular zone and confirm zone occupancy time against manually counted frames",
    "Confirm heatmap observation totals equal the number of interpolated track observations",
    "For a multi-fish clip, confirm nearest-neighbor distance and school-spread calculations against manually checked frames",
    "Launch detector plus ByteTrack using a registered detector and review generated identities",
    "Launch the same detector plus BoT-SORT and review generated identities",
    "Confirm generated-track provenance records tracker, detector/model checksum, source-video checksum, thresholds, provider, and confidence",
    "Confirm unmapped detector labels are reported rather than silently assigned",
    "Review a machine-generated track, correct it if necessary, and mark it verified",
    "Export CSV and confirm frame/time/track/box coordinates round-trip into a spreadsheet or parser",
    "Export MOTChallenge text and confirm frame numbering, identities, boxes, and confidence round-trip into a MOT parser",
    "Export ReefVision JSON and confirm video metadata, track metadata, provenance, and interpolated frames are preserved",
    "Delete one track and confirm it disappears without removing the video",
    "Restart ReefVision and confirm videos, calibration, extraction state, tracks, provenance, revisions, and exports persist",
    "Run detection, segmentation, semantic segmentation, classification, and coral measurement regression checks",
    "Install the Windows MSI on a clean or isolated Windows environment and repeat import/playback/extraction/tracking/export smoke tests",
    "Compare ByteTrack and BoT-SORT trajectories with manually annotated fish tracks and record localization/identity-switch accuracy"
)

$directory = Split-Path -Parent $ReportPath
if ($directory) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

$lines = @(
    "# ReefVision Phase 6 Acceptance",
    "",
    "Branch: agent/m6-acceptance-hardening",
    "Generated: $(Get-Date -Format o)",
    "",
    "Mark each item PASS, FAIL, or BLOCKED during validation. Automated CI passing is necessary but does not replace the real-video and packaged-Windows checks below.",
    ""
)
foreach ($check in $checks) {
    $lines += "- [ ] **PENDING** — $check"
}
$lines += ""
$lines += "Phase 6 must remain unmerged until automated validation and every applicable release item above passes. Scientific tracking-accuracy results should be recorded separately from software smoke-test results."

Set-Content -Path $ReportPath -Value $lines -Encoding UTF8
Write-Host "Phase 6 acceptance checklist saved to $ReportPath"
