[CmdletBinding()]
param(
    [switch]$SkipValidation,
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
    return [pscustomobject]@{
        Name = $Name
        Result = $answer
        Notes = (Read-Host "Notes (optional)").Trim()
    }
}

$dirty = git status --porcelain
if ($dirty) {
    $dirty
    throw "The repository has uncommitted changes. Commit or preserve them before acceptance."
}
$branch = (git branch --show-current).Trim()
if ($branch -ne "feat/semantic-segmentation-nnunet") {
    throw "Phase 3E acceptance must run from feat/semantic-segmentation-nnunet."
}
$head = (git rev-parse HEAD).Trim()
$shortHead = (git rev-parse --short HEAD).Trim()
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
if (-not $ReportPath) {
    $reportDirectory = Join-Path $Root ".desktop\acceptance"
    New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
    $ReportPath = Join-Path $reportDirectory "phase3e-$timestamp-$shortHead.md"
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python -PathType Leaf)) {
    throw "ReefVision's .venv is missing. Run .\scripts\bootstrap.ps1 first."
}
$env:PYTHONPATH = Join-Path $Root "apps\api"

Write-Step "Checking the optional nnU-Net provider"
$Preflight = @'
import json
from reefvision.ml.semantic_segmentation import nnunet_dependency_status
status = nnunet_dependency_status()
print(json.dumps(status, indent=2, sort_keys=True))
raise SystemExit(0 if status["ready"] else 1)
'@
& $Python -c $Preflight
if ($LASTEXITCODE -ne 0) {
    throw "Install the provider with .\scripts\install-nnunet-provider.ps1 first."
}

if (-not $SkipValidation) {
    Write-Step "Running ReefVision validation before semantic acceptance"
    & (Join-Path $PSScriptRoot "validate-pr.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Automated validation failed. Semantic acceptance cannot continue."
    }
}

Write-Host "`nRun the source desktop in another PowerShell window:" -ForegroundColor Green
Write-Host "  Set-Location `"$Root`""
Write-Host '  npm --prefix apps/web run desktop:dev'
Write-Host "Return here after ReefVision is open."
Read-Host "Press Enter to begin the semantic checks" | Out-Null

$results = [System.Collections.Generic.List[object]]::new()
$results.Add((Read-AcceptanceResult -Name "Semantic provider and catalog" -Instructions @(
    "Open a project with a complete immutable dataset containing raster masks or polygon masks.",
    "Open Training and select Semantic segmentation.",
    "Confirm nnU-Net v2 2D is shown as Ready and uses provider nnunet.",
    "Confirm the preflight reports polygon and raster mask counts without excluding raster masks."
)))
$results.Add((Read-AcceptanceResult -Name "One-epoch semantic training" -Instructions @(
    "Keep ReefVision tiling and tuning disabled.",
    "Set epochs to 1, select a small dataset, and launch the run.",
    "Confirm the run completes planning, preprocessing, and nnU-Net training.",
    "Confirm semantic Dice metrics and semantic-model.zip are recorded."
)))
$results.Add((Read-AcceptanceResult -Name "Semantic model registration" -Instructions @(
    "Register the completed semantic run.",
    "Confirm the model has purpose semantic_segmenter and task semantic_segment.",
    "Confirm the annotation toolbar lists it with a Semantic prefix."
)))
$results.Add((Read-AcceptanceResult -Name "Semantic raster inference" -Instructions @(
    "Open an image and run the registered semantic model.",
    "Confirm one pending raster proposal appears for each predicted foreground class.",
    "Pan and zoom and confirm the green raster overlay remains aligned to the source image.",
    "Confirm the proposal mask preview endpoint loads without an error."
)))
$results.Add((Read-AcceptanceResult -Name "Semantic proposal review" -Instructions @(
    "Reject one raster proposal.",
    "Accept another proposal and confirm it becomes a verified raster mask annotation.",
    "Test bulk accept or bulk reject when multiple proposals are available.",
    "Confirm accepted mask provenance includes model, prediction, checksum, and class information."
)))
$results.Add((Read-AcceptanceResult -Name "Restart and regression" -Instructions @(
    "Close and reopen the source desktop, then reopen the project and image.",
    "Confirm accepted semantic masks persist and rejected proposals remain rejected.",
    "Run one detector inference and one YOLO instance-segmentation inference job.",
    "Confirm box and polygon proposal review still work."
)))

$failed = @($results | Where-Object { $_.Result -eq "FAIL" })
$blocked = @($results | Where-Object { $_.Result -eq "BLOCKED" })
$overall = if ($failed.Count -eq 0 -and $blocked.Count -eq 0) { "PASS" } else { "INCOMPLETE" }

$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("# ReefVision Phase 3E Acceptance Report")
$lines.Add("")
$lines.Add("- Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')")
$lines.Add("- Branch: $branch")
$lines.Add("- Commit: $head")
$lines.Add("- Overall: **$overall**")
$lines.Add("- Execution mode: source desktop with optional nnU-Net provider")
$lines.Add("")
$lines.Add("| Check | Result | Notes |")
$lines.Add("|---|---|---|")
foreach ($result in $results) {
    $escapedNotes = $result.Notes.Replace("|", "\|")
    $lines.Add("| $($result.Name) | **$($result.Result)** | $escapedNotes |")
}
$lines.Add("")
$lines.Add(
    if ($overall -eq "PASS") {
        "Phase 3E source-mode acceptance passed at this commit."
    }
    else {
        "Phase 3E remains incomplete. Resolve every FAIL or BLOCKED item and rerun."
    }
)
Set-Content -Path $ReportPath -Value $lines -Encoding UTF8
Write-Host "`nAcceptance report: $ReportPath" -ForegroundColor Green
Write-Host "Overall result: $overall" -ForegroundColor $(if ($overall -eq "PASS") { "Green" } else { "Yellow" })
if ($overall -ne "PASS") {
    exit 1
}
