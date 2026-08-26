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
$VdaRuntimeRoot = Join-Path $ProviderRuntimePath "video-depth-anything"
$VdaSourcePath = Join-Path $VdaRuntimeRoot "source"
$VdaManifestPath = Join-Path $VdaRuntimeRoot "source-manifest.json"
$ExpectedVdaCommit = "4f5ae23172ba60fd7bc11ef671cca678842c7072"
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
    $SourceCatalogPath = Join-Path $Root "config\model_catalog.json"
    if (-not (Test-Path -LiteralPath $SourceCatalogPath -PathType Leaf)) {
        throw "Source Model Hub catalog is missing: $SourceCatalogPath"
    }
    try {
        $SourceCatalog = Get-Content -LiteralPath $SourceCatalogPath -Raw | ConvertFrom-Json
    }
    catch {
        throw "Source Model Hub catalog is not valid JSON: $SourceCatalogPath ($($_.Exception.Message))"
    }

    $ExpectedCatalogIds = @(
        $SourceCatalog.models |
            ForEach-Object { [string]$_.catalog_id } |
            Sort-Object
    )
    $ActualCatalogIds = @(
        $Catalog.models |
            ForEach-Object { [string]$_.catalog_id } |
            Sort-Object
    )

    if ($ExpectedCatalogIds.Count -le 0) {
        throw "Source Model Hub catalog contains no model entries: $SourceCatalogPath"
    }
    if ($ActualCatalogIds.Count -ne $ExpectedCatalogIds.Count) {
        throw "Model Hub catalog entry count must match the source catalog ($($ExpectedCatalogIds.Count) entries): $Path"
    }

    $CatalogIdDifference = @(
        Compare-Object -ReferenceObject $ExpectedCatalogIds -DifferenceObject $ActualCatalogIds
    )
    if ($CatalogIdDifference.Count -ne 0) {
        $DifferenceText = ($CatalogIdDifference | ForEach-Object {
            "$($_.SideIndicator) $($_.InputObject)"
        }) -join "; "
        throw "Model Hub catalog IDs must exactly match the source catalog: $Path ($DifferenceText)"
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
    "thop",
    "transformers",
    "huggingface_hub",
    "tokenizers",
    "safetensors",
    "sentencepiece"
)
$ProviderMetadataPackages = @(
    "numpy",
    "matplotlib",
    "opencv-contrib-python",
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
    "huggingface-hub",
    "tokenizers",
    "safetensors",
    "sentencepiece"
)
$BundledTorchDevelopmentPatterns = @(
    "*.lib"
)
$PackagingDebrisDirectoryNames = @(
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "tests",
    "test"
)
$PackagingDebrisFilePatterns = @(
    "*.pyc",
    "*.pyo"
)

function Remove-ReefVisionPackagingDebris {
    param([Parameter(Mandatory = $true)][string]$BundlePath)

    $RemovedDirectories = 0
    $RemovedFiles = 0
    foreach ($DirectoryName in $PackagingDebrisDirectoryNames) {
        $Directories = @(Get-ChildItem -LiteralPath $BundlePath -Directory -Recurse -Force |
            Where-Object { $_.Name -ieq $DirectoryName } |
            Sort-Object { $_.FullName.Length } -Descending)
        foreach ($Directory in $Directories) {
            if (Test-Path -LiteralPath $Directory.FullName -PathType Container) {
                Remove-Item -LiteralPath $Directory.FullName -Recurse -Force
                $RemovedDirectories += 1
            }
        }
    }
    foreach ($Pattern in $PackagingDebrisFilePatterns) {
        $Files = @(Get-ChildItem -LiteralPath $BundlePath -File -Recurse -Force -Filter $Pattern)
        foreach ($File in $Files) {
            Remove-Item -LiteralPath $File.FullName -Force
            $RemovedFiles += 1
        }
    }
    Write-Host (
        "Removed $RemovedDirectories development/test/cache directories and " +
        "$RemovedFiles bytecode files from the packaged runtime."
    ) -ForegroundColor DarkGray

    $RemainingDebris = @(Get-ChildItem -LiteralPath $BundlePath -Recurse -Force |
        Where-Object {
            ($_.PSIsContainer -and $_.Name -in $PackagingDebrisDirectoryNames) -or
            (-not $_.PSIsContainer -and $_.Extension -in @(".pyc", ".pyo"))
        })
    if ($RemainingDebris.Count -gt 0) {
        throw "Packaged runtime still contains development/test/cache debris: $($RemainingDebris[0].FullName)"
    }
}

foreach ($path in @($DistPath, $WorkPath, $SpecPath, $BinariesPath, $ProviderRuntimePath)) {
    New-Item -ItemType Directory -Path $path -Force | Out-Null
}

Assert-ReefVisionModelCatalog -Path $ModelCatalogFile

