param(
    [ValidateSet("x86_64-pc-windows-msvc", "i686-pc-windows-msvc", "aarch64-pc-windows-msvc")]
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
$SourceScript = Join-Path $PSScriptRoot "relink-tauri-msi.ps1"
$BundleVerificationScript = Join-Path `
    $PSScriptRoot `
    "verify-windows-msi-bundle-short-path.ps1"
$GeneratedScript = Join-Path $PSScriptRoot ".relink-tauri-msi-large-files.generated.ps1"

foreach ($RequiredScript in @($SourceScript, $BundleVerificationScript)) {
    if (-not (Test-Path -LiteralPath $RequiredScript -PathType Leaf)) {
        throw "The required MSI recovery script is missing: $RequiredScript"
    }
}

$SourceText = (Get-Content -LiteralPath $SourceScript -Raw) -replace "`r`n", "`n"
$EnvironmentNeedle = '$env:WIX_MCSLFS = "512"'
$EnvironmentReplacement = '$env:WIX_MCSLFS = "2048"'
$MediaNeedle = 'MaximumCabinetSizeForLargeFileSplitting="512"'
$MediaReplacement = 'MaximumCabinetSizeForLargeFileSplitting="2048"'
$ExternalVerificationNeedle = @'
    & $VerificationScript `
        -MsiPath $FinalInstaller `
        -OutputDirectory $VerificationDirectory
    if (-not $?) {
        throw "The external-cabinet MSI failed ReefVision payload verification."
    }
'@
$ExternalVerificationReplacement = @'
    $BundleVerificationScript = Join-Path `
        $PSScriptRoot `
        "verify-windows-msi-bundle-short-path.ps1"
    & $BundleVerificationScript -MsiPath $FinalInstaller
    if (-not $?) {
        throw "The external-cabinet MSI failed short-path bundle verification."
    }
'@

$EnvironmentMatchCount = [regex]::Matches(
    $SourceText,
    [regex]::Escape($EnvironmentNeedle)
).Count
$MediaMatchCount = [regex]::Matches(
    $SourceText,
    [regex]::Escape($MediaNeedle)
).Count
$VerificationMatchCount = [regex]::Matches(
    $SourceText,
    [regex]::Escape($ExternalVerificationNeedle)
).Count
if (
    $EnvironmentMatchCount -ne 1 -or
    $MediaMatchCount -ne 1 -or
    $VerificationMatchCount -ne 1
) {
    throw (
        "The base relink script no longer has the expected recovery settings. " +
        "Environment matches: $EnvironmentMatchCount; media matches: " +
        "$MediaMatchCount; external verification matches: $VerificationMatchCount."
    )
}

$PatchedText = $SourceText.Replace(
    $EnvironmentNeedle,
    $EnvironmentReplacement
).Replace(
    $MediaNeedle,
    $MediaReplacement
).Replace(
    $ExternalVerificationNeedle,
    $ExternalVerificationReplacement
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
    "ceiling, followed by short-path bundle verification..."
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
