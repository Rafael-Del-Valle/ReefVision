$ErrorActionPreference = 'Stop'
$folder = Join-Path $env:TEMP ('reefvision-rc-payload-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $folder | Out-Null
$verifier = Join-Path $PSScriptRoot 'verify-windows-installer-payload.ps1'
try {
    $msi = Join-Path $folder 'ReefVision_1.1.0_x64_en-US.msi'
    $installer = New-Object -ComObject WindowsInstaller.Installer
    $db = $installer.OpenDatabase($msi, 3)
    foreach ($sql in @(
        'CREATE TABLE `Property` (`Property` CHAR(72) NOT NULL, `Value` CHAR(0) NOT NULL PRIMARY KEY `Property`)',
        'CREATE TABLE `Media` (`DiskId` SHORT NOT NULL, `Cabinet` CHAR(255) PRIMARY KEY `DiskId`)',
        'INSERT INTO `Property` (`Property`, `Value`) VALUES (''ProductVersion'', ''1.1.0'')',
        'INSERT INTO `Property` (`Property`, `Value`) VALUES (''ProductCode'', ''{10B8E995-C822-438D-8E1B-524F6D16B7D7}'')',
        'INSERT INTO `Property` (`Property`, `Value`) VALUES (''UpgradeCode'', ''{20B8E995-C822-438D-8E1B-524F6D16B7D7}'')',
        'INSERT INTO `Media` (`DiskId`, `Cabinet`) VALUES (1, ''#test.cab'')',
        'INSERT INTO `Media` (`DiskId`, `Cabinet`) VALUES (2, ''rv1.cab'')'
    )) {
        $view = $db.OpenView($sql)
        $view.Execute()
        $view.Close()
    }
    $null = [Runtime.InteropServices.Marshal]::FinalReleaseComObject($view)
    $db.Commit()
    $null = [Runtime.InteropServices.Marshal]::FinalReleaseComObject($db)
    $null = [Runtime.InteropServices.Marshal]::FinalReleaseComObject($installer)
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
    Set-Content -LiteralPath (Join-Path $folder 'rv1.cab') -Value 'Synthetic cabinet data'
    $payload = & $verifier -InstallerDirectory $folder -Version '1.1.0'
    if ($payload.media.Count -ne 2 -or -not $payload.media[0].embedded -or $payload.media[1].embedded -or $payload.files.Count -ne 2) {
        throw 'MSI Media or external file inventory does not match the fixture.'
    }
    [ordered]@{
        version = '1.1.0'
        source_commit = '0000000000000000000000000000000000000001'
        source_tree_clean = $true
        msi_verified = $true
        msi = [ordered]@{ identity = $payload.identity; media = $payload.media }
        files = $payload.files
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $folder 'build-provenance.json')
    $null = & $verifier -InstallerDirectory $folder -Version '1.1.0' -SourceCommit '0000000000000000000000000000000000000001' -RequireProvenance
    Set-Content -LiteralPath (Join-Path $folder 'rv1.cab') -Value 'Modified cabinet data'
    try {
        $null = & $verifier -InstallerDirectory $folder -Version '1.1.0' -SourceCommit '0000000000000000000000000000000000000001' -RequireProvenance
        throw 'Unexpected acceptance of a modified cabinet.'
    } catch {
        if ($_.Exception.Message -notmatch 'differ from build provenance') { throw }
    }
    'Fixture passed version, digest, external and embedded cabinet checks.'
} finally {
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
    $tempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
    if (-not [IO.Path]::GetFullPath($folder).StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Fixture directory is outside the temporary directory.'
    }
    Remove-Item -LiteralPath $folder -Recurse -Force
}
