param(
    [ValidateSet("x86_64-pc-windows-msvc", "i686-pc-windows-msvc", "aarch64-pc-windows-msvc")]
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [switch]$AllowMissingCuda,
    [switch]$KeepCleanSeedData
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

. (Join-Path $PSScriptRoot "lib\node-tools.ps1")

if (-not (Test-Path ".venv" -PathType Container)) {
    throw "Run .\scripts\bootstrap.ps1 first."
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$ProviderRequirements = Join-Path $Root "requirements\providers-windows-cu121-py312.txt"
$TransformersPolicy = Join-Path $Root "config\transformers_model_pack.json"
$TransformersBundle = Join-Path $Root ".desktop\bundled-transformers-models"
$CleanSeedData = Join-Path $Root ".desktop\acceptance-clean-seed"
$AcceptanceRoot = Join-Path $Root ".desktop\acceptance"
$SmokeResults = Join-Path $AcceptanceRoot "transformers-model-smoke.json"
$InstallerDirectory = Join-Path $Root "apps\web\src-tauri\target\$TargetTriple\release\bundle\msi"
$PreviousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = Join-Path $Root "apps\api"

New-Item -ItemType Directory -Path $AcceptanceRoot -Force | Out-Null

try {
    Write-ReefVisionStep "Installing the pinned advanced provider dependencies"
    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
    & $Python -m pip install -r $ProviderRequirements
    if ($LASTEXITCODE -ne 0) { throw "Provider dependency installation failed." }
    & $Python -m pip check
    if ($LASTEXITCODE -ne 0) { throw "The installed Python environment has dependency conflicts." }

    Write-ReefVisionStep "Running Ruff checks"
    & $Python -m ruff check apps/api/reefvision scripts
    if ($LASTEXITCODE -ne 0) { throw "Ruff check failed." }
    & $Python -m ruff format --check apps/api/reefvision scripts
    if ($LASTEXITCODE -ne 0) { throw "Ruff format check failed." }

    Write-ReefVisionStep "Running strict backend type checking"
    & $Python -m mypy apps/api/reefvision
    if ($LASTEXITCODE -ne 0) { throw "Mypy failed." }

    Write-ReefVisionStep "Running focused advanced-provider backend tests"
    & $Python -m pytest `
        apps/api/reefvision/tests/test_advanced_vision_providers.py `
        apps/api/reefvision/tests/test_bundled_transformers_models.py `
        apps/api/reefvision/tests/test_model_delivery_contract.py `
        apps/api/reefvision/tests/test_desktop_ready_model_catalog.py `
        apps/api/reefvision/tests/test_bundled_models.py `
        -q
    if ($LASTEXITCODE -ne 0) { throw "Focused advanced-provider tests failed." }

    Write-ReefVisionStep "Running frontend formatting, type, and component tests"
    $NodeTools = Ensure-ReefVisionNodeTools
    Assert-ReefVisionPublicLockfile -NodeTools $NodeTools
    Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @("--prefix", "apps/web", "run", "format:check")
    Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @("--prefix", "apps/web", "run", "typecheck")
    Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @("--prefix", "apps/web", "run", "test")

    Write-ReefVisionStep "Downloading and hashing all six Transformers snapshots"
    & $Python .\scripts\stage-transformers-provider-models.py `
        --policy $TransformersPolicy `
        --output $TransformersBundle
    if ($LASTEXITCODE -ne 0) { throw "Transformers model-pack staging failed." }

    Write-ReefVisionStep "Testing all six Transformers models on CPU and CUDA"
    $SmokeArguments = @(
        ".\scripts\smoke-transformers-model-pack.py",
        "--root", $TransformersBundle,
        "--devices", "cpu,cuda",
        "--output", $SmokeResults
    )
    if ($AllowMissingCuda) {
        $SmokeArguments += "--allow-missing-cuda"
    }
    & $Python @SmokeArguments
    if ($LASTEXITCODE -ne 0) { throw "Real Transformers CPU/CUDA smoke testing failed." }

    Write-ReefVisionStep "Testing clean application-data model seeding"
    $SeedArguments = @(
        ".\scripts\smoke-clean-transformers-seeding.py",
        "--bundle-root", $TransformersBundle,
        "--data-dir", $CleanSeedData
    )
    if ($KeepCleanSeedData) {
        $SeedArguments += "--keep-data"
    }
    & $Python @SeedArguments
    if ($LASTEXITCODE -ne 0) { throw "Clean startup seeding failed." }

    Write-ReefVisionStep "Building and validating the enlarged MSI"
    & (Join-Path $PSScriptRoot "build-desktop.ps1") -TargetTriple $TargetTriple
    if ($LASTEXITCODE -ne 0) { throw "Desktop MSI build failed." }

    $Installers = @(
        Get-ChildItem -LiteralPath $InstallerDirectory -Filter "*.msi" -File -ErrorAction SilentlyContinue
    )
    if ($Installers.Count -eq 0) {
        throw "No MSI was produced in $InstallerDirectory"
    }

    Write-Host "" 
    Write-Host "Advanced provider acceptance passed." -ForegroundColor Green
    Write-Host "Transformers smoke results: $SmokeResults" -ForegroundColor Green
    foreach ($Installer in $Installers) {
        Write-Host "MSI: $($Installer.FullName)" -ForegroundColor Green
    }
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
}
