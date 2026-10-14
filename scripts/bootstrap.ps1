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
    throw "Python was not found. Install Python 3.12.x, reopen the terminal, and rerun this script."
}

$PythonVersion = & $PythonCommand.Source -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if ($LASTEXITCODE -ne 0) {
    throw "Python was found but could not be started."
}
$PythonMajorMinor = $PythonVersion.Split('.')
if ([int]$PythonMajorMinor[0] -ne 3 -or [int]$PythonMajorMinor[1] -ne 12) {
    throw "ReefVision development and the pinned provider stack require Python 3.12.x. Found Python $PythonVersion."
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
$ProviderRequirementsContent = Get-Content -LiteralPath $ProviderRequirementsPath -Raw
$UsesOpenCvContrib = $ProviderRequirementsContent -match '(?m)^\s*opencv-contrib-python(?:\s|[=<>!~])'
if ($UsesOpenCvContrib) {
    Write-ReefVisionStep "Resetting OpenCV to the single supported contrib distribution"
    # Ultralytics declares opencv-python as a dependency, but OpenCV's base and contrib
    # wheels own the same cv2 namespace and must not coexist. The normal dev install above
    # resolves every transitive dependency first. Remove every OpenCV wheel variant here,
    # then install the fully pinned provider file with dependency resolution disabled so
    # Ultralytics cannot pull the base wheel back in.
    & $VenvPython -m pip uninstall -y opencv-python opencv-python-headless opencv-contrib-python opencv-contrib-python-headless
    if ($LASTEXITCODE -ne 0) {
        throw "OpenCV distribution reset failed."
    }
}

Write-ReefVisionStep "Installing pinned model-provider dependencies"
if ($UsesOpenCvContrib) {
    & $VenvPython -m pip install --no-deps -r $ProviderRequirementsPath
} else {
    & $VenvPython -m pip install -r $ProviderRequirementsPath
}
if ($LASTEXITCODE -ne 0) {
    throw "Pinned model-provider dependency installation failed."
}

$AdvancedProviderRequirementsPath = Join-Path $Root "requirements/advanced-providers-windows-py312.txt"
if (-not (Test-Path $AdvancedProviderRequirementsPath -PathType Leaf)) {
    throw "Pinned advanced-provider dependency file not found: $AdvancedProviderRequirementsPath"
}
Write-ReefVisionStep "Installing pinned optional AI provider dependencies"
# Runtime packages only. Model weights remain explicit opt-in downloads.
& $VenvPython -m pip install -r $AdvancedProviderRequirementsPath
if ($LASTEXITCODE -ne 0) {
    throw "Pinned advanced-provider dependency installation failed."
}

Write-ReefVisionStep "Verifying optional AI provider runtime"
& $VenvPython -c "import importlib.metadata as m; expected={'transformers':'4.57.2','huggingface-hub':'0.36.0','hf-xet':'1.4.3','tokenizers':'0.22.1','safetensors':'0.7.0','sentencepiece':'0.2.1'}; actual={k:m.version(k) for k in expected}; bad={k:(expected[k],actual[k]) for k in expected if actual[k] != expected[k]}; assert not bad, f'advanced provider version mismatch: {bad}'; import transformers, huggingface_hub, tokenizers, safetensors, sentencepiece; print('Advanced provider runtime OK:', actual)"
if ($LASTEXITCODE -ne 0) {
    throw "Advanced provider runtime verification failed."
}

if ($UsesOpenCvContrib) {
    Write-ReefVisionStep "Verifying a single OpenCV contrib distribution owns cv2"
    & $VenvPython -c "import importlib.metadata as m; names={d.metadata.get('Name','').lower() for d in m.distributions()}; conflicts=sorted(names & {'opencv-python','opencv-python-headless','opencv-contrib-python-headless'}); assert 'opencv-contrib-python' in names, 'opencv-contrib-python is not installed'; assert not conflicts, f'conflicting OpenCV distributions installed: {conflicts}'; print('OpenCV distribution ownership OK')"
    if ($LASTEXITCODE -ne 0) {
        throw "OpenCV distribution ownership verification failed. Rerun setup in a clean .venv if the conflict persists."
    }
}

Write-ReefVisionStep "Verifying ReefVision Scale Assistant marker runtime"
& $VenvPython -c "from reefvision.desktop import require_scale_assistant_marker_runtime; require_scale_assistant_marker_runtime(); print('Scale Assistant marker runtime OK')"
if ($LASTEXITCODE -ne 0) {
    throw "Scale Assistant marker runtime verification failed. Ensure the provider requirements install opencv-contrib-python."
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
