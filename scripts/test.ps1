$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

. (Join-Path $PSScriptRoot "lib\node-tools.ps1")
$NodeTools = Ensure-ReefVisionNodeTools
Assert-ReefVisionPublicLockfile -NodeTools $NodeTools

if (-not (Test-Path ".venv" -PathType Container)) {
    throw "Run .\scripts\bootstrap.ps1 first."
}

& ".\.venv\Scripts\python.exe" -m ruff check apps/api
if ($LASTEXITCODE -ne 0) { throw "Ruff lint failed." }
& ".\.venv\Scripts\python.exe" -m ruff format --check apps/api
if ($LASTEXITCODE -ne 0) { throw "Ruff formatting check failed." }
& ".\.venv\Scripts\python.exe" -m mypy apps/api/reefvision
if ($LASTEXITCODE -ne 0) { throw "mypy failed." }
& ".\.venv\Scripts\python.exe" -m pytest apps/api/reefvision/tests
if ($LASTEXITCODE -ne 0) { throw "Backend tests failed." }
Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @("--prefix", "apps/web", "run", "format:check")
Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @("--prefix", "apps/web", "run", "typecheck")
Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @("--prefix", "apps/web", "run", "test")
Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @("--prefix", "apps/web", "run", "test:e2e")
