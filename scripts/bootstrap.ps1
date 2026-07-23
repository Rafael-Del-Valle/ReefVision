param(
    [switch]$NonInteractive,
    [switch]$SkipPlaywrightBrowser,
    [string]$ProviderRequirementsFile = "requirements/providers-windows-cu121-py312.txt"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

. (Join-Path $PSScriptRoot "lib\node-tools.ps1")

function Invoke-ReefVisionNativeCapture {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $false)][string[]]$Arguments = @()
    )

    $PreviousPreference = $ErrorActionPreference
    $Output = @()
    $ExitCode = 1
    try {
        $ErrorActionPreference = "Continue"
        $Output = @(& $Executable @Arguments 2>&1)
        $ExitCode = if ($null -eq $LASTEXITCODE) { 1 } else { $LASTEXITCODE }
    }
    finally {
        $ErrorActionPreference = $PreviousPreference
    }
    $Output | ForEach-Object { Write-Host $_ }
    return [pscustomobject]@{
        ExitCode = $ExitCode
        Output = ($Output | Out-String)
    }
}

function New-ReefVisionPythonEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$BasePython,
        [Parameter(Mandatory = $true)][string]$EnvironmentPath
    )

    if (Test-Path -LiteralPath $EnvironmentPath) {
        Remove-Item -LiteralPath $EnvironmentPath -Recurse -Force
    }
    & $BasePython -m venv $EnvironmentPath
    if ($LASTEXITCODE -ne 0) {
        throw "Python could not create the .venv environment."
    }
}

function Install-ReefVisionPythonDependencies {
    param(
        [Parameter(Mandatory = $true)][string]$VenvPython,
        [Parameter(Mandatory = $true)][string]$ProviderRequirementsPath
    )

    $PipUpgrade = Invoke-ReefVisionNativeCapture -Executable $VenvPython -Arguments @(
        "-m",
        "pip",
        "install",
        "--upgrade",
        "pip",
        "setuptools",
        "wheel"
    )
    if ($PipUpgrade.ExitCode -ne 0) {
        return [pscustomobject]@{
            Passed = $false
            Stage = "pip-upgrade"
            Output = $PipUpgrade.Output
        }
    }

    $ProjectInstall = Invoke-ReefVisionNativeCapture -Executable $VenvPython -Arguments @(
        "-m",
        "pip",
        "install",
        "-e",
        ".[dev]"
    )
    if ($ProjectInstall.ExitCode -ne 0) {
        return [pscustomobject]@{
            Passed = $false
            Stage = "project-install"
            Output = $ProjectInstall.Output
        }
    }

    $ProviderInstall = Invoke-ReefVisionNativeCapture -Executable $VenvPython -Arguments @(
        "-m",
        "pip",
        "install",
        "-r",
        $ProviderRequirementsPath
    )
    if ($ProviderInstall.ExitCode -ne 0) {
        return [pscustomobject]@{
            Passed = $false
            Stage = "provider-install"
            Output = $ProviderInstall.Output
        }
    }

    return [pscustomobject]@{
        Passed = $true
        Stage = "complete"
        Output = ""
    }
}

Write-Host "ReefVision first-time setup" -ForegroundColor Green
Write-Host "Project: $Root" -ForegroundColor DarkGray

# Check all external prerequisites before installing project dependencies so setup
# cannot complete the Python half and then fail unexpectedly at npm.
Write-ReefVisionStep "Checking Node.js and npm"
$NodeTools = Ensure-ReefVisionNodeTools -AllowInstall -NonInteractive:$NonInteractive

Write-ReefVisionStep "Checking Python"
$PythonCommand = Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($null -eq $PythonCommand) {
    throw "Python was not found. Install Python 3.11 or newer, reopen the terminal, and rerun this script."
}

