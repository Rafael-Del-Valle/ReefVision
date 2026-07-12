$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".venv")) {
    throw "Run ./scripts/bootstrap.ps1 first."
}

& ".\.venv\Scripts\python.exe" -m alembic -c apps/api/alembic.ini upgrade head
& ".\.venv\Scripts\python.exe" -m uvicorn reefvision.main:app --app-dir apps/api --reload --host 127.0.0.1 --port 8000
