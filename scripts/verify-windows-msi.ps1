param(
    [string]$TargetTriple = 'x86_64-pc-windows-msvc',
    [string]$InstallerDirectory = '',
    [string]$ExpectedVersion = '',
    [switch]$KeepExtracted
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot 'lib\windows-clean-acceptance.ps1')
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
# A symlinked MSI or CAB (or a junction in its parent path) could redirect
# verification to unrelated files. Reject reparse points before reading either.
Assert-ReefVisionNoReparseAncestors -Path $Msi.FullName
if (-not $ExpectedVersion) {
    $ExpectedVersion = (Get-Content -LiteralPath (Join-Path $RepositoryRoot 'apps\web\src-tauri\tauri.conf.json') -Raw | ConvertFrom-Json).version
}
$MsiDatabase = (New-Object -ComObject WindowsInstaller.Installer).OpenDatabase($Msi.FullName, 0)
$VersionView = $MsiDatabase.OpenView("SELECT ``Value`` FROM ``Property`` WHERE ``Property``='ProductVersion'")
[void]$VersionView.Execute()
$ProductVersion = ConvertTo-ReefVisionVersionString ([string]$VersionView.Fetch().StringData(1))
[void]$VersionView.Close()
if ($ProductVersion -ne $ExpectedVersion) {
    throw "MSI ProductVersion $ProductVersion does not match expected $ExpectedVersion."
}
$CabFiles = @(Get-ChildItem -Path $InstallerDirectory -Filter '*.cab' -File)
foreach ($Cab in $CabFiles) {
    Assert-ReefVisionNoReparseAncestors -Path $Cab.FullName
    if ($Cab.Length -le 0) {
        throw "External cabinet is empty: $($Cab.FullName)"
    }
}

# Validate the MSI's authoritative Media table before invoking msiexec /a.
# A CAB copied from another build can otherwise be mistaken for part of this
# candidate installer; never infer required cabinets from directory contents.
$MediaView = $MsiDatabase.OpenView('SELECT `Cabinet` FROM `Media`')
$DeclaredCabinets = @()
try {
    [void]$MediaView.Execute()
    while ($MediaRecord = $MediaView.Fetch()) {
        $DeclaredCabinets += [string]$MediaRecord.StringData(1)
    }
}
finally {
    [void]$MediaView.Close()
}
$CabinetContract = Assert-ReefVisionMsiCabinetSet `
    -DeclaredCabinets $DeclaredCabinets `
    -AvailableCabinets @($CabFiles | ForEach-Object { $_.Name })
