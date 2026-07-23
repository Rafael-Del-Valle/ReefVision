param(
    [ValidateSet("x86_64-pc-windows-msvc", "i686-pc-windows-msvc", "aarch64-pc-windows-msvc")]
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$SourceTorchLib = Join-Path $Root ".venv\Lib\site-packages\torch\lib"
$StagedTorchLib = Join-Path `
    $Root `
    "apps\web\src-tauri\binaries\reefvision-api\_internal\torch\lib"
$PackagedApi = Join-Path `
    $Root `
    "apps\web\src-tauri\binaries\reefvision-api\reefvision-api.exe"
$SmokeLog = Join-Path `
    $Root `
    ".desktop\pyinstaller\$TargetTriple\provider-import-smoke-final.jsonl"
$RuntimePatterns = @(
    "cudnn_*.dll",
    "cublas*.dll",
    "cusparse*.dll",
    "cusolver*.dll",
    "cufft*.dll",
    "curand*.dll",
    "nvrtc*.dll",
    "nvJitLink*.dll"
)

if (-not (Test-Path -LiteralPath $SourceTorchLib -PathType Container)) {
    throw "The pinned PyTorch runtime directory is missing: $SourceTorchLib"
}
if (-not (Test-Path -LiteralPath $StagedTorchLib -PathType Container)) {
    throw "The staged PyInstaller Torch runtime is missing: $StagedTorchLib"
}
if (-not (Test-Path -LiteralPath $PackagedApi -PathType Leaf)) {
    throw "The staged ReefVision API sidecar is missing: $PackagedApi"
}

$RuntimeFiles = @(
    foreach ($Pattern in $RuntimePatterns) {
        Get-ChildItem `
            -LiteralPath $SourceTorchLib `
            -Filter $Pattern `
            -File `
            -ErrorAction SilentlyContinue
    }
) | Sort-Object -Property Name -Unique

if ($RuntimeFiles.Count -eq 0) {
    throw (
        "No CUDA runtime DLLs were found in the pinned PyTorch installation. " +
        "Reinstall the Windows CU121 provider environment before packaging."
    )
}

foreach ($RuntimeFile in $RuntimeFiles) {
    $Destination = Join-Path $StagedTorchLib $RuntimeFile.Name
    $NeedsCopy = -not (Test-Path -LiteralPath $Destination -PathType Leaf)
    if (-not $NeedsCopy) {
        $NeedsCopy = (Get-Item -LiteralPath $Destination).Length -ne $RuntimeFile.Length
    }
    if ($NeedsCopy) {
        Copy-Item -LiteralPath $RuntimeFile.FullName -Destination $Destination -Force
    }
    $StagedFile = Get-Item -LiteralPath $Destination
    if ($StagedFile.Length -ne $RuntimeFile.Length) {
        throw "Staged CUDA runtime size mismatch: $($RuntimeFile.Name)"
    }
}

Remove-Item -LiteralPath $SmokeLog -Force -ErrorAction SilentlyContinue
$SmokeArguments = "--provider-import-smoke --log-file `"$SmokeLog`""
$Smoke = Start-Process `
    -FilePath $PackagedApi `
    -ArgumentList $SmokeArguments `
    -PassThru `
    -Wait
if ($Smoke.ExitCode -ne 0) {
    $Details = if (Test-Path -LiteralPath $SmokeLog -PathType Leaf) {
        Get-Content -LiteralPath $SmokeLog -Raw
    }
    else {
        "No final packaged-provider smoke log was produced."
    }
    throw (
        "Final packaged provider smoke failed with exit code " +
        "$($Smoke.ExitCode). $Details"
    )
}

Write-Host (
    "Restored and verified $($RuntimeFiles.Count) PyTorch CUDA runtime DLLs " +
    "before Tauri packaging."
) -ForegroundColor Green
