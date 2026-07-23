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
    Assert-CommandExists "npm.cmd"

    $EnvironmentPath = Join-Path $ReportRoot "environment.txt"
    @(
        "Timestamp: $(Get-Date -Format o)"
        "Repository: $RepoRoot"
        "Commit: $(git -C $RepoRoot rev-parse HEAD)"
        "Git: $(git --version)"
        "UV: $(uv --version)"
        "Node: $(node --version)"
        "npm: $(npm.cmd --version)"
        "PowerShell: $($PSVersionTable.PSVersion)"
    ) | Set-Content -Path $EnvironmentPath -Encoding UTF8

    Invoke-Checked "Feature freeze" {
        uv run --project $ApiProject python scripts/check-feature-freeze.py `
            --json-output (Join-Path $ReportRoot "feature-freeze-report.json")
    }

    Invoke-Checked "Git whitespace" {
        git diff --check
    }

    Invoke-Checked "Ruff lint" {
        uv run --project $ApiProject ruff check `
            apps/api/reefvision `
            apps/api/migrations/versions `
            scripts
    }

    Invoke-Checked "Ruff formatting" {
        uv run --project $ApiProject ruff format --check `
            apps/api/reefvision `
            apps/api/migrations/versions `
            scripts
    }

    Invoke-Checked "Strict mypy" {
        uv run --project $ApiProject mypy apps/api/reefvision
    }

    Invoke-Checked "Stabilization coral journey" {
        uv run --project $ApiProject pytest -q `
            apps/api/reefvision/tests/test_stabilization_coral_journey.py
    }

    Invoke-Checked "All-phase focused backend tests" {
        uv run --project $ApiProject pytest -q `
            apps/api/reefvision/tests/test_project_integrity_phase1.py `
            apps/api/reefvision/tests/test_project_restart_phase1.py `
            apps/api/reefvision/tests/test_raster_cleanup_phase2.py `
            apps/api/reefvision/tests/test_segmentation_evaluation_phase3.py `
            apps/api/reefvision/tests/test_measurement_validation_phase4.py `
            apps/api/reefvision/tests/test_measurement_agreement_phase4.py `
            apps/api/reefvision/tests/test_classification_dataset_snapshots_phase5.py `
            apps/api/reefvision/tests/test_classification_evaluation_phase5.py `
            apps/api/reefvision/tests/test_video_tracking_hardening_phase6.py `
            apps/api/reefvision/tests/test_embedding_diversity_phase7.py `
            apps/api/reefvision/tests/test_prompt_points_phase8.py `
            apps/api/reefvision/tests/test_interchange_phase9.py `
            apps/api/reefvision/tests/test_workflow_recovery_phase10.py `
            apps/api/reefvision/tests/test_independent_mask_consensus_phase10.py `
            apps/api/reefvision/tests/test_multi_gpu_scheduler_phase10.py `
            apps/api/reefvision/tests/test_consensus_evaluation_gate.py `
            apps/api/reefvision/tests/test_mask_migration_lineage.py
    }

    if (-not $SkipMigrationRoundTrip) {
        Remove-Item -Force -ErrorAction SilentlyContinue $MigrationDatabase
        $PreviousDatabaseUrl = $env:REEFVISION_DATABASE_URL
        try {
            $DatabaseUrl = "sqlite:///" + ($MigrationDatabase -replace "\\", "/")
            $env:REEFVISION_DATABASE_URL = $DatabaseUrl
            Invoke-Checked "Alembic upgrade to head" {
                uv run --project $ApiProject alembic -c apps/api/alembic.ini upgrade head
            }
            Invoke-Checked "Alembic downgrade to 0019" {
                uv run --project $ApiProject alembic -c apps/api/alembic.ini downgrade 0019
            }
            Invoke-Checked "Alembic re-upgrade to head" {
                uv run --project $ApiProject alembic -c apps/api/alembic.ini upgrade head
            }
            Invoke-Checked "Alembic downgrade to base" {
                uv run --project $ApiProject alembic -c apps/api/alembic.ini downgrade base
            }
            Invoke-Checked "Alembic final upgrade to head" {
                uv run --project $ApiProject alembic -c apps/api/alembic.ini upgrade head
            }
        }
        finally {
            $env:REEFVISION_DATABASE_URL = $PreviousDatabaseUrl
        }
    }

    if (-not $SkipFullSuites) {
        Invoke-Checked "Complete backend test suite" {
            uv run --project $ApiProject pytest -q apps/api/reefvision/tests
        }
    }

    Push-Location $WebProject
    try {
        Invoke-Checked "Frontend clean install" { npm.cmd ci }
        Invoke-Checked "Frontend formatting" { npm.cmd run format:check }
        Invoke-Checked "Frontend TypeScript" { npm.cmd run typecheck }
        Invoke-Checked "Frontend unit tests" { npm.cmd run test }
        if (-not $SkipFrontendBuild) {
            Invoke-Checked "Frontend production build" { npm.cmd run build }
        }
    }
    finally {
        Pop-Location
    }

    $TrackedStatus = (git status --short --untracked-files=no | Out-String).Trim()
    if ($TrackedStatus) {
        throw "Acceptance modified tracked files:`n$TrackedStatus"
    }

    $SummaryPath = Join-Path $ReportRoot "PASS.txt"
    @(
        "All-phase static and automated acceptance passed."
        "Timestamp: $(Get-Date -Format o)"
        "Repository: $RepoRoot"
        "Commit: $(git -C $RepoRoot rev-parse HEAD)"
        "Migration head: 0034"
        ""
        "Still required outside the automated source gate:"
        "- physical multi-GPU training acceptance"
        "- real SAM 3/SAM 2/Gemini/OpenAI consensus on manually reviewed masks"
        "- CVAT, LabelMe, and private Roboflow interchange evidence"
        "- signed or unsigned MSI machine install, relaunch, persistence, and uninstall"
        "- installed-app coral journey with representative project imagery"
        "- primary user-journey simplification after the preceding gates pass"
        "- independent persisted article branch nodes only after the freeze is lifted"
    ) | Set-Content -Path $SummaryPath -Encoding UTF8
    Write-Host "`nAll-phase automated acceptance passed." -ForegroundColor Green
    Write-Host "Report: $SummaryPath"
}
finally {
    Pop-Location
    Stop-Transcript | Out-Null
}
