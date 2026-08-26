param(
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Version = "1.0.0"
$BundleRoot = Join-Path $Root "apps\web\src-tauri\target\$TargetTriple\release\bundle\msi"
$Installer = Join-Path $BundleRoot "ReefVision_${Version}_x64_en-US.msi"
$OutputRoot = Join-Path $Root "release-artifacts"
$ChecksumsPath = Join-Path $OutputRoot "ReefVision_${Version}_windows_x64_SHA256SUMS.txt"
$ManifestPath = Join-Path $OutputRoot "ReefVision_${Version}_windows_x64_manifest.json"

if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
    throw "ReefVision $Version MSI was not found: $Installer"
}

$CabFiles = @(Get-ChildItem -LiteralPath $BundleRoot -Filter "rv*.cab" -File |
    Sort-Object Name)
if ($CabFiles.Count -eq 0) {
    throw "No split ReefVision rv*.cab payload files were found beside the MSI."
}

Write-Host "Re-running packaged MSI/backend verification..."
try {
    & (Join-Path $PSScriptRoot "verify-windows-msi.ps1") `
        -TargetTriple $TargetTriple `
        -InstallerDirectory $BundleRoot
}
catch {
    throw "Windows MSI verification failed: $($_.Exception.Message)"
}

New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

$Files = @((Get-Item -LiteralPath $Installer)) + $CabFiles
$Records = foreach ($File in $Files) {
    $Hash = Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256
    [pscustomobject]@{
        name = $File.Name
        size_bytes = $File.Length
        sha256 = $Hash.Hash.ToLowerInvariant()
    }
}

$ChecksumLines = foreach ($Record in $Records) {
    "$($Record.sha256)  $($Record.name)"
}
Set-Content -LiteralPath $ChecksumsPath -Value $ChecksumLines -Encoding UTF8

$Manifest = [ordered]@{
    product = "ReefVision"
    version = $Version
    platform = "windows"
    architecture = "x64"
    target_triple = $TargetTriple
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    installer = (Split-Path -Leaf $Installer)
    cabinet_count = $CabFiles.Count
    files = @($Records)
}
$Manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ManifestPath -Encoding UTF8

Write-Host ""
Write-Host "ReefVision $Version automated release artifacts finalized." -ForegroundColor Green
Write-Host "MSI:       $Installer"
Write-Host "CAB files: $($CabFiles.Count)"
Write-Host "Checksums: $ChecksumsPath"
Write-Host "Manifest:  $ManifestPath"
