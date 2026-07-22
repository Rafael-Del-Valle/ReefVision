param(
    [ValidateSet("x86_64-pc-windows-msvc", "i686-pc-windows-msvc", "aarch64-pc-windows-msvc")]
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

. (Join-Path $PSScriptRoot "lib\node-tools.ps1")

if (-not (Test-Path ".venv" -PathType Container)) {
    throw "Run .\scripts\bootstrap.ps1 first."
}

$PyInstaller = ".\.venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $PyInstaller -PathType Leaf)) {
    throw "PyInstaller is not installed in .venv. Rerun .\scripts\bootstrap.ps1 to install the desktop build dependencies."
}

$VenvPython = ".\.venv\Scripts\python.exe"
$PythonBase = (& $VenvPython -c "import sys; print(sys.base_prefix)").Trim()
$DependencyPaths = @(
    $PythonBase,
    (Join-Path $PythonBase "Library\bin"),
    (Join-Path $PythonBase "DLLs")
) | Where-Object { Test-Path $_ -PathType Container } | Select-Object -Unique
$RequiredRuntimeLibraries = @(
    "libcrypto-3-x64.dll",
    "libssl-3-x64.dll",
    "sqlite3.dll",
    "ffi.dll",
    "libexpat.dll",
    "liblzma.dll",
    "libbz2.dll"
)
$BundledRuntimeLibraries = foreach ($library in $RequiredRuntimeLibraries) {
    foreach ($dependencyPath in $DependencyPaths) {
        $candidate = Join-Path $dependencyPath $library
        if (Test-Path $candidate -PathType Leaf) {
            $candidate
            break
        }
    }
}

$OutputRoot = Join-Path $Root ".desktop\pyinstaller\$TargetTriple"
$DistPath = Join-Path $OutputRoot "dist"
$WorkPath = Join-Path $OutputRoot "work"
$SpecPath = Join-Path $OutputRoot "spec"
$BinariesPath = Join-Path $Root "apps\web\src-tauri\binaries"
$PackagedBackendPath = Join-Path $BinariesPath "reefvision-api"
$ProviderRuntimePath = Join-Path $Root ".desktop\provider-runtime"
$ApiRoot = Join-Path $Root "apps\api"
$DesktopEntrypoint = Join-Path $ApiRoot "reefvision\desktop.py"
$AlembicIni = Join-Path $ApiRoot "alembic.ini"
$MigrationsDir = Join-Path $ApiRoot "migrations"
$ConfigRoot = Join-Path $Root "config"
$ModelCatalogFile = Join-Path $ConfigRoot "model_catalog.json"
$TrackerCatalogFile = Join-Path $ConfigRoot "tracker_catalog.json"
$RequiredYolo11CatalogIds = @(
    "ultralytics/yolo11/detect/n",
    "ultralytics/yolo11/detect/s",
    "ultralytics/yolo11/detect/m",
    "ultralytics/yolo11/detect/l",
    "ultralytics/yolo11/detect/x"
)

function Assert-ReefVisionModelCatalog {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path $Path -PathType Leaf)) {
        throw "Required Model Hub catalog is missing: $Path"
    }
    try {
        $Catalog = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    }
    catch {
        throw "Required Model Hub catalog is not valid JSON: $Path ($($_.Exception.Message))"
    }
    if ($Catalog.schema_version -ne 2 -or $Catalog.catalog_version -ne "2.0.0") {
        throw "Model Hub catalog must use schema 2 and catalog version 2.0.0: $Path"
    }
    if (@($Catalog.models).Count -ne 40) {
        throw "Model Hub catalog must contain exactly 40 entries: $Path"
    }
    $CatalogIds = @($Catalog.models | ForEach-Object { $_.catalog_id })
    foreach ($CatalogId in $RequiredYolo11CatalogIds) {
        if ($CatalogId -notin $CatalogIds) {
            throw "Model Hub catalog is missing required YOLO11 preset ${CatalogId}: $Path"
        }
    }
}
$CollectedProviderPackages = @(
    "torch",
    "torchvision",
    "ultralytics",
    "segment_anything",
    "transformers",
    "accelerate",
    "safetensors",
    "huggingface_hub",
    "tokenizers",
    "sentencepiece",
    "nnunetv2",
    "dynamic_network_architectures",
    "batchgenerators",
    "batchgeneratorsv2",
    "cv2",
    "numpy",
    "PIL",
    "matplotlib",
    "yaml",
    "pandas",
    "polars",
    "scipy",
    "lap",
    "seaborn",
    "thop"
)
$ProviderMetadataPackages = @(
    "numpy",
    "matplotlib",
    "opencv-python",
    "pillow",
    "pyyaml",
    "requests",
    "scipy",
    "lap",
    "torch",
    "torchvision",
    "psutil",
    "polars",
    "pandas",
    "seaborn",
    "ultralytics-thop",
    "ultralytics",
    "segment-anything",
    "transformers",
    "accelerate",
    "safetensors",
    "huggingface-hub",
    "tokenizers",
    "sentencepiece",
    "nnunetv2",
    "dynamic-network-architectures",
    "batchgenerators",
    "batchgeneratorsv2"
)
$OptionalBundledTorchPatterns = @(
    "cudnn_*.dll",
    "cublas*.dll",
    "cusparse*.dll",
    "cusolver*.dll",
    "cufft*.dll",
    "curand*.dll",
    "nvrtc*.dll",
    "nvJitLink*.dll",
    "*.lib"
)

