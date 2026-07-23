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
    [ValidateSet(
        "object-detection",
        "single-label-classification",
        "multi-label-classification",
        "instance-segmentation",
        "semantic-segmentation"
    )]
    [string]$RoboflowProjectType = "instance-segmentation",
    [string]$RoboflowProjectLicense = "Private",
    [string]$RoboflowBatchName = "ReefVision external validation",
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

$Python = Join-Path $Root ".venv\Scripts\python.exe"

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
        $Arguments = @($CvatCommonArguments) + @(
            "task",
            "import-dataset",
            "--format",
            $CvatFormat,
            $CvatTaskId.ToString(),
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
            Start-Process "labelme" -ArgumentList @(
                (Resolve-Path -LiteralPath $LabelMeDirectory).Path
            )
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
        if (-not $env:ROBOFLOW_API_KEY) {
            throw "ROBOFLOW_API_KEY is not configured in the environment."
        }
        if (-not (Test-Path -LiteralPath $RoboflowDatasetDirectory -PathType Container)) {
            throw "Roboflow dataset directory does not exist: $RoboflowDatasetDirectory"
        }
        if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
            throw "ReefVision Python environment is missing: $Python"
        }
        $ResolvedDataset = (Resolve-Path -LiteralPath $RoboflowDatasetDirectory).Path
        $Uploader = @'
import json
import os
import pathlib
import sys
from roboflow import Roboflow

dataset, workspace_id, project_id, project_type, project_license, batch_name = sys.argv[1:]
root = pathlib.Path(dataset).resolve()
if not root.is_dir():
    raise SystemExit(f"Dataset directory is missing: {root}")
rf = Roboflow(api_key=os.environ["ROBOFLOW_API_KEY"])
workspace = rf.workspace(workspace_id)
result = workspace.upload_dataset(
    str(root),
    project_id,
    num_workers=4,
    project_license=project_license,
    project_type=project_type,
    batch_name=batch_name,
    num_retries=1,
    is_prediction=True,
)
print(json.dumps({"accepted": True, "result_type": type(result).__name__}, indent=2))
'@
        $UploaderPath = Join-Path $OutputDirectory "upload-roboflow-dataset.py"
        $UploadResultPath = Join-Path $OutputDirectory "roboflow-upload-result.json"
        Set-Content -LiteralPath $UploaderPath -Value $Uploader -Encoding utf8
        & $Python $UploaderPath @(
            $ResolvedDataset,
            $RoboflowWorkspace,
            $RoboflowProject,
            $RoboflowProjectType,
            $RoboflowProjectLicense,
            $RoboflowBatchName
        ) | Set-Content -LiteralPath $UploadResultPath -Encoding utf8
        if ($LASTEXITCODE -ne 0) {
            throw "The Roboflow Python SDK rejected the ReefVision dataset."
        }
        Add-Result "Roboflow" "passed" "Roboflow accepted the ReefVision dataset as a reviewable prediction batch." @{
            workspace = $RoboflowWorkspace
            project = $RoboflowProject
            project_type = $RoboflowProjectType
            dataset_directory = $ResolvedDataset
            upload_result = $UploadResultPath
            remote_upload_authorized = $true
            uploaded_as_prediction = $true
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
    schema = "reefvision-external-interchange-validation-v2"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    passed = $Failed.Count -eq 0
    results = $Results
    safety = @{
        roboflow_upload_requires_explicit_switch = $true
        roboflow_upload_is_marked_as_prediction = $true
        credentials_are_not_written_to_report = $true
        cvat_task_import_can_replace_existing_annotations = $true
    }
}
$ReportPath = Join-Path $OutputDirectory "external-interchange-validation.json"
$Report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $ReportPath -Encoding utf8
Write-Host "External interchange report: $ReportPath"
$Results | Format-Table consumer, status, message -AutoSize
if ($Failed.Count -gt 0) {
    exit 1
}
