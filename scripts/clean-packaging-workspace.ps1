param(
    [ValidateSet("x86_64-pc-windows-msvc", "i686-pc-windows-msvc", "aarch64-pc-windows-msvc")]
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [switch]$RemoveCompletedTransformerSnapshots
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
        return [int64](Get-Item -LiteralPath $Path).Length
    }
    $Measurement = Get-ChildItem -LiteralPath $Path -File -Recurse -Force -ErrorAction SilentlyContinue |
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

$Candidates = [System.Collections.Generic.List[string]]::new()
foreach ($RelativePath in @(
    ".desktop\pyinstaller\$TargetTriple\work",
    ".desktop\pyinstaller\$TargetTriple\dist",
    ".desktop\pyinstaller\$TargetTriple\spec",
    "apps\web\src-tauri\binaries\reefvision-api",
    "apps\web\src-tauri\target\$TargetTriple\release"
)) {
    $Path = Join-Path $Root $RelativePath
    if (Test-Path -LiteralPath $Path) {
        [void]$Candidates.Add($Path)
    }
}

$TransformerRoot = Join-Path $Root ".desktop\bundled-transformers-models"
if (Test-Path -LiteralPath $TransformerRoot -PathType Container) {
    Get-ChildItem -LiteralPath $TransformerRoot -Directory -Recurse -Force |
        Where-Object { $_.Name.EndsWith(".part", [System.StringComparison]::OrdinalIgnoreCase) } |
        ForEach-Object { [void]$Candidates.Add($_.FullName) }
    Get-ChildItem -LiteralPath $TransformerRoot -File -Recurse -Force |
        Where-Object { $_.Name.EndsWith(".part", [System.StringComparison]::OrdinalIgnoreCase) } |
        ForEach-Object { [void]$Candidates.Add($_.FullName) }
    if ($RemoveCompletedTransformerSnapshots) {
        [void]$Candidates.Add($TransformerRoot)
    }
}

$UniqueCandidates = @($Candidates | Sort-Object -Unique)
if ($UniqueCandidates.Count -eq 0) {
    Write-Host "No disposable packaging workspace was found." -ForegroundColor Green
    exit 0
}

$BytesBefore = [int64]0
foreach ($Path in $UniqueCandidates) {
    $Bytes = Get-ReefVisionPathBytes -Path $Path
    $BytesBefore += $Bytes
    Write-Host "Removing $(Format-ReefVisionBytes -Bytes $Bytes): $Path" -ForegroundColor Yellow
    Remove-Item -LiteralPath $Path -Recurse -Force
}

$DriveRoot = [System.IO.Path]::GetPathRoot($Root)
$FreeBytes = [int64](Get-PSDrive -Name $DriveRoot.TrimEnd("\").TrimEnd(":")) .Free
Write-Host (
    "Packaging cleanup reclaimed approximately " +
    "$(Format-ReefVisionBytes -Bytes $BytesBefore). " +
    "Current free space: $(Format-ReefVisionBytes -Bytes $FreeBytes)."
) -ForegroundColor Green

if (-not $RemoveCompletedTransformerSnapshots) {
    Write-Host "Completed Transformers snapshots were preserved." -ForegroundColor DarkGray
}
