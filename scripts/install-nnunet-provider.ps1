[CmdletBinding()]
param(
    [string]$Version = "2.8.1",
    [switch]$Upgrade
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Step {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python -PathType Leaf)) {
    throw "ReefVision's .venv is missing. Run .\scripts\bootstrap.ps1 first."
}

Write-Step "Checking the existing PyTorch runtime"
& $Python -c "import torch; print(f'PyTorch {torch.__version__}; CUDA available: {torch.cuda.is_available()}')"
if ($LASTEXITCODE -ne 0) {
    throw "PyTorch must be installed in ReefVision's .venv before nnU-Net."
}

Write-Step "Installing optional nnU-Net v2 provider $Version"
$Arguments = @("-m", "pip", "install")
if ($Upgrade) {
    $Arguments += "--upgrade"
}
$Arguments += "nnunetv2==$Version"
& $Python @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "nnU-Net installation failed."
}

Write-Step "Verifying the nnU-Net package and command-line entry points"
& $Python -c "from importlib.metadata import version; print('nnunetv2', version('nnunetv2'))"
if ($LASTEXITCODE -ne 0) {
    throw "nnunetv2 could not be imported after installation."
}

$Commands = @(
    "nnUNetv2_plan_and_preprocess",
    "nnUNetv2_train",
    "nnUNetv2_predict"
)
foreach ($Command in $Commands) {
    $Candidate = Join-Path (Split-Path $Python -Parent) "$Command.exe"
    if (-not (Test-Path $Candidate -PathType Leaf)) {
        $Resolved = Get-Command $Command -ErrorAction SilentlyContinue
        if ($null -eq $Resolved) {
            throw "Required nnU-Net command is missing after installation: $Command"
        }
        Write-Host "$Command -> $($Resolved.Source)"
    }
    else {
        Write-Host "$Command -> $Candidate"
    }
}

Write-Step "Running ReefVision's semantic provider preflight"
$Preflight = @'
import json
from reefvision.ml.semantic_segmentation import nnunet_dependency_status
status = nnunet_dependency_status()
print(json.dumps(status, indent=2, sort_keys=True))
raise SystemExit(0 if status["ready"] else 1)
'@
$env:PYTHONPATH = Join-Path $Root "apps\api"
& $Python -c $Preflight
if ($LASTEXITCODE -ne 0) {
    throw "ReefVision still reports the nnU-Net provider as unavailable."
}

Write-Host "`nnnU-Net semantic segmentation provider is ready." -ForegroundColor Green
