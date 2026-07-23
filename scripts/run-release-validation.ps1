param(
    [ValidateSet("x86_64-pc-windows-msvc", "i686-pc-windows-msvc", "aarch64-pc-windows-msvc")]
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [switch]$SkipBootstrap,
    [switch]$SkipPackaging
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$ArtifactRoot = Join-Path $Root ".artifacts\release-validation-$Timestamp"
New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
$Results = [System.Collections.Generic.List[object]]::new()

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $false)][string[]]$Arguments = @()
    )

    $Command = Get-Command $Executable -ErrorAction SilentlyContinue
    if ($null -eq $Command) {
        throw "Required command or executable was not found: $Executable"
    }

    # Windows PowerShell surfaces a native program's stderr as ErrorRecord objects.
    # Native tools routinely write warnings to stderr even on success, so determine
    # success from the process exit code rather than PowerShell's error stream.
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ExitCode = 1
    try {
        $ErrorActionPreference = "Continue"
        & $Command.Source @Arguments 2>&1
        $ExitCode = if ($null -eq $LASTEXITCODE) { 1 } else { $LASTEXITCODE }
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }

    if ($ExitCode -ne 0) {
        throw "$Executable exited with code $ExitCode."
    }
}

function Invoke-ReleaseGate {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    $SafeName = ($Name -replace "[^A-Za-z0-9._-]+", "-").Trim("-").ToLowerInvariant()
    $LogPath = Join-Path $ArtifactRoot "$SafeName.log"
    $StartedAt = Get-Date
    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    try {
        & $Action *>&1 | Tee-Object -FilePath $LogPath
        $Status = "passed"
        $ErrorText = $null
        Write-Host "PASS: $Name" -ForegroundColor Green
    }
    catch {
        $Status = "failed"
        $ErrorText = $_.Exception.Message
        $_ | Out-String | Add-Content -LiteralPath $LogPath -Encoding utf8
        Write-Host "FAIL: $Name - $ErrorText" -ForegroundColor Red
    }
    $CompletedAt = Get-Date
    [void]$Results.Add(
        [pscustomobject]@{
            name = $Name
            status = $Status
            started_at = $StartedAt.ToUniversalTime().ToString("o")
            completed_at = $CompletedAt.ToUniversalTime().ToString("o")
            duration_seconds = [math]::Round(($CompletedAt - $StartedAt).TotalSeconds, 3)
            log_path = $LogPath
            error = $ErrorText
        }
    )
}

function Add-BlockedGate {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Reason
    )

    $SafeName = ($Name -replace "[^A-Za-z0-9._-]+", "-").Trim("-").ToLowerInvariant()
    $LogPath = Join-Path $ArtifactRoot "$SafeName.log"
    "BLOCKED: $Reason" | Set-Content -LiteralPath $LogPath -Encoding utf8
    [void]$Results.Add(
        [pscustomobject]@{
            name = $Name
            status = "failed"
            started_at = (Get-Date).ToUniversalTime().ToString("o")
            completed_at = (Get-Date).ToUniversalTime().ToString("o")
            duration_seconds = 0.0
            log_path = $LogPath
            error = "Blocked: $Reason"
        }
    )
    Write-Host "BLOCKED: $Name - $Reason" -ForegroundColor Yellow
}

if (-not $SkipBootstrap) {
    Invoke-ReleaseGate "Bootstrap build environment" {
        & (Join-Path $PSScriptRoot "bootstrap.ps1") -NonInteractive -SkipPlaywrightBrowser
        if (-not $?) {
            throw "bootstrap.ps1 failed."
        }
    }
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "The ReefVision virtual environment is missing. Run without -SkipBootstrap first."
}
$FreezePolicyPath = Join-Path $Root ".reefvision-feature-freeze.json"
$FreezePolicy = Get-Content -LiteralPath $FreezePolicyPath -Raw | ConvertFrom-Json
$BaselineSha = [string]$FreezePolicy.baseline_sha
if (-not $BaselineSha) {
    throw "Feature-freeze policy does not define baseline_sha."
}

