param(
    [ValidateSet("x86_64-pc-windows-msvc", "i686-pc-windows-msvc", "aarch64-pc-windows-msvc")]
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [switch]$SkipBootstrap,
    [switch]$SkipPackaging,
    [switch]$RequireMsiSignature,
    [switch]$PerformMachineInstall,
    [switch]$ReleaseCandidate,
    [string]$ExpectedPublisher,
    [string]$ConsensusEvaluationReport,
    [string]$CvatArchive,
    [int]$CvatTaskId = 0,
    [string[]]$CvatCommonArguments = @(),
    [string]$LabelMeDirectory,
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
    [switch]$AllowRoboflowUpload
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutputRoot = Join-Path $Root ".artifacts\complete-release-validation-$Timestamp"
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

if ($ReleaseCandidate) {
    if ($SkipPackaging) {
        throw "A release candidate cannot skip Windows packaging."
    }
    if (-not $PerformMachineInstall) {
        throw "A release candidate requires -PerformMachineInstall."
    }
    if (-not $ConsensusEvaluationReport) {
        throw "A release candidate requires -ConsensusEvaluationReport."
    }
    if (-not $CvatArchive -or $CvatTaskId -le 0) {
        throw "A release candidate requires a CVAT archive and positive CVAT task ID."
    }
    if (-not $LabelMeDirectory) {
        throw "A release candidate requires -LabelMeDirectory."
    }
    if (
        -not $RoboflowDatasetDirectory -or
        -not $RoboflowWorkspace -or
        -not $RoboflowProject -or
        -not $AllowRoboflowUpload
    ) {
        throw (
            "A release candidate requires an explicitly authorized private Roboflow " +
            "validation upload with dataset directory, workspace, and project."
        )
    }
}

$ReleaseArguments = @("-TargetTriple", $TargetTriple)
if ($SkipBootstrap) { $ReleaseArguments += "-SkipBootstrap" }
if ($SkipPackaging) { $ReleaseArguments += "-SkipPackaging" }
& (Join-Path $PSScriptRoot "run-release-validation.ps1") @ReleaseArguments
if ($LASTEXITCODE -ne 0) {
    throw "Core release validation failed."
}

$MsiReport = $null
if (-not $SkipPackaging) {
    $InstallerRoot = Join-Path $Root "apps\web\src-tauri\target\$TargetTriple\release\bundle\msi"
    $Msi = Get-ChildItem -LiteralPath $InstallerRoot -Filter "*.msi" -File |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if (-not $Msi) {
        throw "No MSI was found after packaging in $InstallerRoot."
    }
    $MsiOutput = Join-Path $OutputRoot "msi"
    $MsiArguments = @("-MsiPath", $Msi.FullName, "-OutputDirectory", $MsiOutput)
    if ($RequireMsiSignature) { $MsiArguments += "-RequireSignature" }
    if ($PerformMachineInstall) { $MsiArguments += "-PerformMachineInstall" }
    if ($ExpectedPublisher) { $MsiArguments += @("-ExpectedPublisher", $ExpectedPublisher) }
    & (Join-Path $PSScriptRoot "verify-windows-msi.ps1") @MsiArguments
    if ($LASTEXITCODE -ne 0) {
        throw "MSI verification failed."
    }
    $MsiReport = Join-Path $MsiOutput "msi-verification.json"
}

$ConsensusReport = $null
$ConsensusPassed = $null
if ($ConsensusEvaluationReport) {
    if (-not (Test-Path -LiteralPath $ConsensusEvaluationReport -PathType Leaf)) {
        throw "Consensus evaluation report does not exist: $ConsensusEvaluationReport"
    }
    try {
        $ConsensusPayload = Get-Content -LiteralPath $ConsensusEvaluationReport -Raw |
            ConvertFrom-Json
    }
    catch {
        throw "Consensus evaluation report is not valid JSON: $ConsensusEvaluationReport"
    }
    if ($ConsensusPayload.schema -ne "reefvision-real-consensus-evaluation-v1") {
        throw "Consensus evaluation report has an unsupported schema."
    }
    $ConsensusPassed = [bool]$ConsensusPayload.passed
    if (-not $ConsensusPassed) {
        throw "Real multi-model consensus evaluation did not meet its acceptance thresholds."
    }
    $ConsensusReport = (Resolve-Path -LiteralPath $ConsensusEvaluationReport).Path
}

$ExternalRequested = [bool](
    $CvatArchive -or
    $LabelMeDirectory -or
    $RoboflowDatasetDirectory
)
$ExternalReport = $null
if ($ExternalRequested) {
    $ExternalOutput = Join-Path $OutputRoot "external-interchange"
    $ExternalParameters = @{
        OutputDirectory = $ExternalOutput
    }
    if ($CvatArchive) {
        $ExternalParameters.CvatArchive = $CvatArchive
        $ExternalParameters.CvatTaskId = $CvatTaskId
        $ExternalParameters.CvatCommonArguments = @($CvatCommonArguments)
    }
    if ($LabelMeDirectory) {
        $ExternalParameters.LabelMeDirectory = $LabelMeDirectory
    }
    if ($RoboflowDatasetDirectory) {
        $ExternalParameters.RoboflowDatasetDirectory = $RoboflowDatasetDirectory
        $ExternalParameters.RoboflowWorkspace = $RoboflowWorkspace
        $ExternalParameters.RoboflowProject = $RoboflowProject
        $ExternalParameters.RoboflowProjectType = $RoboflowProjectType
        $ExternalParameters.RoboflowProjectLicense = $RoboflowProjectLicense
        $ExternalParameters.RoboflowBatchName = $RoboflowBatchName
        $ExternalParameters.AllowRoboflowUpload = [bool]$AllowRoboflowUpload
    }
    & (Join-Path $PSScriptRoot "validate-external-interchange.ps1") @ExternalParameters
    if ($LASTEXITCODE -ne 0) {
        throw "External interchange validation failed."
    }
    $ExternalReport = Join-Path $ExternalOutput "external-interchange-validation.json"
}

$Summary = [pscustomobject]@{
    schema = "reefvision-complete-release-validation-v3"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    commit_sha = (& git rev-parse HEAD).Trim()
    target_triple = $TargetTriple
    release_candidate_requested = [bool]$ReleaseCandidate
    packaging_skipped = [bool]$SkipPackaging
    machine_install_requested = [bool]$PerformMachineInstall
    msi_report = $MsiReport
    consensus_evaluation_report = $ConsensusReport
    consensus_evaluation_passed = $ConsensusPassed
    external_interchange_requested = $ExternalRequested
    external_interchange_report = $ExternalReport
    passed = $true
}
$SummaryPath = Join-Path $OutputRoot "complete-release-validation.json"
$Summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $SummaryPath -Encoding utf8
Write-Host "Complete release validation report: $SummaryPath" -ForegroundColor Green
