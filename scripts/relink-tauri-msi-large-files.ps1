param(
    [ValidateSet("x86_64-pc-windows-msvc", "i686-pc-windows-msvc", "aarch64-pc-windows-msvc")]
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
$SourceScript = Join-Path $PSScriptRoot "relink-tauri-msi.ps1"
$GeneratedScript = Join-Path $PSScriptRoot ".relink-tauri-msi-large-files.generated.ps1"

if (-not (Test-Path -LiteralPath $SourceScript -PathType Leaf)) {
    throw "The base MSI relink script is missing: $SourceScript"
}

$SourceText = Get-Content -LiteralPath $SourceScript -Raw
$EnvironmentNeedle = '$env:WIX_MCSLFS = "512"'
$EnvironmentReplacement = '$env:WIX_MCSLFS = "2048"'
$MediaNeedle = 'MaximumCabinetSizeForLargeFileSplitting="512"'
$MediaReplacement = 'MaximumCabinetSizeForLargeFileSplitting="2048"'

$EnvironmentMatchCount = [regex]::Matches(
    $SourceText,
    [regex]::Escape($EnvironmentNeedle)
).Count
$MediaMatchCount = [regex]::Matches(
    $SourceText,
    [regex]::Escape($MediaNeedle)
).Count
if ($EnvironmentMatchCount -ne 1 -or $MediaMatchCount -ne 1) {
    throw (
        "The base relink script no longer has the expected 512 MB large-file " +
        "settings. Environment matches: $EnvironmentMatchCount; media matches: " +
        "$MediaMatchCount."
    )
}

$PatchedText = $SourceText.Replace(
    $EnvironmentNeedle,
    $EnvironmentReplacement
).Replace(
    $MediaNeedle,
    $MediaReplacement
)
$Utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText(
    $GeneratedScript,
    $PatchedText,
    $Utf8WithoutBom
)

$CandidateRoots = @(
    (Join-Path $Root ".desktop\bundled-models"),
    (Join-Path $Root ".desktop\bundled-transformers-models"),
    (Join-Path $Root "apps\web\src-tauri\binaries")
)
$CandidateFiles = @(
    foreach ($CandidateRoot in $CandidateRoots) {
        if (Test-Path -LiteralPath $CandidateRoot -PathType Container) {
            Get-ChildItem -LiteralPath $CandidateRoot -Recurse -File -ErrorAction Stop
        }
    }
)
$LargestFile = $CandidateFiles |
    Sort-Object -Property Length -Descending |
    Select-Object -First 1
if ($LargestFile) {
    $LargestFileMiB = [math]::Round($LargestFile.Length / 1MB, 1)
    Write-Host (
        "Largest staged payload file: $LargestFileMiB MiB - " +
        $LargestFile.FullName
    ) -ForegroundColor DarkGray
    if ($LargestFile.Length -ge 2GB) {
        throw (
            "The staged payload contains a file at or above WiX's 2 GB cabinet " +
            "limit: $($LargestFile.FullName)"
        )
    }
}

Write-Host (
    "Relinking with 512 MB ordinary cabinets and a 2048 MB individual-file " +
    "ceiling..."
) -ForegroundColor Cyan
try {
    & $GeneratedScript -TargetTriple $TargetTriple
    if (-not $?) {
        throw "The large-file MSI relink did not complete successfully."
    }
}
finally {
    Remove-Item -LiteralPath $GeneratedScript -Force -ErrorAction SilentlyContinue
}
