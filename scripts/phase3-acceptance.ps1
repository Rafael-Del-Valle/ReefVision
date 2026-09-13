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
    throw "The repository has uncommitted changes. Commit or preserve them before Phase 3 acceptance."
}

$branch = (git branch --show-current).Trim()
if ($branch -notin @("feat/segmentation-training", "feat/semantic-segmentation-nnunet")) {
    throw "Expected the Phase 3 or Phase 3E branch but found $branch."
}

$head = (git rev-parse HEAD).Trim()
$shortHead = (git rev-parse --short HEAD).Trim()
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

if (-not $ReportPath) {
    $reportDirectory = Join-Path $Root ".desktop\acceptance"
    New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
    $ReportPath = Join-Path $reportDirectory "phase3-$timestamp-$shortHead.md"
}

if (-not $SkipBuild) {
    Write-Step "Running full validation and building the MSI"
    & (Join-Path $PSScriptRoot "validate-pr.ps1") -BuildDesktopInstaller
    if ($LASTEXITCODE -ne 0) {
        throw "Full validation or MSI creation failed. Phase 3 acceptance cannot continue."
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
    Get-Process "reefvision-desktop" -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Process -FilePath $releaseExecutable | Out-Null
}

$results.Add((Read-AcceptanceResult -Name "Segmentation dataset preflight" -Instructions @(
    "Open an existing project with a complete immutable dataset containing polygon masks.",
    "Open Training, create or select a draft, and choose Instance segmentation.",
    "Choose an installed architecture such as yolo11n-seg.",
    "Confirm the preflight reports polygon counts by split.",
    "If raster masks are present, confirm they produce an explicit exclusion warning rather than being silently used."
)))

$results.Add((Read-AcceptanceResult -Name "One-epoch segmentation training" -Instructions @(
    "Set epochs to 1, keep tiling and tuning disabled, and launch the run.",
    "Confirm the run moves through dataset preparation, training, and completed stages.",
    "Confirm metrics include box values and mask values such as keys containing (M), mask, or seg.",
    "Confirm best.pt or last.pt is listed as the finalized checkpoint."
)))

$results.Add((Read-AcceptanceResult -Name "Segmenter checkpoint registration" -Instructions @(
    "Register the completed run using the existing Register action.",
    "Confirm the resulting model is recorded with purpose segmenter and task segment.",
    "Confirm the model becomes selectable in the annotation segmentation launcher."
)))

$results.Add((Read-AcceptanceResult -Name "Polygon proposal alignment" -Instructions @(
    "Open an image from the same project and choose the registered segmenter.",
    "Run segmentation inference and wait for pending proposals.",
    "Pan and zoom the annotation canvas.",
    "Confirm proposal polygons remain aligned to the source image during transforms."
)))

$results.Add((Read-AcceptanceResult -Name "Proposal review actions" -Instructions @(
    "Accept one polygon proposal and confirm a verified mask annotation is created.",
    "Reject one proposal and confirm it disappears from pending review.",
    "Select multiple pending proposals and test bulk accept or bulk reject.",
    "Confirm accepted masks retain model, confidence, source prediction, and geometry provenance."
)))

if (-not $NoLaunch) {
    Write-Step "Restarting ReefVision for persistence verification"
    Get-Process "reefvision-desktop" -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Milliseconds 750
    Start-Process -FilePath $releaseExecutable | Out-Null
}

$results.Add((Read-AcceptanceResult -Name "Accepted-mask restart persistence" -Instructions @(
    "Reopen the same project and image after the forced application restart.",
    "Confirm every accepted mask is still present with the correct class and polygon geometry.",
    "Confirm rejected proposals remain rejected and are not recreated by merely reopening the project."
)))

$results.Add((Read-AcceptanceResult -Name "Detection regression" -Instructions @(
    "Select a registered detector model and run ordinary object-detection inference on one image.",
    "Confirm bounding-box proposals appear and can still be accepted or rejected.",
    "Confirm no polygon-mask code path is used for the detector job."
)))

$failed = @($results | Where-Object { $_.Result -eq "FAIL" })
$blocked = @($results | Where-Object { $_.Result -eq "BLOCKED" })
$overall = if ($failed.Count -eq 0 -and $blocked.Count -eq 0) { "PASS" } else { "INCOMPLETE" }

$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("# ReefVision Phase 3 Acceptance Report")
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
    $lines.Add("Phase 3 packaged acceptance passed at this commit. Keep this report with the branch or PR evidence.")
} else {
    $lines.Add("Phase 3 remains incomplete. Resolve every FAIL or BLOCKED item and rerun this script at the resulting commit.")
}

Set-Content -Path $ReportPath -Value $lines -Encoding UTF8
Write-Host "`nAcceptance report: $ReportPath" -ForegroundColor Green
Write-Host "Overall result: $overall" -ForegroundColor $(if ($overall -eq "PASS") { "Green" } else { "Yellow" })

if ($overall -ne "PASS") {
    exit 1
}
