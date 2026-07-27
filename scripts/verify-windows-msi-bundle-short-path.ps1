param(
    [string]$MsiPath,
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
if (-not $MsiPath) {
    $MsiPath = Join-Path `
        $Root `
        "apps\web\src-tauri\target\x86_64-pc-windows-msvc\release\bundle\msi\ReefVision_1.7.0_x64_en-US.msi"
}
$ResolvedMsi = (Resolve-Path -LiteralPath $MsiPath).Path
$SourceBundleDirectory = Split-Path -Parent $ResolvedMsi
$Cabinets = @(
    Get-ChildItem `
        -LiteralPath $SourceBundleDirectory `
        -Filter "rv*.cab" `
        -File `
        -ErrorAction Stop |
        Sort-Object -Property Name
)
if ($Cabinets.Count -eq 0) {
    throw "No external ReefVision cabinet files were found beside $ResolvedMsi"
}

$DriveRoot = [IO.Path]::GetPathRoot($ResolvedMsi)
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$ShortRoot = Join-Path $DriveRoot "rv-msi-verify-$Timestamp"
$ShortBundleDirectory = Join-Path $ShortRoot "b"
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $ShortRoot "o"
}
New-Item -ItemType Directory -Path $ShortBundleDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

function Add-ReefVisionBundleLink {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
    try {
        New-Item -ItemType HardLink -Path $Destination -Target $Source -ErrorAction Stop |
            Out-Null
    }
    catch {
        Write-Warning "Hard-link staging failed for $Source; copying the file instead."
        Copy-Item -LiteralPath $Source -Destination $Destination -Force
    }
}

$StagedMsi = Join-Path $ShortBundleDirectory ([IO.Path]::GetFileName($ResolvedMsi))
Add-ReefVisionBundleLink -Source $ResolvedMsi -Destination $StagedMsi
foreach ($Cabinet in $Cabinets) {
    Add-ReefVisionBundleLink `
        -Source $Cabinet.FullName `
        -Destination (Join-Path $ShortBundleDirectory $Cabinet.Name)
}

Write-Host (
    "Verifying the existing MSI with $($Cabinets.Count) external cabinets from " +
    "the short bundle path $ShortBundleDirectory"
) -ForegroundColor Cyan
$VerificationScript = Join-Path $PSScriptRoot "verify-windows-msi.ps1"
try {
    & $VerificationScript `
        -MsiPath $StagedMsi `
        -OutputDirectory $OutputDirectory
    if (-not $?) {
        throw "MSI bundle verification returned a failing status."
    }
}
catch {
    $InstallLog = Join-Path $OutputDirectory "msiexec-administrative.log"
    if (Test-Path -LiteralPath $InstallLog -PathType Leaf) {
        $LogLines = @(Get-Content -LiteralPath $InstallLog)
        $FailureIndexes = @(
            for ($Index = 0; $Index -lt $LogLines.Count; $Index++) {
                if (
                    $LogLines[$Index] -match "Return value 3" -or
                    $LogLines[$Index] -match "Error 1[0-9]{3}" -or
                    $LogLines[$Index] -match "Error 2[0-9]{3}" -or
                    $LogLines[$Index] -match "Source file not found" -or
                    $LogLines[$Index] -match "cabinet"
                ) {
                    $Index
                }
            }
        )
        if ($FailureIndexes.Count -gt 0) {
            $FocusIndex = $FailureIndexes[-1]
            $StartIndex = [math]::Max(0, $FocusIndex - 35)
            $EndIndex = [math]::Min($LogLines.Count - 1, $FocusIndex + 15)
            Write-Host ""
            Write-Host "Windows Installer failure context:" -ForegroundColor Yellow
            $LogLines[$StartIndex..$EndIndex] |
                ForEach-Object { Write-Host $_ }
        }
        Write-Host "Full Windows Installer log: $InstallLog" -ForegroundColor Yellow
    }
    throw
}

Write-Host "Short-path MSI bundle verification passed." -ForegroundColor Green
Write-Host "Verification evidence: $OutputDirectory" -ForegroundColor Green
Write-Host "Short administrative image: $(Join-Path $OutputDirectory 'administrative-image')" -ForegroundColor Green