Invoke-ReleaseGate "Feature freeze policy" {
    Invoke-External $Python @(
        (Join-Path $PSScriptRoot "check-feature-freeze.py"),
        "--json-output",
        (Join-Path $ArtifactRoot "feature-freeze-report.json")
    )
}
Invoke-ReleaseGate "Repository whitespace check" {
    Invoke-External "git" @("diff", "--check", "$BaselineSha...HEAD")
    Invoke-External "git" @("diff", "--check")
    Invoke-External "git" @("diff", "--cached", "--check")
}
Invoke-ReleaseGate "Backend Ruff lint" {
    Invoke-External $Python @("-m", "ruff", "check", "apps/api", "scripts")
}
Invoke-ReleaseGate "Backend Ruff formatting" {
    Invoke-External $Python @("-m", "ruff", "format", "--check", "apps/api", "scripts")
}
Invoke-ReleaseGate "Strict mypy" {
    Invoke-External $Python @("-m", "mypy", "apps/api/reefvision")
}
Invoke-ReleaseGate "Coral import-to-export journey" {
    Invoke-External $Python @(
        "-m",
        "pytest",
        "apps/api/reefvision/tests/test_stabilization_coral_journey.py",
        "-q",
        "--junitxml=$(Join-Path $ArtifactRoot 'coral-journey.xml')"
    )
}
Invoke-ReleaseGate "Full pytest" {
    Invoke-External $Python @(
        "-m",
        "pytest",
        "apps/api/reefvision/tests",
        "--junitxml=$(Join-Path $ArtifactRoot 'pytest.xml')"
    )
}
Invoke-ReleaseGate "Alembic upgrade downgrade round trip" {
    $PreviousDataDir = $env:REEFVISION_DATA_DIR
    $MigrationDataDir = Join-Path $ArtifactRoot "migration-data"
    New-Item -ItemType Directory -Path $MigrationDataDir -Force | Out-Null
    $env:REEFVISION_DATA_DIR = $MigrationDataDir
    try {
        Invoke-External $Python @("-m", "alembic", "-c", "apps/api/alembic.ini", "upgrade", "head")
        Invoke-External $Python @("-m", "alembic", "-c", "apps/api/alembic.ini", "downgrade", "0019")
        Invoke-External $Python @("-m", "alembic", "-c", "apps/api/alembic.ini", "upgrade", "head")
        Invoke-External $Python @("-m", "alembic", "-c", "apps/api/alembic.ini", "downgrade", "base")
        Invoke-External $Python @("-m", "alembic", "-c", "apps/api/alembic.ini", "upgrade", "head")
    }
    finally {
        $env:REEFVISION_DATA_DIR = $PreviousDataDir
    }
}

Push-Location (Join-Path $Root "apps\web")
try {
    Invoke-ReleaseGate "Frontend lockfile" {
        Invoke-External "npm.cmd" @("run", "lockfile:check")
    }
    Invoke-ReleaseGate "Frontend npm clean install" {
        Invoke-External "npm.cmd" @("ci")
    }
    Invoke-ReleaseGate "Frontend Prettier" {
        Invoke-External "npm.cmd" @("run", "format:check")
    }
    Invoke-ReleaseGate "Frontend TypeScript" {
        Invoke-External "npm.cmd" @("run", "typecheck")
    }
    Invoke-ReleaseGate "Frontend Vitest" {
        Invoke-External "npm.cmd" @("run", "test", "--", "--reporter=verbose")
    }
    Invoke-ReleaseGate "Frontend production build" {
        Invoke-External "npm.cmd" @("run", "build")
    }
    Invoke-ReleaseGate "Playwright Chromium install" {
        Invoke-External "npx.cmd" @("--no-install", "playwright", "install", "chromium")
    }
    Invoke-ReleaseGate "Playwright browser tests" {
        Invoke-External "npm.cmd" @("run", "test:e2e")
    }
    Invoke-ReleaseGate "Rust format" {
        Invoke-External "cargo" @(
            "fmt",
            "--manifest-path",
            "src-tauri/Cargo.toml",
            "--",
            "--check"
        )
    }
    Invoke-ReleaseGate "Rust cargo check" {
        Invoke-External "rustup" @("target", "add", $TargetTriple)
        Invoke-External "cargo" @(
            "check",
            "--manifest-path",
            "src-tauri/Cargo.toml",
            "--target",
            $TargetTriple,
            "--locked"
        )
    }
}
finally {
    Pop-Location
}

$PackagingSucceeded = $false
if (-not $SkipPackaging) {
    $InstallerRoot = Join-Path $Root "apps\web\src-tauri\target\$TargetTriple\release\bundle\msi"
    Invoke-ReleaseGate "Tauri MSI packaging" {
        if (Test-Path -LiteralPath $InstallerRoot) {
            Get-ChildItem -LiteralPath $InstallerRoot -Filter "*.msi" -File |
                Remove-Item -Force
        }
        & (Join-Path $PSScriptRoot "build-desktop.ps1") -TargetTriple $TargetTriple
        if (-not $?) {
            throw "build-desktop.ps1 failed."
        }
        $script:PackagingSucceeded = $true
    }
    if ($PackagingSucceeded) {
        Invoke-ReleaseGate "Packaged API sidecar smoke" {
            Invoke-External $Python @(
                (Join-Path $PSScriptRoot "smoke-desktop-sidecar.py"),
                (Join-Path $Root "apps\web\src-tauri\binaries\reefvision-api\reefvision-api.exe"),
                "--timeout",
                "90"
            )
        }
        Invoke-ReleaseGate "MSI inventory" {
            $Installers = @(
                Get-ChildItem `
                    -LiteralPath $InstallerRoot `
                    -Filter "*.msi" `
                    -File `
                    -ErrorAction SilentlyContinue
            )
            if ($Installers.Count -eq 0) {
                throw "No MSI installer was produced in $InstallerRoot."
            }
            $Installers |
                Select-Object Name, Length, LastWriteTimeUtc, FullName |
                ConvertTo-Json -Depth 4 |
                Set-Content `
                    -LiteralPath (Join-Path $ArtifactRoot "msi-files.json") `
                    -Encoding utf8
        }
    }
    else {
        Add-BlockedGate `
            -Name "Packaged API sidecar smoke" `
            -Reason "Tauri MSI packaging did not complete successfully."
        Add-BlockedGate `
            -Name "MSI inventory" `
            -Reason "Tauri MSI packaging did not complete successfully."
    }
}

