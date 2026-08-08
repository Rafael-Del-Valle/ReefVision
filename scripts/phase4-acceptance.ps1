[CmdletBinding()]
param([string]$ReportPath = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Read-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Instructions
    )

    Write-Host "`n--- $Name ---" -ForegroundColor Yellow
    foreach ($instruction in $Instructions) {
        Write-Host "  $instruction"
    }
    do {
        $answer = (Read-Host "Result [PASS/FAIL/BLOCKED]").Trim().ToUpperInvariant()
    } while ($answer -notin @("PASS", "FAIL", "BLOCKED"))
    return [pscustomobject]@{
        Name = $Name
        Result = $answer
        Notes = (Read-Host "Notes (optional)").Trim()
    }
}

$branch = (git branch --show-current).Trim()
if ($branch -ne "feat/coral-measurements-phase4") {
    throw "Run this checklist from feat/coral-measurements-phase4."
}
if (git status --porcelain) {
    throw "Commit or preserve local changes before acceptance."
}

$head = (git rev-parse HEAD).Trim()
$shortHead = (git rev-parse --short HEAD).Trim()
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
if (-not $ReportPath) {
    $directory = Join-Path $Root ".desktop\acceptance"
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $ReportPath = Join-Path $directory "phase4-$timestamp-$shortHead.md"
}

Write-Host "Phase 4 manual acceptance for commit $shortHead" -ForegroundColor Cyan
Write-Host "Run automated validation and open the tested ReefVision build before answering."
Read-Host "Press Enter when ready" | Out-Null

$results = [System.Collections.Generic.List[object]]::new()
$results.Add((Read-Check "Pixel measurement regression" @(
    "Verify area, perimeter, centroid, bounds, contained boxes, and pixel density for polygon and raster masks.",
    "Edit and save a mask and confirm measurements refresh."
)))
$results.Add((Read-Check "Image calibration" @(
    "Save distance per pixel, unit, and optional default depth.",
    "Confirm physical area, perimeter, and density appear and persist after restart.",
    "Clear calibration and confirm pixel measurements remain."
)))
$results.Add((Read-Check "Centerline and TLE" @(
    "Add, drag, remove, clear, cancel, and save centerline points.",
    "Confirm source-image alignment and total linear extension in pixels and physical units.",
    "Reopen the image and confirm persistence."
)))
$results.Add((Read-Check "Surface-area models" @(
    "Test no estimate, closed planar extrusion, and equivalent centerline cylinder.",
    "Confirm missing inputs produce an unavailable estimate rather than a fabricated value.",
    "Confirm displayed assumptions identify depth or diameter behavior."
)))
$results.Add((Read-Check "Density filters" @(
    "Filter contained boxes by class, scientific name, and state.",
    "Clear filters and confirm the original count returns."
)))
$results.Add((Read-Check "Measurement exports" @(
    "Confirm CSV contains one row per verified mask and all measurement columns.",
    "Confirm the NumPy ZIP contains measurements.npy, columns.json, and rows.json.",
    "Load the NPY file and compare its row count with rows.json."
)))
$results.Add((Read-Check "Revision and regression" @(
    "Confirm stale measurement-profile updates are rejected and audit history is written.",
    "Confirm boxes, polygon masks, raster masks, inference review, and dataset exports still work."
)))

$incomplete = @($results | Where-Object { $_.Result -ne "PASS" })
$overall = if ($incomplete.Count -eq 0) { "PASS" } else { "INCOMPLETE" }
$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("# ReefVision Phase 4 Acceptance Report")
$lines.Add("")
$lines.Add("- Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')")
$lines.Add("- Branch: $branch")
$lines.Add("- Commit: $head")
$lines.Add("- Overall: **$overall**")
$lines.Add("")
$lines.Add("| Check | Result | Notes |")
$lines.Add("|---|---|---|")
foreach ($result in $results) {
    $notes = $result.Notes.Replace("|", "\|")
    $lines.Add("| $($result.Name) | **$($result.Result)** | $notes |")
}
Set-Content -Path $ReportPath -Value $lines -Encoding UTF8
Write-Host "`nReport: $ReportPath" -ForegroundColor Green
Write-Host "Overall: $overall"
if ($overall -ne "PASS") { exit 1 }
