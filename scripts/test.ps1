param(
    [switch]$SkipE2E
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

. (Join-Path $PSScriptRoot "lib\node-tools.ps1")
$NodeTools = Ensure-ReefVisionNodeTools
Assert-ReefVisionPublicLockfile -NodeTools $NodeTools

if (-not (Test-Path ".venv" -PathType Container)) {
    throw "Run .\scripts\bootstrap.ps1 first."
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$PreviousDataDir = $env:REEFVISION_DATA_DIR
$ValidationDataDir = Join-Path ([System.IO.Path]::GetTempPath()) ("reefvision-validation-" + [guid]::NewGuid().ToString())

function Remove-ReefVisionValidationData {
    param([Parameter(Mandatory = $true)][string]$Path)

    for ($Attempt = 1; $Attempt -le 5; $Attempt += 1) {
        if (-not (Test-Path -LiteralPath $Path)) {
            return
        }

        try {
            [System.GC]::Collect()
            [System.GC]::WaitForPendingFinalizers()
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return
        }
        catch {
            if ($Attempt -eq 5) {
                Write-Warning "Could not remove temporary validation data at '$Path': $($_.Exception.Message)"
                return
            }
            Start-Sleep -Milliseconds (200 * $Attempt)
        }
    }
}

try {
    New-Item -ItemType Directory -Path $ValidationDataDir -Force | Out-Null
    $env:REEFVISION_DATA_DIR = $ValidationDataDir

    Write-ReefVisionStep "Running backend lint"
    & $Python -m ruff check apps/api
    if ($LASTEXITCODE -ne 0) { throw "Ruff lint failed." }

    Write-ReefVisionStep "Checking backend formatting"
    & $Python -m ruff format --check apps/api
    if ($LASTEXITCODE -ne 0) { throw "Ruff formatting check failed." }

    Write-ReefVisionStep "Running backend type checks"
    & $Python -m mypy apps/api/reefvision
    if ($LASTEXITCODE -ne 0) { throw "mypy failed." }

    Write-ReefVisionStep "Running backend tests"
    & $Python -m pytest apps/api/reefvision/tests
    if ($LASTEXITCODE -ne 0) { throw "Backend tests failed." }

    Write-ReefVisionStep "Verifying Alembic upgrade"
    & $Python -m alembic -c apps/api/alembic.ini upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Alembic upgrade failed." }

    Write-ReefVisionStep "Verifying Alembic downgrade"
    & $Python -m alembic -c apps/api/alembic.ini downgrade base
    if ($LASTEXITCODE -ne 0) { throw "Alembic downgrade failed." }

    Write-ReefVisionStep "Checking frontend formatting"
    Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @("--prefix", "apps/web", "run", "format:check")

    Write-ReefVisionStep "Running frontend type checks"
    Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @("--prefix", "apps/web", "run", "typecheck")

    Write-ReefVisionStep "Running frontend unit tests"
    Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @("--prefix", "apps/web", "run", "test")

    if (-not $SkipE2E) {
        Write-ReefVisionStep "Running frontend end-to-end tests"
        Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @("--prefix", "apps/web", "run", "test:e2e")
    }
}
finally {
    if ($null -eq $PreviousDataDir) {
        Remove-Item Env:REEFVISION_DATA_DIR -ErrorAction SilentlyContinue
    }
    else {
        $env:REEFVISION_DATA_DIR = $PreviousDataDir
    }
    Remove-ReefVisionValidationData -Path $ValidationDataDir
}