if (-not (Test-Path -LiteralPath $VdaSourcePath -PathType Container)) {
    throw "Pinned Video Depth Anything source is missing: $VdaSourcePath"
}
if (-not (Test-Path -LiteralPath $VdaManifestPath -PathType Leaf)) {
    throw "Pinned Video Depth Anything source manifest is missing: $VdaManifestPath"
}
$VdaArchitecture = Join-Path $VdaSourcePath "video_depth_anything\video_depth.py"
$VdaTemporal = Join-Path $VdaSourcePath "video_depth_anything\dpt_temporal.py"
$VdaLicense = Join-Path $VdaSourcePath "LICENSE"
foreach ($RequiredVdaPath in @($VdaArchitecture, $VdaTemporal, $VdaLicense)) {
    if (-not (Test-Path -LiteralPath $RequiredVdaPath -PathType Leaf)) {
        throw "Pinned Video Depth Anything source is incomplete: $RequiredVdaPath"
    }
}
try {
    $VdaManifest = Get-Content -LiteralPath $VdaManifestPath -Raw |
        ConvertFrom-Json
}
catch {
    throw "Pinned Video Depth Anything source manifest is invalid JSON."
}
if ($VdaManifest.provider -ne "video_depth_anything") {
    throw "Pinned Video Depth Anything source manifest has the wrong provider."
}
if ($VdaManifest.commit -ne $ExpectedVdaCommit) {
    throw "Pinned Video Depth Anything source manifest has the wrong commit."
}
if ($VdaManifest.license -ne "Apache-2.0") {
    throw "Pinned Video Depth Anything source manifest has the wrong license."
}
if (
    $null -eq $VdaManifest.reefvision_compatibility_patch -or
    $VdaManifest.reefvision_compatibility_patch.upstream_behavior_preserved -ne $true
) {
    throw "Pinned Video Depth Anything compatibility provenance is missing."
}
$VdaLicenseText = Get-Content -LiteralPath $VdaLicense -Raw
if (
    -not $VdaLicenseText.Contains("Apache License") -or
    -not $VdaLicenseText.Contains("Version 2.0")
) {
    throw "Pinned Video Depth Anything LICENSE is not Apache-2.0."
}
$VdaTemporalText = Get-Content -LiteralPath $VdaTemporal -Raw
if ($VdaTemporalText.Contains("EasyDict")) {
    throw "Pinned Video Depth Anything still contains EasyDict."
}
if (-not $VdaTemporalText.Contains("motion_module_kwargs = dict(")) {
    throw "Pinned Video Depth Anything compatibility patch is missing."
}

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
    "--add-data",
    "${AlembicIni};alembic",
    "--add-data",
    "${MigrationsDir};alembic/migrations",
    "--add-data",
    "${ModelCatalogFile};config",
    "--add-data",
    "${TrackerCatalogFile};config",
    "--add-data",
    "${VdaRuntimeRoot};provider-runtime/video-depth-anything",
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
$env:Path = (($DependencyPaths + @($env:Path)) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join ";"
$env:YOLO_AUTOINSTALL = "false"
$env:YOLO_CONFIG_DIR = $ResolvedProviderRuntimePath

try {
    Write-ReefVisionStep "Checking pinned provider dependencies before packaging"
    & $VenvPython -c "from pathlib import Path; from reefvision.desktop import require_scale_assistant_marker_runtime; from reefvision.ml.dependencies import configure_provider_runtime, require_all_implemented_providers_ready; configure_provider_runtime(data_dir=Path(r'$ResolvedProviderRuntimePath')); require_all_implemented_providers_ready(); require_scale_assistant_marker_runtime()"
    if ($LASTEXITCODE -ne 0) {
        throw "Pinned provider or Scale Assistant marker-runtime preflight failed. Rerun .\scripts\bootstrap.ps1."
    }

    Write-ReefVisionStep "Checking optional AI provider dependencies before packaging"
    & $VenvPython -c "import importlib.metadata as m; expected={'transformers':'4.57.2','huggingface-hub':'0.36.0','tokenizers':'0.22.1','safetensors':'0.7.0','sentencepiece':'0.2.1'}; actual={k:m.version(k) for k in expected}; bad={k:(expected[k],actual[k]) for k in expected if actual[k] != expected[k]}; assert not bad, f'advanced provider version mismatch: {bad}'; import transformers, huggingface_hub, tokenizers, safetensors, sentencepiece; print('Advanced provider packaging runtime OK:', actual)"
    if ($LASTEXITCODE -ne 0) {
        throw "Pinned advanced-provider runtime preflight failed. Rerun .\scripts\bootstrap.ps1."
    }

    Write-ReefVisionStep "Building the packaged FastAPI sidecar with PyInstaller"
    & $PyInstaller @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed while building the ReefVision desktop sidecar."
    }
}
finally {
    $env:Path = $PreviousPath
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

$PyInstallerVdaRoot = Join-Path $SourceBundle "_internal\provider-runtime\video-depth-anything"
$PyInstallerVdaSource = Join-Path $PyInstallerVdaRoot "source\video_depth_anything\video_depth.py"
$PyInstallerVdaManifest = Join-Path $PyInstallerVdaRoot "source-manifest.json"
if (-not (Test-Path -LiteralPath $PyInstallerVdaSource -PathType Leaf)) {
    throw "PyInstaller omitted pinned Video Depth Anything source."
}
if (-not (Test-Path -LiteralPath $PyInstallerVdaManifest -PathType Leaf)) {
    throw "PyInstaller omitted Video Depth Anything provenance."
}

Write-ReefVisionStep "Trimming packaged desktop runtime to the supported installed-app footprint"
Remove-ReefVisionPackagingDebris -BundlePath $SourceBundle
$TorchLibPath = Join-Path $SourceBundle "_internal\torch\lib"
if (Test-Path $TorchLibPath -PathType Container) {
    foreach ($pattern in $BundledTorchDevelopmentPatterns) {
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
$StagedVdaRoot = Join-Path $PackagedBackendPath "_internal\provider-runtime\video-depth-anything"
$StagedVdaSource = Join-Path $StagedVdaRoot "source\video_depth_anything\video_depth.py"
$StagedVdaManifest = Join-Path $StagedVdaRoot "source-manifest.json"
if (-not (Test-Path -LiteralPath $StagedVdaSource -PathType Leaf)) {
    throw "Staged backend omitted pinned Video Depth Anything source."
}
if (-not (Test-Path -LiteralPath $StagedVdaManifest -PathType Leaf)) {
    throw "Staged backend omitted Video Depth Anything provenance."
}

Write-Host "Desktop backend bundle: $PackagedBackendPath" -ForegroundColor Green
