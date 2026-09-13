[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [switch]$NoLaunch,
    [string]$ReportPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Step {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Read-AcceptanceResult {
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

    $notes = (Read-Host "Notes (optional)").Trim()
    return [pscustomobject]@{
        Name = $Name
        Result = $answer
        Notes = $notes
    }
}

$dirty = git status --porcelain
if ($dirty) {
    $dirty
    throw "The repository has uncommitted changes. Preserve or discard them before Phase 2 acceptance."
}

$branch = (git branch --show-current).Trim()
if ($branch -ne "feat/editable-mask-annotations") {
    throw "Expected branch feat/editable-mask-annotations but found $branch."
}

$head = (git rev-parse HEAD).Trim()
$shortHead = (git rev-parse --short HEAD).Trim()
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

if (-not $ReportPath) {
    $reportDirectory = Join-Path $Root ".desktop\acceptance"
    New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
    $ReportPath = Join-Path $reportDirectory "phase2-$timestamp-$shortHead.md"
}

if (-not $SkipBuild) {
    Write-Step "Running the full current-head validation and MSI build"
    & (Join-Path $PSScriptRoot "validate-pr.ps1") -BuildDesktopInstaller
    if ($LASTEXITCODE -ne 0) {
        throw "Full validation or MSI creation failed. Phase 2 acceptance cannot continue."
    }
}

$releaseExecutable = Join-Path $Root "apps\web\src-tauri\target\x86_64-pc-windows-msvc\release\reefvision-desktop.exe"
$ReleaseVersion = (Get-Content -LiteralPath (Join-Path $Root "apps\web\src-tauri\tauri.conf.json") -Raw | ConvertFrom-Json).version
$installer = Join-Path $Root "apps\web\src-tauri\target\x86_64-pc-windows-msvc\release\bundle\msi\ReefVision_${ReleaseVersion}_x64_en-US.msi"

if (-not (Test-Path $releaseExecutable -PathType Leaf)) {
    throw "Packaged ReefVision executable was not found: $releaseExecutable"
}
if (-not (Test-Path $installer -PathType Leaf)) {
    throw "ReefVision MSI was not found: $installer"
}

$results = [System.Collections.Generic.List[object]]::new()

if (-not $NoLaunch) {
    Write-Step "Launching the packaged ReefVision executable"
    Get-Process "reefvision-desktop" -ErrorAction SilentlyContinue |
        Stop-Process -Force
    Start-Process -FilePath $releaseExecutable | Out-Null
}

$results.Add((Read-AcceptanceResult -Name "Polygon node edit persistence" -Instructions @(
    "Open a persisted polygon in Polygon mode.",
    "Move one node, insert one node on an edge, and delete that inserted node.",
    "Wait for Saved, switch annotation types, return to Polygons, and confirm the edited geometry remains."
)))

$results.Add((Read-AcceptanceResult -Name "Three-node minimum" -Instructions @(
    "Select a triangle with exactly three nodes.",
    "Choose Delete node and click each node once.",
    "Confirm no node is removed and the triangle remains valid."
)))

$results.Add((Read-AcceptanceResult -Name "Keyboard deletion protection" -Instructions @(
    "Select a polygon while Move nodes is active.",
    "Press Delete and Backspace.",
    "Confirm the polygon remains and no server deletion is queued."
)))

$results.Add((Read-AcceptanceResult -Name "Explicit whole-polygon deletion" -Instructions @(
    "Create or select a disposable polygon.",
    "Click Delete selected masks.",
    "Wait for Saved and confirm only the selected polygon is removed."
)))

$results.Add((Read-AcceptanceResult -Name "Invalid polygon geometry" -Instructions @(
    "Attempt a self-intersecting polygon edit and confirm a visible save error without data loss.",
    "Attempt duplicate vertices and confirm rejection.",
    "Attempt an out-of-bounds edit and confirm rejection.",
    "Return the polygon to valid geometry and confirm autosave recovers."
)))

$results.Add((Read-AcceptanceResult -Name "Autosave and conflict messaging" -Instructions @(
    "Make a polygon node edit and a raster edit and confirm the UI progresses through Unsaved changes/Saving/Saved.",
    "Confirm any stale-revision save displays Revision conflict rather than silently overwriting data.",
    "Confirm local geometry remains available after a failed save."
)))

$results.Add((Read-AcceptanceResult -Name "Annotation type filtering" -Instructions @(
    "Select Bounding boxes and confirm only box annotations are shown.",
    "Select Polygons and confirm only polygon annotations are shown; raster masks must not appear.",
    "Select Raster masks and confirm only raster-mask annotations are shown.",
    "Switch among all three types and confirm filtering never deletes or modifies saved annotations."
)))

$results.Add((Read-AcceptanceResult -Name "Raster layer behavior" -Instructions @(
    "Open an image with one raster mask and paint without clicking Create another mask.",
    "Confirm the existing raster instance is revised and the mask count does not increase.",
    "Erase part of the mask and confirm it persists.",
    "Click Create another mask, paint once, and confirm the mask count increases only then."
)))

if (-not $NoLaunch) {
    Write-Step "Restarting ReefVision for persistence verification"
    Get-Process "reefvision-desktop" -ErrorAction SilentlyContinue |
        Stop-Process -Force
    Start-Sleep -Milliseconds 500
    Start-Process -FilePath $releaseExecutable | Out-Null
}

$results.Add((Read-AcceptanceResult -Name "Complete restart persistence" -Instructions @(
    "Reopen the same project and image after the forced application restart.",
    "Confirm moved/inserted/deleted polygon nodes remain correct.",
    "Confirm raster paint, erase, instance count, and latest revisions remain correct.",
    "Confirm annotation-type filtering did not alter stored annotations."
)))

$failed = @($results | Where-Object { $_.Result -eq "FAIL" })
$blocked = @($results | Where-Object { $_.Result -eq "BLOCKED" })
$overall = if ($failed.Count -eq 0 -and $blocked.Count -eq 0) { "PASS" } else { "INCOMPLETE" }

$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("# ReefVision Phase 2 Acceptance Report")
$lines.Add("")
$lines.Add("- Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')")
$lines.Add("- Branch: $branch")
$lines.Add("- Commit: $head")
$lines.Add("- Overall: **$overall**")
$lines.Add("- Packaged executable: ``$releaseExecutable``")
$lines.Add("- MSI: ``$installer``")
$lines.Add("")
$lines.Add("## Automated gate")
$lines.Add("")
$lines.Add("- Full validation and MSI build: **$(if ($SkipBuild) { 'SKIPPED' } else { 'PASS' })**")
$lines.Add("")
$lines.Add("## Packaged desktop checks")
$lines.Add("")
$lines.Add("| Check | Result | Notes |")
$lines.Add("|---|---|---|")
foreach ($result in $results) {
    $escapedNotes = $result.Notes.Replace("|", "\|")
    $lines.Add("| $($result.Name) | **$($result.Result)** | $escapedNotes |")
}
$lines.Add("")
$lines.Add("## Completion decision")
$lines.Add("")
if ($overall -eq "PASS") {
    $lines.Add("Phase 2 acceptance passed at this commit. Keep the report with the PR evidence.")
} else {
    $lines.Add("Phase 2 remains incomplete. Resolve every FAIL or BLOCKED item and rerun this script at the resulting commit.")
}

Set-Content -Path $ReportPath -Value $lines -Encoding UTF8
Write-Host "`nAcceptance report: $ReportPath" -ForegroundColor Green
Write-Host "Overall result: $overall" -ForegroundColor $(if ($overall -eq "PASS") { "Green" } else { "Yellow" })

if ($overall -ne "PASS") {
    exit 1
}
