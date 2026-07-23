param(
    [ValidateSet("x86_64-pc-windows-msvc", "i686-pc-windows-msvc", "aarch64-pc-windows-msvc")]
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [switch]$SkipBootstrap,
    [switch]$SkipPackaging,
    [switch]$RequireMsiSignature,
    [switch]$PerformMachineInstall,
    [string]$ExpectedPublisher,
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
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutputRoot = Join-Path $Root ".artifacts\complete-release-validation-$Timestamp"
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

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
    schema = "reefvision-complete-release-validation-v2"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    target_triple = $TargetTriple
    packaging_skipped = [bool]$SkipPackaging
    msi_report = $MsiReport
    external_interchange_requested = $ExternalRequested
    external_interchange_report = $ExternalReport
    passed = $true
}
$SummaryPath = Join-Path $OutputRoot "complete-release-validation.json"
$Summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $SummaryPath -Encoding utf8
Write-Host "Complete release validation report: $SummaryPath" -ForegroundColor Green