Write-Host "MSI Media table references $($CabinetContract.Count) verified external CABs."


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
    ) -Wait -PassThru -WindowStyle Hidden
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
    $DesktopVersion = $DesktopExe.VersionInfo.ProductVersion
    if ($DesktopVersion -notin @($ExpectedVersion, "$ExpectedVersion.0")) {
        throw "Desktop version $DesktopVersion does not match expected $ExpectedVersion."
    }
    $SidecarExe = @($ExtractedFiles | Where-Object { $_.Name -ieq 'reefvision-api.exe' }) | Select-Object -First 1
    if (-not $SidecarExe) {
        throw 'Extracted MSI does not contain reefvision-api.exe.'
    }
    $ModelCatalog = @($ExtractedFiles | Where-Object { $_.Name -ieq 'model_catalog.json' }) | Select-Object -First 1
    if (-not $ModelCatalog) {
        throw 'Extracted MSI does not contain model_catalog.json.'
    }
    $PydanticCoreBinary = @(
        $ExtractedFiles | Where-Object {
            $_.Name -like '_pydantic_core*.pyd' -and
            $_.FullName -match '[\\/]pydantic_core[\\/]'
        }
    ) | Select-Object -First 1
    if (-not $PydanticCoreBinary) {
        throw 'Extracted MSI does not contain the compiled pydantic_core extension.'
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
    if ($Manifest.model_policy -ne 'architecture_first_no_pretrained_weights' -or
        [int]$Manifest.asset_count -ne 0 -or [int]$Manifest.provider_asset_count -ne 0 -or
        [long]$Manifest.total_size_bytes -ne 0) {
        throw 'Extracted MSI model manifest violates the weight-free release policy.'
    }
    $AuditPython = Join-Path $RepositoryRoot '.venv\Scripts\python.exe'
    $ModelAuditScript = Join-Path $PSScriptRoot 'audit-model-downloadability.py'
    & $AuditPython $ModelAuditScript --catalog $ModelCatalog.FullName --bundle-root $BundledManifest.Directory.FullName --runtime-root $ExtractRoot
    if ($LASTEXITCODE -ne 0) { throw 'Extracted MSI contains prohibited model assets or acquisition catalog paths.' }

    $Longest = $ExtractedFiles | Sort-Object { $_.FullName.Length } -Descending | Select-Object -First 1
    Write-Host "Extracted file count: $($ExtractedFiles.Count)"
    Write-Host "Longest extracted path: $($Longest.FullName.Length) characters"
    Write-Host "  $($Longest.FullName)"
    Write-Host "Desktop executable: $($DesktopExe.FullName)"
    Write-Host "Backend sidecar: $($SidecarExe.FullName)"
    Write-Host "Pydantic Core: $($PydanticCoreBinary.FullName)"
    Write-Host "Migration files: $($MigrationFiles.Count)"
    Write-Host "Bundled model assets: $($Manifest.asset_count)"

    Write-Host 'Running packaged backend self-test...'
    $SidecarProcess = Start-Process -FilePath $SidecarExe.FullName -ArgumentList @(
        '--self-test',
        '--safe-mode',
        '--data-dir', $SelfTestData,
        '--log-file', $SidecarLog
    ) -Wait -PassThru -WindowStyle Hidden
    if ($SidecarProcess.ExitCode -ne 0) {
        Show-Tail -Path $SidecarLog
        throw "Packaged reefvision-api.exe self-test failed with exit code $($SidecarProcess.ExitCode)."
    }
    $SelfTestResultPath = Join-Path $SelfTestData 'self-test-result.json'
    if (-not (Test-Path -LiteralPath $SelfTestResultPath -PathType Leaf)) {
        Show-Tail -Path $SidecarLog
        throw "Packaged API self-test did not produce evidence: $SelfTestResultPath"
    }
    try {
        $SelfTestResult = Get-Content -LiteralPath $SelfTestResultPath -Raw | ConvertFrom-Json
    }
    catch {
        throw "Packaged API self-test evidence is invalid JSON: $SelfTestResultPath"
    }
    if ([string]$SelfTestResult.status -ne 'PASS') {
        throw "Packaged API self-test did not report PASS."
    }
    if ([string]$SelfTestResult.application_version -ne $ExpectedVersion) {
        throw "Packaged API self-test version $($SelfTestResult.application_version) does not match expected $ExpectedVersion."
    }
    if ([int]$SelfTestResult.openapi_path_count -le 0) {
        throw "Packaged API self-test reported no OpenAPI paths."
    }

    $DatabaseFiles = @(Get-ChildItem -Path $SelfTestData -Recurse -File | Where-Object {
        $_.Extension -in @('.db', '.sqlite', '.sqlite3')
    })
    if ($DatabaseFiles.Count -eq 0) {
        throw 'Packaged sidecar self-test did not create a migrated SQLite database.'
    }

    # Fresh startup must not seed a pretrained cache into the test profile.
    & $AuditPython $ModelAuditScript --catalog $ModelCatalog.FullName --runtime-root $SelfTestData
    if ($LASTEXITCODE -ne 0) { throw 'Fresh-profile self-test created prohibited model assets.' }

    Write-Host 'ReefVision Windows MSI verification passed.'
}
finally {
    if (-not $KeepExtracted) {
        foreach ($cleanupPath in @($ExtractRoot, $SelfTestData)) {
            $resolvedCleanupPath = [System.IO.Path]::GetFullPath($cleanupPath)
            if ($resolvedCleanupPath -notin @((Join-Path $SystemDrive "rv1-$Token"), (Join-Path $SystemDrive "rvd-$Token"))) {
                throw "Refusing cleanup outside the generated verification directories: $resolvedCleanupPath"
            }
        }
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $ExtractRoot
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $SelfTestData
    }
}
