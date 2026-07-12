param(
    [switch]$NonInteractive,
    [switch]$SkipPlaywrightBrowser,
    [string]$ProviderRequirementsFile = "requirements/providers-windows-cu121-py312.txt"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

. (Join-Path $PSScriptRoot "lib\node-tools.ps1")

Write-Host "ReefVision first-time setup" -ForegroundColor Green
Write-Host "Project: $Root" -ForegroundColor DarkGray

# Check all external prerequisites before installing project dependencies so setup
# cannot complete the Python half and then fail unexpectedly at npm.
Write-ReefVisionStep "Checking Node.js and npm"
$NodeTools = Ensure-ReefVisionNodeTools -AllowInstall -NonInteractive:$NonInteractive

Write-ReefVisionStep "Checking Python"
$PythonCommand = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $PythonCommand) {
    throw "Python was not found. Install Python 3.11 or newer, reopen the terminal, and rerun this script."
}

$PythonVersion = & $PythonCommand.Source -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if ($LASTEXITCODE -ne 0) {
    throw "Python was found but could not be started."
}
$PythonMajorMinor = $PythonVersion.Split('.')
if ([int]$PythonMajorMinor[0] -lt 3 -or ([int]$PythonMajorMinor[0] -eq 3 -and [int]$PythonMajorMinor[1] -lt 11)) {
    throw "Python 3.11 or newer is required. Found Python $PythonVersion."
}
if ([int]$PythonMajorMinor[0] -ne 3 -or [int]$PythonMajorMinor[1] -ne 12) {
    throw "The pinned ReefVision provider stack currently requires Python 3.12.x. Found Python $PythonVersion."
}
Write-Host "Python: $PythonVersion" -ForegroundColor DarkGray

Write-ReefVisionStep "Creating ReefVision's isolated Python environment"
if (-not (Test-Path ".venv")) {
    & $PythonCommand.Source -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "Python could not create the .venv environment."
    }
} else {
    Write-Host ".venv already exists; reusing it." -ForegroundColor DarkGray
}

$VenvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython -PathType Leaf)) {
    throw "The ReefVision Python environment is incomplete. Delete '.venv' and rerun setup."
}

Write-ReefVisionStep "Installing ReefVision Python dependencies"
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
& $VenvPython -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "ReefVision Python dependency installation failed." }

$ProviderRequirementsPath = Join-Path $Root $ProviderRequirementsFile
if (-not (Test-Path $ProviderRequirementsPath -PathType Leaf)) {
    throw "Pinned provider dependency file not found: $ProviderRequirementsFile"
}
Write-ReefVisionStep "Installing pinned model-provider dependencies"
& $VenvPython -m pip install -r $ProviderRequirementsPath
if ($LASTEXITCODE -ne 0) {
    throw "Pinned model-provider dependency installation failed."
}

Write-ReefVisionStep "Installing ReefVision web dependencies"
Write-Host "This step installs many small files and may be quiet for a while." -ForegroundColor Yellow
Repair-ReefVisionPackageLock -LockFilePath "apps\web\package-lock.json"
Assert-ReefVisionPublicLockfile -NodeTools $NodeTools
if (Test-Path "apps\web\package-lock.json" -PathType Leaf) {
    Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @("--prefix", "apps/web", "ci", "--no-audit", "--no-fund", "--registry", "https://registry.npmjs.org/")
} else {
    Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @("--prefix", "apps/web", "install", "--no-audit", "--no-fund", "--registry", "https://registry.npmjs.org/")
}

if (-not $SkipPlaywrightBrowser) {
    Write-ReefVisionStep "Installing the Playwright Chromium test browser"
    Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @("--prefix", "apps/web", "exec", "--", "playwright", "install", "chromium")
}

Write-Host "`nReefVision development environment is ready." -ForegroundColor Green
Write-Host "Start the API with: .\scripts\dev-api.ps1" -ForegroundColor Green
Write-Host "Start the web app in a second terminal with: .\scripts\dev-web.ps1" -ForegroundColor Green