$PythonVersion = & $PythonCommand.Source -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if ($LASTEXITCODE -ne 0) {
    throw "Python was found but could not be started."
}
$PythonMajorMinor = $PythonVersion.Split(".")
if (
    [int]$PythonMajorMinor[0] -lt 3 -or
    ([int]$PythonMajorMinor[0] -eq 3 -and [int]$PythonMajorMinor[1] -lt 11)
) {
    throw "Python 3.11 or newer is required. Found Python $PythonVersion."
}
if ([int]$PythonMajorMinor[0] -ne 3 -or [int]$PythonMajorMinor[1] -ne 12) {
    throw "The pinned ReefVision provider stack currently requires Python 3.12.x. Found Python $PythonVersion."
}
Write-Host "Python: $PythonVersion" -ForegroundColor DarkGray

$ProviderRequirementsPath = Join-Path $Root $ProviderRequirementsFile
if (-not (Test-Path -LiteralPath $ProviderRequirementsPath -PathType Leaf)) {
    throw "Pinned provider dependency file not found: $ProviderRequirementsFile"
}

Write-ReefVisionStep "Creating ReefVision's isolated Python environment"
$EnvironmentPath = Join-Path $Root ".venv"
$VenvPython = Join-Path $EnvironmentPath "Scripts\python.exe"
$ReusedEnvironment = Test-Path -LiteralPath $EnvironmentPath
if (-not $ReusedEnvironment) {
    New-ReefVisionPythonEnvironment -BasePython $PythonCommand.Source -EnvironmentPath $EnvironmentPath
} else {
    Write-Host ".venv already exists; validating it before reuse." -ForegroundColor DarkGray
}
if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    Write-Warning "The existing .venv is incomplete and will be recreated."
    New-ReefVisionPythonEnvironment -BasePython $PythonCommand.Source -EnvironmentPath $EnvironmentPath
    $ReusedEnvironment = $false
}

Write-ReefVisionStep "Installing ReefVision Python dependencies"
$PythonInstall = Install-ReefVisionPythonDependencies `
    -VenvPython $VenvPython `
    -ProviderRequirementsPath $ProviderRequirementsPath

if (-not $PythonInstall.Passed) {
    $CorruptMetadataPattern = "uninstall-no-record-file|RECORD file not found|No files were found to uninstall"
    $CanRepair = $ReusedEnvironment -and $PythonInstall.Output -match $CorruptMetadataPattern
    if (-not $CanRepair) {
        throw "ReefVision Python dependency installation failed during $($PythonInstall.Stage)."
    }

    Write-Warning (
        "The reused .venv contains corrupted package metadata. " +
        "Recreating the isolated environment and retrying once."
    )
    New-ReefVisionPythonEnvironment -BasePython $PythonCommand.Source -EnvironmentPath $EnvironmentPath
    $PythonInstall = Install-ReefVisionPythonDependencies `
        -VenvPython $VenvPython `
        -ProviderRequirementsPath $ProviderRequirementsPath
    if (-not $PythonInstall.Passed) {
        throw (
            "ReefVision Python dependency installation still failed after rebuilding .venv " +
            "during $($PythonInstall.Stage)."
        )
    }
}

Write-ReefVisionStep "Installing ReefVision web dependencies"
Write-Host "This step installs many small files and may be quiet for a while." -ForegroundColor Yellow
Repair-ReefVisionPackageLock -LockFilePath "apps\web\package-lock.json"
Assert-ReefVisionPublicLockfile -NodeTools $NodeTools
if (Test-Path "apps\web\package-lock.json" -PathType Leaf) {
    Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @(
        "--prefix",
        "apps/web",
        "ci",
        "--no-audit",
        "--no-fund",
        "--registry",
        "https://registry.npmjs.org/"
    )
} else {
    Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @(
        "--prefix",
        "apps/web",
        "install",
        "--no-audit",
        "--no-fund",
        "--registry",
        "https://registry.npmjs.org/"
    )
}

if (-not $SkipPlaywrightBrowser) {
    Write-ReefVisionStep "Installing the Playwright Chromium test browser"
    Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @(
        "--prefix",
        "apps/web",
        "exec",
        "--",
        "playwright",
        "install",
        "chromium"
    )
}

Write-Host "`nReefVision development environment is ready." -ForegroundColor Green
Write-Host "Start the API with: .\scripts\dev-api.ps1" -ForegroundColor Green
Write-Host "Start the web app in a second terminal with: .\scripts\dev-web.ps1" -ForegroundColor Green
