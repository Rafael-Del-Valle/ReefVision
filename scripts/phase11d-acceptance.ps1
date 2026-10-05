param(
    [string]$ExpectedGpuSubstring = "RTX 4060",
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [switch]$SkipBuild,
    [switch]$KeepExtracted
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$BranchExpected = "feat/scientist-ready-phase11-packaging-hardware-20261004"
$InstallerDirectory = Join-Path $Repo "apps\web\src-tauri\target\$TargetTriple\release\bundle\msi"

Set-Location $Repo

$Branch = (git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $Branch -ne $BranchExpected) {
    throw "Phase 11D must run on $BranchExpected (found: $Branch)"
}
$Head = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Could not determine Phase 11D source commit."
}
if (git status --porcelain) {
    git status --short
    throw "Phase 11D requires a clean source tree."
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "ReefVision virtual environment is missing: $Python"
}

Write-Host ""
Write-Host "======================================================================"
Write-Host " REEFVISION SCIENTIST-READY PHASE 11D"
Write-Host " PACKAGED PROVIDER CPU / CUDA MATRIX"
Write-Host "======================================================================"
Write-Host ""
Write-Host "Branch: $Branch"
Write-Host "Commit: $Head"
Write-Host "Expected GPU: $ExpectedGpuSubstring"
Write-Host ""

Write-Host "=== FOCUSED SOURCE CONTRACTS ==="
& $Python -m pytest `
    apps/api/reefvision/tests/test_desktop.py `
    apps/api/reefvision/tests/test_packaged_provider_acceptance.py `
    -q
if ($LASTEXITCODE -ne 0) {
    throw "Phase 11D focused tests failed."
}

& $Python -m ruff check `
    apps/api/reefvision/desktop.py `
    apps/api/reefvision/packaged_provider_acceptance.py `
    apps/api/reefvision/tests/test_packaged_provider_acceptance.py `
    apps/api/reefvision/tests/test_desktop.py
if ($LASTEXITCODE -ne 0) {
    throw "Phase 11D Ruff check failed."
}

& $Python -m ruff format --check `
    apps/api/reefvision/desktop.py `
    apps/api/reefvision/packaged_provider_acceptance.py `
    apps/api/reefvision/tests/test_packaged_provider_acceptance.py `
    apps/api/reefvision/tests/test_desktop.py
if ($LASTEXITCODE -ne 0) {
    throw "Phase 11D format check failed."
}

if (-not $SkipBuild) {
    Write-Host ""
    Write-Host "=== REBUILDING FINAL PHASE 11 MSI ==="
    & powershell.exe `
        -NoLogo `
        -NoProfile `
        -ExecutionPolicy Bypass `
        -File (Join-Path $Repo "scripts\build-desktop.ps1") `
        -TargetTriple $TargetTriple
    if ($LASTEXITCODE -ne 0) {
        throw "Phase 11D MSI build failed."
    }
}

$MsiFiles = @(Get-ChildItem -LiteralPath $InstallerDirectory -Filter "*.msi" -File)
if ($MsiFiles.Count -ne 1) {
    throw "Expected exactly one MSI in $InstallerDirectory; found $($MsiFiles.Count)."
}
$Msi = $MsiFiles[0]
$ProvenancePath = Join-Path $InstallerDirectory "build-provenance.json"
if (-not (Test-Path -LiteralPath $ProvenancePath -PathType Leaf)) {
    throw "Final MSI build provenance is missing."
}
$Provenance = Get-Content -LiteralPath $ProvenancePath -Raw | ConvertFrom-Json
if ([string]$Provenance.source_commit -ne $Head) {
    throw "Final MSI was not built from the current Phase 11D commit."
}
if (-not [bool]$Provenance.source_tree_clean -or -not [bool]$Provenance.msi_verified) {
    throw "Final MSI provenance is not release-valid."
}

