param(
    [string]$CvatArchive,
    [int]$CvatTaskId = 0,
    [string]$CvatFormat = "CVAT 1.1",
    [string[]]$CvatCommonArguments = @(),
    [string]$LabelMeDirectory,
    [switch]$LaunchLabelMe,
    [string]$RoboflowDatasetDirectory,
    [string]$RoboflowWorkspace,
    [string]$RoboflowProject,
    [switch]$AllowRoboflowUpload,
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $Root ".artifacts\external-interchange-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$Results = [System.Collections.Generic.List[object]]::new()

function Add-Result {
    param(
        [string]$Consumer,
        [string]$Status,
        [string]$Message,
        [hashtable]$Evidence = @{}
    )
    [void]$Results.Add([pscustomobject]@{
        consumer = $Consumer
        status = $Status
        message = $Message
        evidence = $Evidence
    })
}

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable exited with code $LASTEXITCODE."
    }
}

function Get-FileEvidence {
    param([string]$Path)
    $Item = Get-Item -LiteralPath $Path
    return @{
        path = $Item.FullName
        size_bytes = $Item.Length
        sha256 = (Get-FileHash -LiteralPath $Item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        modified_at = $Item.LastWriteTimeUtc.ToString("o")
    }
}

# CVAT live import. The task must already contain the matching images and labels.
if ($CvatArchive) {
    try {
        if ($CvatTaskId -le 0) {
            throw "-CvatTaskId is required when -CvatArchive is supplied."
        }
        if (-not (Test-Path -LiteralPath $CvatArchive -PathType Leaf)) {
            throw "CVAT archive does not exist: $CvatArchive"
        }
        if (-not (Get-Command "cvat-cli" -ErrorAction SilentlyContinue)) {
            throw "cvat-cli is not installed. Install the official cvat-cli package first."
        }
        $Arguments = @(
            $CvatCommonArguments
            "task"
            "import-dataset"
            "--format"
            $CvatFormat
            $CvatTaskId.ToString()
            (Resolve-Path -LiteralPath $CvatArchive).Path
        )
        Invoke-Checked "cvat-cli" $Arguments
        Add-Result "CVAT" "passed" "CVAT accepted the ReefVision annotation archive." @{
            task_id = $CvatTaskId
            format = $CvatFormat
            archive = Get-FileEvidence $CvatArchive
        }
    }
    catch {
        Add-Result "CVAT" "failed" $_.Exception.Message @{}
    }
}
else {
    Add-Result "CVAT" "skipped" "Provide -CvatArchive and -CvatTaskId for a live import gate." @{}
}

# LabelMe loads every JSON through the installed application's own parser. GUI launch is optional.
if ($LabelMeDirectory) {
    try {
        if (-not (Test-Path -LiteralPath $LabelMeDirectory -PathType Container)) {
            throw "LabelMe directory does not exist: $LabelMeDirectory"
        }
        $Python = Join-Path $Root ".venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
            throw "ReefVision Python environment is missing: $Python"
        }
        $Validator = @'
import json
import pathlib
import sys
from labelme.label_file import LabelFile

root = pathlib.Path(sys.argv[1]).resolve()
files = sorted(root.rglob("*.json"))
if not files:
    raise SystemExit("No LabelMe JSON files were found")
summary = []
for path in files:
    label = LabelFile(filename=str(path))
    if not label.shapes:
        raise RuntimeError(f"LabelMe loaded no shapes from {path}")
    summary.append({"path": str(path), "shape_count": len(label.shapes)})
print(json.dumps(summary, indent=2))
'@
        $ValidatorPath = Join-Path $OutputDirectory "validate-labelme.py"
        Set-Content -LiteralPath $ValidatorPath -Value $Validator -Encoding utf8
        $OutputPath = Join-Path $OutputDirectory "labelme-load-results.json"
        & $Python $ValidatorPath (Resolve-Path -LiteralPath $LabelMeDirectory).Path |
            Set-Content -LiteralPath $OutputPath -Encoding utf8
        if ($LASTEXITCODE -ne 0) {
            throw "The installed LabelMe parser rejected the ReefVision export."
        }
        if ($LaunchLabelMe) {
            if (-not (Get-Command "labelme" -ErrorAction SilentlyContinue)) {
                throw "The LabelMe GUI command is not installed."
            }
            Start-Process "labelme" -ArgumentList @((Resolve-Path -LiteralPath $LabelMeDirectory).Path)
        }
        Add-Result "LabelMe" "passed" "Every ReefVision LabelMe JSON loaded in LabelMe's parser." @{
            directory = (Resolve-Path -LiteralPath $LabelMeDirectory).Path
            load_results = $OutputPath
            gui_launched = [bool]$LaunchLabelMe
        }
    }
    catch {
        Add-Result "LabelMe" "failed" $_.Exception.Message @{}
    }
}
else {
    Add-Result "LabelMe" "skipped" "Provide -LabelMeDirectory for an installed-parser gate." @{}
}

# Roboflow upload is intentionally opt-in because it transmits project data to a remote service.
if ($RoboflowDatasetDirectory) {
    try {
        if (-not $AllowRoboflowUpload) {
            throw "Roboflow validation requires the explicit -AllowRoboflowUpload switch."
        }
        if (-not $RoboflowWorkspace -or -not $RoboflowProject) {
            throw "-RoboflowWorkspace and -RoboflowProject are required for upload validation."
        }
        if (-not (Test-Path -LiteralPath $RoboflowDatasetDirectory -PathType Container)) {
            throw "Roboflow dataset directory does not exist: $RoboflowDatasetDirectory"
        }
        if (-not (Get-Command "roboflow" -ErrorAction SilentlyContinue)) {
            throw "The Roboflow CLI is not installed or authenticated."
        }
        $ResolvedDataset = (Resolve-Path -LiteralPath $RoboflowDatasetDirectory).Path
        Invoke-Checked "roboflow" @(
            "import"
            "-w"
            $RoboflowWorkspace
            "-p"
            $RoboflowProject
            $ResolvedDataset
        )
        Add-Result "Roboflow" "passed" "Roboflow CLI accepted the ReefVision dataset directory." @{
            workspace = $RoboflowWorkspace
            project = $RoboflowProject
            dataset_directory = $ResolvedDataset
            remote_upload_authorized = $true
        }
    }
    catch {
        Add-Result "Roboflow" "failed" $_.Exception.Message @{}
    }
}
else {
    Add-Result "Roboflow" "skipped" "Provide a dataset directory and explicit upload authorization for a live gate." @{}
}

$Failed = @($Results | Where-Object status -eq "failed")
$Report = [pscustomobject]@{
    schema = "reefvision-external-interchange-validation-v1"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    passed = $Failed.Count -eq 0
    results = $Results
    safety = @{
        roboflow_upload_requires_explicit_switch = $true
        credentials_are_not_written_to_report = $true
        cvat_import_replaces_or_merges_according_to_server_format_behavior = $true
    }
}
$ReportPath = Join-Path $OutputDirectory "external-interchange-validation.json"
$Report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $ReportPath -Encoding utf8
Write-Host "External interchange report: $ReportPath"
$Results | Format-Table consumer, status, message -AutoSize
if ($Failed.Count -gt 0) {
    exit 1
}
