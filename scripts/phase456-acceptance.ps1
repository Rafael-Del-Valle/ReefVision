param(
    [switch]$SkipFrontendBuild,
    [switch]$SkipFullSuites
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ApiProject = Join-Path $RepoRoot "apps/api"
$WebProject = Join-Path $RepoRoot "apps/web"
$ReportRoot = Join-Path $RepoRoot ".desktop/acceptance/phase456"
New-Item -ItemType Directory -Force -Path $ReportRoot | Out-Null
$TranscriptPath = Join-Path $ReportRoot "phase456-acceptance.log"

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

Start-Transcript -Path $TranscriptPath -Force | Out-Null
try {
    Push-Location $RepoRoot

    Invoke-Checked "Ruff lint" {
        uv run --project $ApiProject ruff check `
            apps/api/reefvision `
            apps/api/migrations/versions/0020_classification_predictions.py `
            apps/api/migrations/versions/0021_video_tracking_nullable_classes.py `
            apps/api/migrations/versions/0022_video_track_provenance.py
    }

    Invoke-Checked "Ruff formatting" {
        uv run --project $ApiProject ruff format --check `
            apps/api/reefvision `
            apps/api/migrations/versions/0020_classification_predictions.py `
            apps/api/migrations/versions/0021_video_tracking_nullable_classes.py `
            apps/api/migrations/versions/0022_video_track_provenance.py
    }

    Invoke-Checked "Strict mypy" {
        uv run --project $ApiProject mypy apps/api/reefvision
    }

    Invoke-Checked "Focused Phase 4-6 backend tests" {
        uv run --project $ApiProject pytest -q `
            apps/api/reefvision/tests/test_measurement_validation_phase4.py `
            apps/api/reefvision/tests/test_coral_measurements_phase4.py `
            apps/api/reefvision/tests/test_classification_phase5.py `
            apps/api/reefvision/tests/test_video_tracking_phase6.py
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
        "Phase 4-6 static and automated acceptance passed."
        "Timestamp: $(Get-Date -Format o)"
        "Repository: $RepoRoot"
        "Commit: $(git -C $RepoRoot rev-parse HEAD)"
        ""
        "Still required manually:"
        "- Alembic 0019 -> 0022 upgrade and downgrade on a disposable database"
        "- representative manual coral measurement comparison"
        "- real six-class and binary classifier smoke runs"
        "- real ByteTrack and BoT-SORT video runs"
        "- restart persistence"
        "- packaged Windows application smoke test"
    ) | Set-Content -Path $SummaryPath -Encoding UTF8
    Write-Host "`nPhase 4-6 automated acceptance passed." -ForegroundColor Green
    Write-Host "Report: $SummaryPath"
}
finally {
    Pop-Location
    Stop-Transcript | Out-Null
}
