$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

. (Join-Path $PSScriptRoot "lib\node-tools.ps1")
$NodeTools = Ensure-ReefVisionNodeTools

if (-not (Test-Path "apps\web\node_modules" -PathType Container)) {
    throw "Web dependencies are not installed. Run .\scripts\bootstrap.ps1 first."
}

Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @("--prefix", "apps/web", "run", "dev")
