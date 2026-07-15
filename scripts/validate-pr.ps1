[CmdletBinding()]
param(
    [switch]$SkipE2E,
    [switch]$SkipDesktop,
    [switch]$BuildDesktopInstaller
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

. (Join-Path $PSScriptRoot "lib\node-tools.ps1")

if (-not (Test-Path ".venv" -PathType Container)) {
    throw "Run .\scripts\bootstrap.ps1 first."
}

Write-ReefVisionStep "Running backend, frontend, migration, and browser tests"
& (Join-Path $PSScriptRoot "test.ps1") -SkipE2E:$SkipE2E
if ($LASTEXITCODE -ne 0) {
    throw "ReefVision test validation failed."
}

Write-ReefVisionStep "Running production package builds"
& (Join-Path $PSScriptRoot "build.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "ReefVision package build validation failed."
}

if (-not $SkipDesktop) {
    $RustTools = Ensure-ReefVisionRustTools -Purpose "validate the ReefVision desktop application"
    $CargoManifest = Join-Path $Root "apps\web\src-tauri\Cargo.toml"

    Write-ReefVisionStep "Checking Rust formatting"
    & $RustTools.Cargo fmt --manifest-path $CargoManifest -- --check
    if ($LASTEXITCODE -ne 0) {
        throw "Rust formatting validation failed."
    }

    Write-ReefVisionStep "Running Rust Clippy"
    & $RustTools.Cargo clippy --manifest-path $CargoManifest --all-targets --all-features -- -D warnings
    if ($LASTEXITCODE -ne 0) {
        throw "Rust Clippy validation failed."
    }

    Write-ReefVisionStep "Running Rust tests"
    & $RustTools.Cargo test --manifest-path $CargoManifest --all-features
    if ($LASTEXITCODE -ne 0) {
        throw "Rust tests failed."
    }

    if ($BuildDesktopInstaller) {
        Write-ReefVisionStep "Building the complete Windows desktop installer"
        & (Join-Path $PSScriptRoot "build-desktop.ps1")
        if ($LASTEXITCODE -ne 0) {
            throw "Windows desktop installer validation failed."
        }
    }
}

Write-Host "`nAll selected ReefVision pull-request validation gates passed." -ForegroundColor Green