foreach ($path in @($DistPath, $WorkPath, $SpecPath, $BinariesPath, $ProviderRuntimePath)) {
    New-Item -ItemType Directory -Path $path -Force | Out-Null
}

Assert-ReefVisionModelCatalog -Path $ModelCatalogFile

$ResolvedProviderRuntimePath = (Resolve-Path $ProviderRuntimePath).Path
$Arguments = @(
    "--noconfirm",
    "--clean",
    "--onedir",
    "--windowed",
    "--name",
    "reefvision-api",
    "--distpath",
    $DistPath,
    "--workpath",
    $WorkPath,
    "--specpath",
    $SpecPath,
    "--paths",
    $ApiRoot,
    "--collect-submodules",
    "alembic",
    "--collect-submodules",
    "sqlalchemy.dialects",
    "--collect-submodules",
    "uvicorn",
    "--collect-submodules",
    "multipart",
    "--collect-submodules",
    "python_multipart",
    "--collect-submodules",
    "transformers.models",
    "--collect-submodules",
    "nnunetv2",
    "--collect-submodules",
    "dynamic_network_architectures",
    "--collect-submodules",
    "batchgenerators",
    "--collect-submodules",
    "batchgeneratorsv2",
    "--hidden-import",
    "uvicorn.logging",
    "--hidden-import",
    "uvicorn.loops.auto",
    "--hidden-import",
    "uvicorn.protocols.http.auto",
    "--hidden-import",
    "uvicorn.protocols.websockets.auto",
    "--hidden-import",
    "uvicorn.lifespan.on",
    "--hidden-import",
    "transformers.models.florence2",
    "--hidden-import",
    "transformers.models.grounding_dino",
    "--hidden-import",
    "transformers.models.owlv2",
    "--hidden-import",
    "nnunetv2.experiment_planning.plan_and_preprocess_entrypoints",
    "--hidden-import",
    "nnunetv2.run.run_training",
    "--hidden-import",
    "nnunetv2.inference.predict_from_raw_data",
    "--add-data",
    "${AlembicIni};alembic",
    "--add-data",
    "${MigrationsDir};alembic/migrations",
    "--add-data",
    "${ModelCatalogFile};config",
    "--add-data",
    "${TrackerCatalogFile};config",
    $DesktopEntrypoint
)

foreach ($package in $CollectedProviderPackages) {
    $Arguments += @("--collect-all", $package)
}
foreach ($package in $ProviderMetadataPackages) {
    $Arguments += @("--copy-metadata", $package)
}

if ($DependencyPaths.Count -gt 0) {
    Write-Host "Extending PATH for PyInstaller dependency discovery:" -ForegroundColor DarkGray
    foreach ($dependencyPath in $DependencyPaths) {
        Write-Host "  $dependencyPath" -ForegroundColor DarkGray
    }
}
if (@($BundledRuntimeLibraries).Count -gt 0) {
    Write-Host "Bundling explicit runtime libraries:" -ForegroundColor DarkGray
    foreach ($library in $BundledRuntimeLibraries) {
        Write-Host "  $library" -ForegroundColor DarkGray
        $Arguments += @("--add-binary", "${library};.")
    }
}

