param(
    [string]$Branch = "feat/all-phases-advancement"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$CurrentBranch = (& git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $CurrentBranch -ne $Branch) {
    throw "Run this script from the $Branch branch. Current branch: $CurrentBranch"
}

$TrackedChanges = @(& git status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect the Git working tree."
}
if ($TrackedChanges.Count -gt 0) {
    throw (
        "The tracked working tree is not clean. Commit or restore existing changes " +
        "before applying the skeleton implementation."
    )
}

$PayloadDirectory = Join-Path $Root ".skeleton-payload"
$Parts = @(
    Get-ChildItem -LiteralPath $PayloadDirectory -Filter "part-*" -File |
        Sort-Object -Property Name
)
if ($Parts.Count -ne 10) {
    throw "Expected 10 coral skeleton payload parts, but found $($Parts.Count)."
}

$ExpectedHash = "f84ad1d44b6ce818d1e65ba37e01f40f4fa1370497237ae1597a398e9d605bb3"
$TempRoot = Join-Path $env:TEMP "reefvision-skeleton-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
$ArchivePath = Join-Path $TempRoot "skeleton-payload.tar.gz"
New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null

$ExpectedPaths = @(
    "apps/api/reefvision/ml/skeleton_analysis.py",
    "apps/api/reefvision/schemas/advanced_measurements.py",
    "apps/api/reefvision/services/advanced_measurements.py",
    "apps/api/reefvision/api/routes/measurements.py",
    "apps/api/reefvision/tests/test_skeleton_analysis_phase4.py",
    "apps/web/src/features/measurements/skeletonApi.ts",
    "apps/web/src/features/measurements/SkeletonWorkbench.tsx",
    "apps/web/src/features/measurements/SkeletonWorkbench.test.tsx",
    "apps/web/src/features/measurements/MeasurementsDashboard.tsx",
    "docs/CORAL_SKELETON_ANALYSIS.md"
)

try {
    Write-Host "Reconstructing the reviewed coral skeleton payload..." -ForegroundColor Cyan
    $Base64 = [string]::Concat(@(
        $Parts | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw }
    ))
    $ArchiveBytes = [Convert]::FromBase64String($Base64)
    [IO.File]::WriteAllBytes($ArchivePath, $ArchiveBytes)

    $ActualHash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ActualHash -ne $ExpectedHash) {
        throw "Payload checksum mismatch. Expected $ExpectedHash but received $ActualHash."
    }
    Write-Host "Payload checksum passed: $ActualHash" -ForegroundColor Green

    Write-Host "Extracting the coral skeleton implementation..." -ForegroundColor Cyan
    & tar.exe -xzf $ArchivePath -C $Root
    if ($LASTEXITCODE -ne 0) {
        throw "tar.exe failed to extract the coral skeleton payload."
    }

    foreach ($RelativePath in $ExpectedPaths) {
        $AbsolutePath = Join-Path $Root ($RelativePath -replace "/", "\")
        if (-not (Test-Path -LiteralPath $AbsolutePath -PathType Leaf)) {
            throw "The extracted implementation is missing $RelativePath"
        }
    }

    $PythonCandidates = @(
        (Join-Path $Root ".venv\Scripts\python.exe"),
        (Join-Path $Root "apps\api\.venv\Scripts\python.exe")
    )
    $PythonPath = $PythonCandidates |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
    if (-not $PythonPath) {
        $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($PythonCommand) {
            $PythonPath = $PythonCommand.Source
        }
    }
    if ($PythonPath) {
        Write-Host "Compiling the new Python implementation..." -ForegroundColor Cyan
        & $PythonPath -m compileall -q @(
            $ExpectedPaths |
                Where-Object { $_ -like "*.py" } |
                ForEach-Object { Join-Path $Root ($_ -replace "/", "\") }
        )
        if ($LASTEXITCODE -ne 0) {
            throw "Python compilation failed for the coral skeleton implementation."
        }
    }
    else {
        Write-Warning "Python was not found, so compileall was skipped."
    }

    Remove-Item -LiteralPath $PayloadDirectory -Recurse -Force
    Remove-Item `
        -LiteralPath (Join-Path $Root ".github\workflows\apply-skeleton-payload.yml") `
        -Force `
        -ErrorAction SilentlyContinue

    $SelfPath = $MyInvocation.MyCommand.Path
    Remove-Item -LiteralPath $SelfPath -Force

    & git add -A -- @(
        $ExpectedPaths +
        @(
            ".skeleton-payload",
            ".github/workflows/apply-skeleton-payload.yml",
            "scripts/apply-coral-skeleton-implementation.ps1"
        )
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to stage the coral skeleton implementation."
    }

    & git diff --cached --check
    if ($LASTEXITCODE -ne 0) {
        throw "Git detected whitespace errors in the staged implementation."
    }

    & git commit -m "Implement coral skeleton analysis workbench"
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to commit the coral skeleton implementation."
    }

    & git push origin "HEAD:$Branch"
    if ($LASTEXITCODE -ne 0) {
        throw "The implementation was committed locally, but the Git push failed."
    }

    Write-Host "Coral skeleton implementation committed and pushed." -ForegroundColor Green
    Write-Host "Commit: $((& git rev-parse HEAD).Trim())" -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