Invoke-ReleaseGate "Tracked working tree remains clean" {
    $TrackedStatus = (& git status --short --untracked-files=no 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "git status failed with code $LASTEXITCODE."
    }
    if ($TrackedStatus) {
        throw "Validation modified tracked files:`n$TrackedStatus"
    }
}

$Failed = @($Results | Where-Object status -eq "failed")
$SerializableResults = @(
    foreach ($Result in $Results) {
        [pscustomobject]@{
            name = [string]$Result.name
            status = [string]$Result.status
            started_at = [string]$Result.started_at
            completed_at = [string]$Result.completed_at
            duration_seconds = [double]$Result.duration_seconds
            log_path = [string]$Result.log_path
            error = if ($null -eq $Result.error) { $null } else { [string]$Result.error }
        }
    }
)
$FailureReportPath = $null
$FailureBundlePath = $null
if ($Failed.Count -gt 0) {
    $FailureReportPath = Join-Path $ArtifactRoot "release-validation-failures.json"
    $FailureDetails = @(
        foreach ($Result in $Failed) {
            $Lines = @()
            if (Test-Path -LiteralPath ([string]$Result.log_path) -PathType Leaf) {
                $Lines = @(
                    Get-Content -LiteralPath ([string]$Result.log_path) |
                        ForEach-Object { [string]$_ }
                )
            }
            [pscustomobject]@{
                name = [string]$Result.name
                error = if ($null -eq $Result.error) { $null } else { [string]$Result.error }
                log_path = [string]$Result.log_path
                line_count = @($Lines).Count
                first_lines = @($Lines | Select-Object -First 80)
                last_lines = @($Lines | Select-Object -Last 160)
            }
        }
    )
    $FailureReport = [pscustomobject]@{
        schema = "reefvision-release-validation-failures-v3"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        commit_sha = [string]((& git rev-parse HEAD).Trim())
        failures = $FailureDetails
    }
    $FailureReportJson = ConvertTo-Json -InputObject $FailureReport -Depth 10
    Set-Content -LiteralPath $FailureReportPath -Value $FailureReportJson -Encoding utf8
    $FailureBundlePath = Join-Path $ArtifactRoot "release-validation-failure-bundle.zip"
}

$Summary = [pscustomobject]@{
    schema = "reefvision-release-validation-v7"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    repository_root = [string]$Root
    commit_sha = [string]((& git rev-parse HEAD).Trim())
    feature_freeze_baseline = [string]$BaselineSha
    target_triple = [string]$TargetTriple
    artifact_root = [string]$ArtifactRoot
    failure_report_path = $FailureReportPath
    failure_bundle_path = $FailureBundlePath
    passed = $Failed.Count -eq 0
    passed_count = @($Results | Where-Object status -eq "passed").Count
    failed_count = $Failed.Count
    results = $SerializableResults
}
$SummaryPath = Join-Path $ArtifactRoot "release-validation-summary.json"
$SummaryJson = ConvertTo-Json -InputObject $Summary -Depth 8
Set-Content -LiteralPath $SummaryPath -Value $SummaryJson -Encoding utf8

if ($FailureBundlePath) {
    $BundleInputs = @(
        Get-ChildItem -LiteralPath $ArtifactRoot -File |
            Where-Object {
                $_.FullName -ne $FailureBundlePath -and
                $_.Extension -in @(".json", ".log", ".xml")
            } |
            Select-Object -ExpandProperty FullName
    )
    if ($BundleInputs.Count -gt 0) {
        Compress-Archive -LiteralPath $BundleInputs -DestinationPath $FailureBundlePath -Force
    }
}

Write-Host "`nRelease validation summary: $SummaryPath" -ForegroundColor Cyan
if ($FailureBundlePath) {
    Write-Host "Failure bundle: $FailureBundlePath" -ForegroundColor Yellow
}
$Results | Format-Table name, status, duration_seconds, error -AutoSize
if ($Failed.Count -gt 0) {
    exit 1
}