$PreviousPath = $env:Path
$HadPreviousAutoinstall = Test-Path Env:YOLO_AUTOINSTALL
$PreviousAutoinstall = if ($HadPreviousAutoinstall) { $env:YOLO_AUTOINSTALL } else { $null }
$HadPreviousConfigDir = Test-Path Env:YOLO_CONFIG_DIR
$PreviousConfigDir = if ($HadPreviousConfigDir) { $env:YOLO_CONFIG_DIR } else { $null }
$PreviousTransformersOffline = $env:TRANSFORMERS_OFFLINE
$PreviousHubOffline = $env:HF_HUB_OFFLINE
$env:Path = (($DependencyPaths + @($env:Path)) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join ";"
$env:YOLO_AUTOINSTALL = "false"
$env:YOLO_CONFIG_DIR = $ResolvedProviderRuntimePath
$env:TRANSFORMERS_OFFLINE = "1"
$env:HF_HUB_OFFLINE = "1"

try {
    Write-ReefVisionStep "Checking pinned provider dependencies before packaging"
    & $VenvPython -c "from pathlib import Path; from reefvision.ml.dependencies import configure_provider_runtime, require_all_implemented_providers_ready; configure_provider_runtime(data_dir=Path(r'$ResolvedProviderRuntimePath')); require_all_implemented_providers_ready(); import transformers, accelerate, safetensors, huggingface_hub, nnunetv2; import nnunetv2.experiment_planning.plan_and_preprocess_entrypoints, nnunetv2.run.run_training, nnunetv2.inference.predict_from_raw_data; import dynamic_network_architectures, batchgenerators, batchgeneratorsv2"
    if ($LASTEXITCODE -ne 0) {
        throw "Pinned provider dependency preflight failed. Rerun .\scripts\bootstrap.ps1."
    }

    Write-ReefVisionStep "Building the packaged FastAPI sidecar with PyInstaller"
    & $PyInstaller @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed while building the ReefVision desktop sidecar."
    }
}
finally {
    $env:Path = $PreviousPath
    $env:TRANSFORMERS_OFFLINE = $PreviousTransformersOffline
    $env:HF_HUB_OFFLINE = $PreviousHubOffline
    if ($HadPreviousAutoinstall) {
        $env:YOLO_AUTOINSTALL = $PreviousAutoinstall
    }
    else {
        Remove-Item Env:YOLO_AUTOINSTALL -ErrorAction SilentlyContinue
    }
    if ($HadPreviousConfigDir) {
        $env:YOLO_CONFIG_DIR = $PreviousConfigDir
    }
    else {
        Remove-Item Env:YOLO_CONFIG_DIR -ErrorAction SilentlyContinue
    }
}

$SourceBundle = Join-Path $DistPath "reefvision-api"
if (-not (Test-Path $SourceBundle -PathType Container)) {
    throw "PyInstaller did not produce the expected onedir backend bundle: $SourceBundle"
}
$PyInstallerCatalog = Join-Path $SourceBundle "_internal\config\model_catalog.json"
Assert-ReefVisionModelCatalog -Path $PyInstallerCatalog

Write-ReefVisionStep "Testing advanced providers inside the frozen backend"
$PackagedApi = Join-Path $SourceBundle "reefvision-api.exe"
$ProviderSmokeLog = Join-Path $OutputRoot "provider-import-smoke.jsonl"
Remove-Item -LiteralPath $ProviderSmokeLog -Force -ErrorAction SilentlyContinue
$ProviderSmoke = Start-Process `
    -FilePath $PackagedApi `
    -ArgumentList @("--provider-import-smoke", "--log-file", $ProviderSmokeLog) `
    -PassThru `
    -Wait
if ($ProviderSmoke.ExitCode -ne 0) {
    $Details = if (Test-Path $ProviderSmokeLog -PathType Leaf) {
        Get-Content -LiteralPath $ProviderSmokeLog -Raw
    }
    else {
        "No packaged-provider smoke log was produced."
    }
    throw "Packaged advanced-provider imports failed with exit code $($ProviderSmoke.ExitCode). $Details"
}

Write-ReefVisionStep "Trimming packaged desktop runtime to the supported installed-app footprint"
$TorchLibPath = Join-Path $SourceBundle "_internal\torch\lib"
if (Test-Path $TorchLibPath -PathType Container) {
    foreach ($pattern in $OptionalBundledTorchPatterns) {
        Get-ChildItem -Path $TorchLibPath -Filter $pattern -File -ErrorAction SilentlyContinue |
            Remove-Item -Force
    }
}

if (Test-Path $PackagedBackendPath) {
    Remove-Item -LiteralPath $PackagedBackendPath -Recurse -Force
}

$LegacyTargetExe = Join-Path $BinariesPath "reefvision-api-$TargetTriple.exe"
if (Test-Path $LegacyTargetExe -PathType Leaf) {
    Remove-Item -LiteralPath $LegacyTargetExe -Force
}

Copy-Item -LiteralPath $SourceBundle -Destination $PackagedBackendPath -Recurse
$StagedCatalog = Join-Path $PackagedBackendPath "_internal\config\model_catalog.json"
Assert-ReefVisionModelCatalog -Path $StagedCatalog
Write-Host "Desktop backend bundle: $PackagedBackendPath" -ForegroundColor Green
