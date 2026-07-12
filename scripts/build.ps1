$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

. (Join-Path $PSScriptRoot "lib\node-tools.ps1")
$NodeTools = Ensure-ReefVisionNodeTools
Assert-ReefVisionPublicLockfile -NodeTools $NodeTools

if (-not (Test-Path ".venv" -PathType Container)) {
    throw "Run .\scripts\bootstrap.ps1 first."
}

Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @("--prefix", "apps/web", "run", "build")
& ".\.venv\Scripts\python.exe" -m build
if ($LASTEXITCODE -ne 0) { throw "Python package build failed." }
