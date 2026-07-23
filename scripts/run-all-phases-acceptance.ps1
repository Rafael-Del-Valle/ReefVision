param(
    [switch]$SkipBootstrap,
    [switch]$SkipFrontendBuild,
    [switch]$SkipFullSuites,
    [switch]$SkipMigrationRoundTrip
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Arguments = @()
if ($SkipBootstrap) { $Arguments += "-SkipBootstrap" }
if ($SkipFrontendBuild) { $Arguments += "-SkipFrontendBuild" }
if ($SkipFullSuites) { $Arguments += "-SkipFullSuites" }
if ($SkipMigrationRoundTrip) { $Arguments += "-SkipMigrationRoundTrip" }

& (Join-Path $PSScriptRoot "all-phases-acceptance.ps1") @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "The ReefVision all-phase compatibility wrapper failed."
}
