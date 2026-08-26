param(
    [switch]$BuildInstaller
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "ReefVision virtual environment not found: $Python"
}

function Invoke-Gate {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    Write-Host ""
    Write-Host "=== $Name ==="
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

Write-Host "ReefVision release-candidate validation"
Write-Host "Repository: $Root"
Write-Host "Installer build requested: $BuildInstaller"

Invoke-Gate "Backend Ruff" {
    & $Python -m ruff check apps/api/reefvision
}

Invoke-Gate "Backend mypy" {
    & $Python -m mypy apps/api/reefvision
}

Invoke-Gate "Items 11-18 focused acceptance" {
    & $Python -m pytest `
        apps/api/reefvision/tests/test_release_acceptance_items_11_18.py `
        apps/api/reefvision/tests/test_classification_phase5.py `
        apps/api/reefvision/tests/test_active_learning_phase7.py `
        apps/api/reefvision/tests/test_active_learning_detection_acceptance_harness.py `
        apps/api/reefvision/tests/test_video_tracking_phase6.py `
        apps/api/reefvision/tests/test_video_tracking_benchmark_phase6.py `
        apps/api/reefvision/tests/test_workflow_graphs_phase10.py `
        apps/api/reefvision/tests/test_workflow_execution_phase10.py `
        -q
}

Invoke-Gate "Full backend regression" {
    & $Python -m pytest apps/api/reefvision/tests -q
}

Invoke-Gate "Frontend TypeScript" {
    npm.cmd --prefix apps/web run typecheck
}

Invoke-Gate "Frontend regression" {
    npm.cmd --prefix apps/web run test -- --run
}

Invoke-Gate "Frontend production build" {
    npm.cmd --prefix apps/web run build
}

if ($BuildInstaller) {
    Invoke-Gate "Windows MSI build and verification" {
# Release installer gate: build-desktop.ps1 performs npm --prefix apps/web run desktop:build and MSI verification.
        & (Join-Path $Root "scripts\build-desktop.ps1") `
            -TargetTriple "x86_64-pc-windows-msvc"
    }

    $BundleRoot = Join-Path $Root "apps\web\src-tauri\target\x86_64-pc-windows-msvc\release\bundle\msi"
    $Msi = Get-ChildItem $BundleRoot -Filter "ReefVision_*_x64_en-US.msi" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $Msi) {
        throw "MSI build completed but no ReefVision MSI was found under $BundleRoot"
    }

    Write-Host ""
    Write-Host "Installer candidate:"
    Write-Host "  $($Msi.FullName)"
    Write-Host "  $([math]::Round($Msi.Length / 1MB, 2)) MB"

    $CabFiles = @(Get-ChildItem $BundleRoot -Filter "rv*.cab" -File -ErrorAction SilentlyContinue |
        Sort-Object Name)
    if ($CabFiles.Count -eq 0) {
        throw "Verified ReefVision MSI was produced without its required external rv*.cab payload."
    }
    Write-Host "External CAB payload files: $($CabFiles.Count)"
    foreach ($Cab in $CabFiles) {
        Write-Host "  $($Cab.Name)"
    }
}

Write-Host ""
Write-Host "AUTOMATED RELEASE-CANDIDATE GATES PASSED"
Write-Host "This is not final release authorization."
Write-Host "Complete docs\RELEASE_CANDIDATE_CHECKLIST.md manual acceptance before release."