$MsiHash = (Get-FileHash -LiteralPath $Msi.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
$Token = [guid]::NewGuid().ToString("N").Substring(0, 10)
$SystemDrive = if ($env:SystemDrive) { $env:SystemDrive } else { "C:" }
$ExtractRoot = Join-Path $SystemDrive "rv11d-$Token"
$DataRoot = Join-Path $SystemDrive "rv11d-data-$Token"
$MsiLog = Join-Path $env:TEMP "reefvision-phase11d-$Token.log"
$EvidenceRoot = Join-Path $Repo ".artifacts\phase11d-$Token"
$EvidenceReport = Join-Path $EvidenceRoot "packaged-provider-report.json"
$SummaryPath = Join-Path $EvidenceRoot "summary.json"
New-Item -ItemType Directory -Path $EvidenceRoot,$ExtractRoot,$DataRoot -Force | Out-Null

$Summary = [ordered]@{
    schema_version = "reefvision-phase11d-acceptance-0001"
    started_at_utc = [DateTime]::UtcNow.ToString("o")
    completed_at_utc = $null
    source_commit = $Head
    installer_path = $Msi.FullName
    installer_sha256 = $MsiHash
    expected_gpu_substring = $ExpectedGpuSubstring
    packaged_report = $EvidenceReport
    status = "NOT RUN"
    failure_reason = $null
    gpu_name = $null
    torch = $null
    cuda_runtime = $null
    results = $null
    deferred = [ordered]@{
        rtx_3090 = if ($ExpectedGpuSubstring -match "3090") { "THIS RUN" } else { "DEFERRED" }
        phase10d_visual_smoke = "DEFERRED_BY_USER"
        phase11c_disposable_install = "DEFERRED"
    }
}
function Save-Summary {
    $Summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $SummaryPath -Encoding UTF8
}
Save-Summary

$PreviousBundled = $env:REEFVISION_BUNDLED_MODELS_DIR
$HadBundled = Test-Path Env:REEFVISION_BUNDLED_MODELS_DIR
$PreviousHfOffline = $env:HF_HUB_OFFLINE
$HadHfOffline = Test-Path Env:HF_HUB_OFFLINE
$PreviousTransformersOffline = $env:TRANSFORMERS_OFFLINE
$HadTransformersOffline = Test-Path Env:TRANSFORMERS_OFFLINE
$PreviousYoloAutoinstall = $env:YOLO_AUTOINSTALL
$HadYoloAutoinstall = Test-Path Env:YOLO_AUTOINSTALL

try {
    Write-Host ""
    Write-Host "=== ADMINISTRATIVE MSI EXTRACTION ==="
    $MsiProcess = Start-Process -FilePath "msiexec.exe" -ArgumentList @(
        "/a",
        ('"{0}"' -f $Msi.FullName),
        "/qn",
        ('TARGETDIR="{0}"' -f $ExtractRoot),
        "/L*v",
        ('"{0}"' -f $MsiLog)
    ) -Wait -PassThru
    if ($MsiProcess.ExitCode -notin @(0, 3010)) {
        throw "MSI administrative extraction failed with exit code $($MsiProcess.ExitCode). See $MsiLog"
    }

    $BackendCandidates = @(
        Get-ChildItem -LiteralPath $ExtractRoot -Filter "reefvision-api.exe" -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "[\\/]backend[\\/]reefvision-api[\\/]reefvision-api.exe$" }
    )
    if ($BackendCandidates.Count -ne 1) {
        throw "Expected one extracted packaged reefvision-api.exe; found $($BackendCandidates.Count)."
    }
    $Backend = $BackendCandidates[0]

    $BundledManifests = @(
        Get-ChildItem -LiteralPath $ExtractRoot -Filter "manifest.json" -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Directory.Name -eq "bundled-models" }
    )
    if ($BundledManifests.Count -ne 1) {
        throw "Expected one extracted bundled-models manifest; found $($BundledManifests.Count)."
    }
    $BundledRoot = $BundledManifests[0].Directory.FullName

    Write-Host "Packaged backend:"
    Write-Host "  $($Backend.FullName)"
    Write-Host "Bundled models:"
    Write-Host "  $BundledRoot"
    Write-Host ""

    $env:REEFVISION_BUNDLED_MODELS_DIR = $BundledRoot
    $env:HF_HUB_OFFLINE = "1"
    $env:TRANSFORMERS_OFFLINE = "1"
    $env:YOLO_AUTOINSTALL = "false"

    Write-Host "=== PACKAGED CPU / CUDA PROVIDER EXECUTION ==="
    & $Backend.FullName `
        --data-dir $DataRoot `
        --safe-mode `
        --provider-hardware-acceptance
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged provider acceptance exited with code $LASTEXITCODE."
    }

    $RawReport = Join-Path $DataRoot "provider-hardware-acceptance.json"
    if (-not (Test-Path -LiteralPath $RawReport -PathType Leaf)) {
        throw "Packaged sidecar did not produce provider-hardware-acceptance.json."
    }
    Copy-Item -LiteralPath $RawReport -Destination $EvidenceReport -Force
    $Report = Get-Content -LiteralPath $EvidenceReport -Raw | ConvertFrom-Json

    if ([string]$Report.status -ne "PASS") {
        throw "Packaged provider acceptance report did not record PASS."
    }
    if (-not [bool]$Report.packaged_runtime) {
        throw "Provider acceptance did not run from a frozen packaged runtime."
    }
    if (-not [bool]$Report.hardware.cuda_available) {
        throw "CUDA is unavailable in the packaged ReefVision runtime."
    }
    $GpuName = [string]$Report.hardware.gpu_name
    if ($GpuName -notlike "*$ExpectedGpuSubstring*") {
        throw "Expected GPU containing $ExpectedGpuSubstring but packaged runtime found $GpuName."
    }

    $Required = @(
        "yolo11n_cpu",
        "yolo11n_cuda",
        "depth_anything_v2_cpu",
        "depth_anything_v2_cuda",
        "invalid_device_rejection"
    )
    foreach ($Name in $Required) {
        $Result = $Report.results.$Name
        if ($null -eq $Result -or [string]$Result.status -ne "PASS") {
            throw "Required packaged provider result did not pass: $Name"
        }
    }

    if ([string]$Report.results.yolo11n_cuda.device_actually_used -notlike "cuda*") {
        throw "YOLO CUDA acceptance did not actually use CUDA."
    }
    if ([string]$Report.results.depth_anything_v2_cuda.device_actually_used -notlike "cuda*") {
        throw "Depth Anything CUDA acceptance did not actually use CUDA."
    }

    $Summary.status = "PASS"
    $Summary.completed_at_utc = [DateTime]::UtcNow.ToString("o")
    $Summary.gpu_name = $GpuName
    $Summary.torch = [string]$Report.hardware.torch
    $Summary.cuda_runtime = [string]$Report.hardware.torch_cuda_runtime
    $Summary.results = $Report.results
    Save-Summary
}
catch {
    $Summary.status = "FAIL"
    $Summary.completed_at_utc = [DateTime]::UtcNow.ToString("o")
    $Summary.failure_reason = $_.Exception.Message
    Save-Summary
    throw
}
finally {
    if ($HadBundled) { $env:REEFVISION_BUNDLED_MODELS_DIR = $PreviousBundled } else { Remove-Item Env:REEFVISION_BUNDLED_MODELS_DIR -ErrorAction SilentlyContinue }
    if ($HadHfOffline) { $env:HF_HUB_OFFLINE = $PreviousHfOffline } else { Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue }
    if ($HadTransformersOffline) { $env:TRANSFORMERS_OFFLINE = $PreviousTransformersOffline } else { Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue }
    if ($HadYoloAutoinstall) { $env:YOLO_AUTOINSTALL = $PreviousYoloAutoinstall } else { Remove-Item Env:YOLO_AUTOINSTALL -ErrorAction SilentlyContinue }
    if (-not $KeepExtracted) {
        Remove-Item -LiteralPath $ExtractRoot -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $DataRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (git status --porcelain) {
    git status --short
    throw "Phase 11D changed tracked source files."
}

Write-Host ""
Write-Host "======================================================================"
Write-Host " PHASE 11D PACKAGED PROVIDER MATRIX PASSED"
Write-Host "======================================================================"
Write-Host ""
Write-Host "Evidence:"
Write-Host "  $EvidenceReport"
Write-Host "Summary:"
Write-Host "  $SummaryPath"
Write-Host "GPU:"
Write-Host "  $($Summary.gpu_name)"
Write-Host "YOLO11n CPU:"
Write-Host "  $($Summary.results.yolo11n_cpu.status)"
Write-Host "YOLO11n CUDA:"
Write-Host "  $($Summary.results.yolo11n_cuda.status)"
Write-Host "Depth Anything V2 CPU:"
Write-Host "  $($Summary.results.depth_anything_v2_cpu.status)"
Write-Host "Depth Anything V2 CUDA:"
Write-Host "  $($Summary.results.depth_anything_v2_cuda.status)"
Write-Host "Invalid-device rejection:"
Write-Host "  $($Summary.results.invalid_device_rejection.status)"
Write-Host ""
Write-Host "Deferred separately:"
Write-Host "  - RTX 3090 packaged hardware run"
Write-Host "  - Phase 11C disposable install/restart/uninstall"
Write-Host "  - Phase 10D visual Node Builder smoke test"
