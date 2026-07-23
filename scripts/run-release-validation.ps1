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

    # Windows PowerShell surfaces a native program's stderr as ErrorRecord objects.
    # Tools such as npm, Alembic, Cargo, and Rustup routinely write warnings or
    # informational messages to stderr even when they exit successfully. Temporarily
    # use Continue and decide success exclusively from the native process exit code.
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Executable @Arguments 2>&1
        $ExitCode = $LASTEXITCODE
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

Invoke-ReleaseGate "Feature freeze policy" {
    Invoke-External $Python @(
        (Join-Path $PSScriptRoot "check-feature-freeze.py"),
        "--json-output",
        (Join-Path $ArtifactRoot "feature-freeze-report.json")
    )
}
Invoke-ReleaseGate "Repository whitespace check" {
    Invoke-External "git" @("diff", "--check")
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

if (-not $SkipPackaging) {
    Invoke-ReleaseGate "Tauri MSI packaging" {
        & (Join-Path $PSScriptRoot "build-desktop.ps1") -TargetTriple $TargetTriple
        if (-not $?) {
            throw "build-desktop.ps1 failed."
        }
    }
    Invoke-ReleaseGate "Packaged API sidecar smoke" {
        Invoke-External $Python @(
            (Join-Path $PSScriptRoot "smoke-desktop-sidecar.py"),
            (Join-Path $Root "apps\web\src-tauri\binaries\reefvision-api\reefvision-api.exe"),
            "--timeout",
            "90"
        )
    }
    Invoke-ReleaseGate "MSI inventory" {
        $InstallerRoot = Join-Path $Root "apps\web\src-tauri\target\$TargetTriple\release\bundle\msi"
        $Installers = @(Get-ChildItem -LiteralPath $InstallerRoot -Filter "*.msi" -File -ErrorAction SilentlyContinue)
        if ($Installers.Count -eq 0) {
            throw "No MSI installer was produced in $InstallerRoot."
        }
        $Installers |
            Select-Object Name, Length, LastWriteTimeUtc, FullName |
            ConvertTo-Json -Depth 4 |
            Set-Content -LiteralPath (Join-Path $ArtifactRoot "msi-files.json") -Encoding utf8
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
$Summary = [pscustomobject]@{
    schema = "reefvision-release-validation-v3"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    repository_root = $Root
    commit_sha = (& git rev-parse HEAD).Trim()
    target_triple = $TargetTriple
    artifact_root = $ArtifactRoot
    passed = $Failed.Count -eq 0
    passed_count = @($Results | Where-Object status -eq "passed").Count
    failed_count = $Failed.Count
    results = $Results
}
$SummaryPath = Join-Path $ArtifactRoot "release-validation-summary.json"
$Summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $SummaryPath -Encoding utf8

Write-Host "`nRelease validation summary: $SummaryPath" -ForegroundColor Cyan
$Results | Format-Table name, status, duration_seconds, error -AutoSize
if ($Failed.Count -gt 0) {
    exit 1
}
