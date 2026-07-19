param(
    [switch]$SkipFrontendBuild,
    [switch]$SkipFullSuites,
    [switch]$SkipMigrationRoundTrip
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ApiProject = Join-Path $RepoRoot "apps/api"
$WebProject = Join-Path $RepoRoot "apps/web"
$ReportRoot = Join-Path $RepoRoot ".desktop/acceptance/all-phases"
$MigrationDatabase = Join-Path $ReportRoot "migration-round-trip.db"
New-Item -ItemType Directory -Force -Path $ReportRoot | Out-Null
$TranscriptPath = Join-Path $ReportRoot "all-phases-acceptance.log"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host "`n=== $Label ===" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Assert-CommandExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' is not available on PATH."
    }
}

Start-Transcript -Path $TranscriptPath -Force | Out-Null
try {
    Push-Location $RepoRoot

    Assert-CommandExists "git"
    Assert-CommandExists "uv"
    Assert-CommandExists "node"
    Assert-CommandExists "npm"

    $EnvironmentPath = Join-Path $ReportRoot "environment.txt"
    @(
        "Timestamp: $(Get-Date -Format o)"
        "Repository: $RepoRoot"
        "Commit: $(git -C $RepoRoot rev-parse HEAD)"
        "Git: $(git --version)"
        "UV: $(uv --version)"
        "Node: $(node --version)"
        "npm: $(npm --version)"
        "PowerShell: $($PSVersionTable.PSVersion)"
    ) | Set-Content -Path $EnvironmentPath -Encoding UTF8

    Invoke-Checked "Ruff lint" {
        uv run --project $ApiProject ruff check `
            apps/api/reefvision `
            apps/api/migrations/versions
    }

    Invoke-Checked "Ruff formatting" {
        uv run --project $ApiProject ruff format --check `
            apps/api/reefvision `
            apps/api/migrations/versions
    }

    Invoke-Checked "Strict mypy" {
        uv run --project $ApiProject mypy apps/api/reefvision
    }

    Invoke-Checked "All-phase focused backend tests" {
        uv run --project $ApiProject pytest -q `
            apps/api/reefvision/tests/test_project_integrity_phase1.py `
            apps/api/reefvision/tests/test_raster_cleanup_phase2.py `
            apps/api/reefvision/tests/test_segmentation_evaluation_phase3.py `
            apps/api/reefvision/tests/test_measurement_validation_phase4.py `
            apps/api/reefvision/tests/test_measurement_agreement_phase4.py `
            apps/api/reefvision/tests/test_classification_phase5.py `
            apps/api/reefvision/tests/test_classification_evaluation_phase5.py `
            apps/api/reefvision/tests/test_video_tracking_phase6.py `
            apps/api/reefvision/tests/test_video_behavior_phase6.py `
            apps/api/reefvision/tests/test_embedding_diversity_phase7.py `
            apps/api/reefvision/tests/test_prompt_points_phase8.py `
            apps/api/reefvision/tests/test_coco_export_phase9.py `
            apps/api/reefvision/tests/test_workflow_validation_phase10.py `
            apps/api/reefvision/tests/test_phase456_migration_lineage.py
    }

    if (-not $SkipMigrationRoundTrip) {
        Remove-Item -Force -ErrorAction SilentlyContinue $MigrationDatabase
        $previousDatabaseUrl = $env:REEFVISION_DATABASE_URL
        try {
            $databaseUrl = "sqlite:///" + ($MigrationDatabase -replace "\\", "/")
            $env:REEFVISION_DATABASE_URL = $databaseUrl
            Invoke-Checked "Alembic upgrade to 0023" {
                uv run --project $ApiProject alembic -c apps/api/alembic.ini upgrade 0023
            }
            Invoke-Checked "Alembic downgrade to 0019" {
                uv run --project $ApiProject alembic -c apps/api/alembic.ini downgrade 0019
            }
            Invoke-Checked "Alembic re-upgrade to head" {
                uv run --project $ApiProject alembic -c apps/api/alembic.ini upgrade head
            }
        }
        finally {
            $env:REEFVISION_DATABASE_URL = $previousDatabaseUrl
        }
    }

    if (-not $SkipFullSuites) {
        Invoke-Checked "Complete backend test suite" {
            uv run --project $ApiProject pytest -q apps/api/reefvision/tests
        }
    }

    Push-Location $WebProject
    try {
        Invoke-Checked "Frontend formatting" { npm run format:check }
        Invoke-Checked "Frontend TypeScript" { npm run typecheck }
        Invoke-Checked "Frontend unit tests" { npm run test }
        if (-not $SkipFrontendBuild) {
            Invoke-Checked "Frontend production build" { npm run build }
        }
    }
    finally {
        Pop-Location
    }

    $SummaryPath = Join-Path $ReportRoot "PASS.txt"
    @(
        "All-phase static and automated acceptance passed."
        "Timestamp: $(Get-Date -Format o)"
        "Repository: $RepoRoot"
        "Commit: $(git -C $RepoRoot rev-parse HEAD)"
        "Migration head: 0023"
        ""
        "Still required manually:"
        "- representative coral segmentation model smoke runs"
        "- representative manual coral measurement comparison"
        "- real six-class and binary classifier training/inference"
        "- real ByteTrack and BoT-SORT video runs"
        "- real SAM-style provider point/brush acceptance"
        "- COCO compatibility testing in external consumers"
        "- workflow execution-engine implementation and GPU scheduling"
        "- restart persistence"
        "- packaged Windows application smoke test"
    ) | Set-Content -Path $SummaryPath -Encoding UTF8
    Write-Host "`nAll-phase automated acceptance passed." -ForegroundColor Green
    Write-Host "Report: $SummaryPath"
}
finally {
    Pop-Location
    Stop-Transcript | Out-Null
}
