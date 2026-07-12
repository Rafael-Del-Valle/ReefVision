$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

. (Join-Path $PSScriptRoot "lib\node-tools.ps1")

Write-Host "ReefVision prerequisite check" -ForegroundColor Green
$NodeTools = Ensure-ReefVisionNodeTools

$PythonCommand = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $PythonCommand) {
    throw "Python was not found. ReefVision requires Python 3.11 or newer."
}

$PythonVersion = & $PythonCommand.Source -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
Write-Host "Python: $PythonVersion" -ForegroundColor DarkGray
Write-Host "All external prerequisites were found." -ForegroundColor Green
