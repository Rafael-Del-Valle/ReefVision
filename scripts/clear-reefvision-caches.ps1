param(
    [ValidateSet("x86_64-pc-windows-msvc", "i686-pc-windows-msvc", "aarch64-pc-windows-msvc")]
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [switch]$IncludeValidationArtifacts,
    [switch]$IncludeNodeModules,
    [switch]$IncludeUserModelCaches,
    [switch]$IncludeCompletedTransformerSnapshots
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Get-ReefVisionPathBytes {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return [int64]0
    }
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        return [int64](Get-Item -LiteralPath $Path -Force).Length
    }
    $Measurement = Get-ChildItem `
        -LiteralPath $Path `
        -File `
        -Recurse `
        -Force `
        -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum
    if ($null -eq $Measurement.Sum) {
        return [int64]0
    }
    return [int64]$Measurement.Sum
}

function Format-ReefVisionBytes {
    param([Parameter(Mandatory = $true)][int64]$Bytes)

    $Units = @("B", "KiB", "MiB", "GiB", "TiB")
    $Value = [double][math]::Max($Bytes, 0)
    foreach ($Unit in $Units) {
        if ($Value -lt 1024 -or $Unit -eq "TiB") {
            return "{0:N2} {1}" -f $Value, $Unit
        }
        $Value /= 1024
    }
    return "{0:N2} TiB" -f $Value
}

function Add-Candidate {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.Generic.List[string]]$Candidates,
        [Parameter(Mandatory = $true)][string]$Path
    )

    if (Test-Path -LiteralPath $Path) {
        [void]$Candidates.Add((Resolve-Path -LiteralPath $Path).Path)
    }
}

Write-Host "Cleaning disposable ReefVision packaging workspace..." -ForegroundColor Cyan
$PackagingCleanup = Join-Path $PSScriptRoot "clean-packaging-workspace.ps1"
$PackagingArguments = @("-TargetTriple", $TargetTriple)
if ($IncludeCompletedTransformerSnapshots) {
    $PackagingArguments += "-RemoveCompletedTransformerSnapshots"
}
& $PackagingCleanup @PackagingArguments
if (-not $?) {
    throw "Packaging workspace cleanup failed."
}

$Candidates = [System.Collections.Generic.List[string]]::new()
foreach ($RelativePath in @(
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "apps\api\.pytest_cache",
    "apps\api\.mypy_cache",
    "apps\api\.ruff_cache",
    "apps\web\node_modules\.vite",
    "apps\web\node_modules\.cache",
    "apps\web\test-results",
    "apps\web\playwright-report",
    "apps\web\coverage"
)) {
    Add-Candidate -Candidates $Candidates -Path (Join-Path $Root $RelativePath)
}

# Restrict bytecode discovery to source trees. Traversing .venv, node_modules,
# downloaded model packs, or Rust targets can take longer than rebuilding them.
foreach ($RelativeSourceRoot in @("apps\api", "scripts")) {
    $SourceRoot = Join-Path $Root $RelativeSourceRoot
    if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) {
        continue
    }
    Get-ChildItem `
        -LiteralPath $SourceRoot `
        -Directory `
        -Recurse `
        -Force `
        -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "__pycache__" } |
        ForEach-Object {
            Add-Candidate -Candidates $Candidates -Path $_.FullName
        }
    Get-ChildItem `
        -LiteralPath $SourceRoot `
        -File `
        -Recurse `
        -Force `
        -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
        ForEach-Object {
            Add-Candidate -Candidates $Candidates -Path $_.FullName
        }
}

if ($IncludeValidationArtifacts) {
    Add-Candidate -Candidates $Candidates -Path (Join-Path $Root ".artifacts")
}
if ($IncludeNodeModules) {
    Add-Candidate -Candidates $Candidates -Path (Join-Path $Root "apps\web\node_modules")
}

if ($IncludeUserModelCaches) {
    $SettingsPath = if ($env:REEFVISION_STORAGE_SETTINGS_FILE) {
        [System.IO.Path]::GetFullPath($env:REEFVISION_STORAGE_SETTINGS_FILE)
    }
    elseif ($env:LOCALAPPDATA) {
        Join-Path $env:LOCALAPPDATA "ReefVision\config\storage.json"
    }
    else {
        Join-Path $HOME ".config\reefvision\storage.json"
    }

    $ConfiguredDataRoot = $null
    $ModelCacheRoot = if ($env:REEFVISION_MODEL_CACHE_DIR) {
        [System.IO.Path]::GetFullPath($env:REEFVISION_MODEL_CACHE_DIR)
    }
    else {
        $null
    }
    if (Test-Path -LiteralPath $SettingsPath -PathType Leaf) {
        try {
            $StorageSettings = Get-Content -LiteralPath $SettingsPath -Raw |
                ConvertFrom-Json
            if (-not $ModelCacheRoot -and $StorageSettings.paths.model_cache_dir) {
                $ModelCacheRoot = [string]$StorageSettings.paths.model_cache_dir
            }
            if ($StorageSettings.paths.data_dir) {
                $ConfiguredDataRoot = [string]$StorageSettings.paths.data_dir
            }
        }
        catch {
            Write-Warning "Could not parse the storage settings file: $SettingsPath"
        }
    }
    if (-not $ConfiguredDataRoot -and $env:REEFVISION_DATA_DIR) {
        $ConfiguredDataRoot = [System.IO.Path]::GetFullPath($env:REEFVISION_DATA_DIR)
    }
    if (-not $ModelCacheRoot) {
        $DataRoot = if ($ConfiguredDataRoot) {
            $ConfiguredDataRoot
        }
        else {
            Join-Path $Root ".reefvision"
        }
        $ModelCacheRoot = Join-Path $DataRoot "model-cache"
    }

    foreach ($RelativeCachePath in @(
        "huggingface",
        "torch",
        "models\catalog-models",
        "models\provider-packs",
        "models\temporary-downloads"
    )) {
        Add-Candidate `
            -Candidates $Candidates `
            -Path (Join-Path $ModelCacheRoot $RelativeCachePath)
    }
}

$UniqueCandidates = @(
    $Candidates |
        Sort-Object { $_.Length } -Descending -Unique
)
$BytesRemoved = [int64]0
foreach ($Path in $UniqueCandidates) {
    if (-not (Test-Path -LiteralPath $Path)) {
        continue
    }
    $Bytes = Get-ReefVisionPathBytes -Path $Path
    $BytesRemoved += $Bytes
    Write-Host (
        "Removing $(Format-ReefVisionBytes -Bytes $Bytes): $Path"
    ) -ForegroundColor Yellow
    Remove-Item -LiteralPath $Path -Recurse -Force
}

$DriveRoot = [System.IO.Path]::GetPathRoot($Root)
$DriveName = $DriveRoot.TrimEnd("\").TrimEnd(":")
$Drive = Get-PSDrive -Name $DriveName
$FreeBytes = [int64]$Drive.Free
Write-Host (
    "Cache cleanup reclaimed approximately " +
    "$(Format-ReefVisionBytes -Bytes $BytesRemoved). " +
    "Current free space: $(Format-ReefVisionBytes -Bytes $FreeBytes)."
) -ForegroundColor Green

Write-Host (
    "Project databases, managed project files, trained models, imported models, " +
    "exports, and backups were preserved."
) -ForegroundColor DarkGray
if (-not $IncludeCompletedTransformerSnapshots) {
    Write-Host (
        "Completed packaged Transformer snapshots were preserved."
    ) -ForegroundColor DarkGray
}
if (-not $IncludeUserModelCaches) {
    Write-Host (
        "Downloadable model caches were preserved. Use -IncludeUserModelCaches " +
        "to remove them; they will need to be restored or downloaded again."
    ) -ForegroundColor DarkGray
}
