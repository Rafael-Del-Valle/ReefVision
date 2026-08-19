param(
    [string]$TargetTriple = 'x86_64-pc-windows-msvc',
    [string]$InstallerDirectory = '',
    [switch]$KeepExtracted
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
if (-not $InstallerDirectory) {
    $InstallerDirectory = Join-Path $RepositoryRoot "apps\web\src-tauri\target\$TargetTriple\release\bundle\msi"
}
$InstallerDirectory = [System.IO.Path]::GetFullPath($InstallerDirectory)
if (-not (Test-Path $InstallerDirectory)) {
    throw "MSI output directory does not exist: $InstallerDirectory"
}

$MsiFiles = @(Get-ChildItem -Path $InstallerDirectory -Filter '*.msi' -File)
if ($MsiFiles.Count -ne 1) {
    throw "Expected exactly one MSI in $InstallerDirectory but found $($MsiFiles.Count)."
}
$Msi = $MsiFiles[0]
$CabFiles = @(Get-ChildItem -Path $InstallerDirectory -Filter '*.cab' -File)
foreach ($Cab in $CabFiles) {
    if ($Cab.Length -le 0) {
        throw "External cabinet is empty: $($Cab.FullName)"
    }
}

$Token = [Guid]::NewGuid().ToString('N').Substring(0, 8)
$SystemDrive = if ($env:SystemDrive) { $env:SystemDrive } else { 'C:' }
$ExtractRoot = Join-Path $SystemDrive "rv1-$Token"
$SelfTestData = Join-Path $SystemDrive "rvd-$Token"
$MsiLog = Join-Path $env:TEMP "reefvision-msi-$Token.log"
$SidecarLog = Join-Path $env:TEMP "reefvision-sidecar-$Token.log"

function Show-Tail {
    param([string]$Path, [int]$Lines = 120)
    if (Test-Path $Path) {
        Write-Host "---- tail: $Path ----"
        Get-Content -Path $Path -Tail $Lines | ForEach-Object { Write-Host $_ }
        Write-Host '---- end tail ----'
    }
}

try {
    New-Item -ItemType Directory -Force -Path $ExtractRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $SelfTestData | Out-Null

    Write-Host "Verifying MSI: $($Msi.FullName)"
    Write-Host "External CAB files: $($CabFiles.Count)"
    if ($CabFiles.Count -gt 0) {
        $CabFiles | Sort-Object Name | ForEach-Object {
            Write-Host "  $($_.Name) ($([Math]::Round($_.Length / 1MB, 2)) MiB)"
        }
    }
    Write-Host "Administrative extraction root: $ExtractRoot"

    $MsiProcess = Start-Process -FilePath 'msiexec.exe' -ArgumentList @(
        '/a',
        $Msi.FullName,
        '/qn',
        "TARGETDIR=$ExtractRoot",
        '/L*v',
        $MsiLog
    ) -Wait -PassThru
    $MsiExitCode = $MsiProcess.ExitCode
    if ($MsiExitCode -notin @(0, 3010)) {
        Show-Tail -Path $MsiLog
        throw "Windows Installer administrative extraction failed with exit code $MsiExitCode."
    }

    $ExtractedFiles = @(Get-ChildItem -Path $ExtractRoot -Recurse -File)
    if ($ExtractedFiles.Count -eq 0) {
        throw 'MSI extraction completed without producing files.'
    }

    $DesktopExe = @($ExtractedFiles | Where-Object { $_.Name -ieq 'ReefVision.exe' }) | Select-Object -First 1
    if (-not $DesktopExe) {
        throw 'Extracted MSI does not contain ReefVision.exe.'
    }
    $SidecarExe = @($ExtractedFiles | Where-Object { $_.Name -ieq 'reefvision-api.exe' }) | Select-Object -First 1
    if (-not $SidecarExe) {
        throw 'Extracted MSI does not contain reefvision-api.exe.'
    }
    $ModelCatalog = @($ExtractedFiles | Where-Object { $_.Name -ieq 'model_catalog.json' }) | Select-Object -First 1
    if (-not $ModelCatalog) {
        throw 'Extracted MSI does not contain model_catalog.json.'
    }
    $AlembicIni = @($ExtractedFiles | Where-Object { $_.Name -ieq 'alembic.ini' }) | Select-Object -First 1
    if (-not $AlembicIni) {
        throw 'Extracted MSI does not contain packaged alembic.ini.'
    }
    $MigrationFiles = @($ExtractedFiles | Where-Object {
        $_.Extension -ieq '.py' -and $_.FullName -match '[\\/]migrations[\\/]versions[\\/]'
    })
    if ($MigrationFiles.Count -eq 0) {
        throw 'Extracted MSI does not contain Alembic migration version files.'
    }
    $BundledManifest = @($ExtractedFiles | Where-Object {
        $_.Name -ieq 'manifest.json' -and $_.FullName -match '[\\/]bundled-models[\\/]'
    }) | Select-Object -First 1
    if (-not $BundledManifest) {
        throw 'Extracted MSI does not contain the bundled-model manifest.'
    }

    $Manifest = Get-Content -Raw -Path $BundledManifest.FullName | ConvertFrom-Json
    if ($null -eq $Manifest.asset_count -or [int]$Manifest.asset_count -le 0) {
        throw "Bundled-model manifest does not report any assets: $($BundledManifest.FullName)"
    }

    $Longest = $ExtractedFiles | Sort-Object { $_.FullName.Length } -Descending | Select-Object -First 1
    Write-Host "Extracted file count: $($ExtractedFiles.Count)"
    Write-Host "Longest extracted path: $($Longest.FullName.Length) characters"
    Write-Host "  $($Longest.FullName)"
    Write-Host "Desktop executable: $($DesktopExe.FullName)"
    Write-Host "Backend sidecar: $($SidecarExe.FullName)"
    Write-Host "Migration files: $($MigrationFiles.Count)"
    Write-Host "Bundled model assets: $($Manifest.asset_count)"

    Write-Host 'Running packaged backend self-test...'
    $SidecarProcess = Start-Process -FilePath $SidecarExe.FullName -ArgumentList @(
        '--self-test',
        '--safe-mode',
        '--data-dir', $SelfTestData,
        '--log-file', $SidecarLog
    ) -Wait -PassThru
    if ($SidecarProcess.ExitCode -ne 0) {
        Show-Tail -Path $SidecarLog
        throw "Packaged reefvision-api.exe self-test failed with exit code $($SidecarProcess.ExitCode)."
    }

    $DatabaseFiles = @(Get-ChildItem -Path $SelfTestData -Recurse -File | Where-Object {
        $_.Extension -in @('.db', '.sqlite', '.sqlite3')
    })
    if ($DatabaseFiles.Count -eq 0) {
        throw 'Packaged sidecar self-test did not create a migrated SQLite database.'
    }

    Write-Host 'ReefVision Windows MSI verification passed.'
}
finally {
    if (-not $KeepExtracted) {
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $ExtractRoot
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $SelfTestData
    }
}
