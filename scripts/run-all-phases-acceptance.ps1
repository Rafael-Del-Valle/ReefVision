param(
    [switch]$SkipFrontendBuild,
    [switch]$SkipFullSuites,
    [switch]$SkipMigrationRoundTrip
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ApiProject = Join-Path $RepoRoot "apps/api"
$ReportRoot = Join-Path $RepoRoot ".desktop/acceptance/all-phases"
$MigrationDataRoot = Join-Path $ReportRoot "migration-data"
$MigrationDatabaseFilename = "migration-round-trip.db"
New-Item -ItemType Directory -Force -Path $ReportRoot | Out-Null

$acceptanceArguments = @("-SkipMigrationRoundTrip")
if ($SkipFrontendBuild) {
    $acceptanceArguments += "-SkipFrontendBuild"
}
if ($SkipFullSuites) {
    $acceptanceArguments += "-SkipFullSuites"
}

& (Join-Path $PSScriptRoot "all-phases-acceptance.ps1") @acceptanceArguments
if ($LASTEXITCODE -ne 0) {
    throw "The all-phase static and automated acceptance suite failed."
}

if ($SkipMigrationRoundTrip) {
    exit 0
}

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $MigrationDataRoot
New-Item -ItemType Directory -Force -Path $MigrationDataRoot | Out-Null
$previousDataDir = $env:REEFVISION_DATA_DIR
$previousDatabaseFilename = $env:REEFVISION_DATABASE_FILENAME
try {
    $env:REEFVISION_DATA_DIR = $MigrationDataRoot
    $env:REEFVISION_DATABASE_FILENAME = $MigrationDatabaseFilename

    Write-Host "`n=== Alembic upgrade to head ===" -ForegroundColor Cyan
    uv run --project $ApiProject alembic -c apps/api/alembic.ini upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic upgrade to head failed."
    }

    Write-Host "`n=== Alembic downgrade to 0019 ===" -ForegroundColor Cyan
    uv run --project $ApiProject alembic -c apps/api/alembic.ini downgrade 0019
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic downgrade to 0019 failed."
    }

    Write-Host "`n=== Alembic re-upgrade to head ===" -ForegroundColor Cyan
    uv run --project $ApiProject alembic -c apps/api/alembic.ini upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic re-upgrade to head failed."
    }

    Write-Host "`n=== Alembic downgrade to base ===" -ForegroundColor Cyan
    uv run --project $ApiProject alembic -c apps/api/alembic.ini downgrade base
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic downgrade to base failed."
    }

    Write-Host "`n=== Alembic final upgrade to head ===" -ForegroundColor Cyan
    uv run --project $ApiProject alembic -c apps/api/alembic.ini upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic final upgrade to head failed."
    }

    $databasePath = Join-Path $MigrationDataRoot $MigrationDatabaseFilename
    if (-not (Test-Path -LiteralPath $databasePath -PathType Leaf)) {
        throw "Migration round-trip database was not created at $databasePath."
    }
    Write-Host "`nMigration round trip passed: $databasePath" -ForegroundColor Green
}
finally {
    $env:REEFVISION_DATA_DIR = $previousDataDir
    $env:REEFVISION_DATABASE_FILENAME = $previousDatabaseFilename
}
