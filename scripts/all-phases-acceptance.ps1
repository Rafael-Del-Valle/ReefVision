param(
    [switch]$SkipBootstrap,
    [switch]$SkipFrontendBuild,
    [switch]$SkipFullSuites,
    [switch]$SkipMigrationRoundTrip
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($SkipFrontendBuild -or $SkipFullSuites -or $SkipMigrationRoundTrip) {
    throw (
        "Partial all-phase acceptance is disabled during the stabilization freeze. " +
        "Run the complete non-packaging validation instead."
    )
}

$Arguments = @("-SkipPackaging")
if ($SkipBootstrap) {
    $Arguments += "-SkipBootstrap"
}

Write-Warning (
    "all-phases-acceptance.ps1 is now a compatibility wrapper. " +
    "scripts/run-release-validation.ps1 is the authoritative stabilization gate."
)
& (Join-Path $PSScriptRoot "run-release-validation.ps1") @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "The authoritative ReefVision stabilization validation failed."
}
