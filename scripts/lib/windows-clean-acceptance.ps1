Set-StrictMode -Version Latest

function ConvertTo-ReefVisionVersionString {
    param([Parameter(Mandatory = $true)][string]$Value)
    # Windows Installer COM may pad StringData values with spaces. Keep the
    # release comparison semantic while discarding transport-only padding.
    return $Value.Trim()
}

function Invoke-ReefVisionIsolatedEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [hashtable]$AdditionalEnvironment = @{},
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    $Isolated = @{
        HF_HOME = (Join-Path $DataRoot 'cache\huggingface')
        HF_HUB_CACHE = (Join-Path $DataRoot 'cache\huggingface\hub')
        HF_ASSETS_CACHE = (Join-Path $DataRoot 'cache\huggingface\assets')
        TORCH_HOME = (Join-Path $DataRoot 'cache\torch')
        YOLO_CONFIG_DIR = (Join-Path $DataRoot 'cache\ultralytics')
        XDG_CACHE_HOME = (Join-Path $DataRoot 'cache')
        HF_HUB_OFFLINE = '1'
        TRANSFORMERS_OFFLINE = '1'
        YOLO_AUTOINSTALL = 'false'
    }
    foreach ($Key in $AdditionalEnvironment.Keys) { $Isolated[$Key] = $AdditionalEnvironment[$Key] }

    # Build a flat, case-insensitive name set. Do not concatenate arrays
    # through a pipeline: a nested collection can cause environment names
    # (notably REEFVISION_CONFIG_DIR) to escape isolation.
    $Names = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($Item in (Get-ChildItem Env:)) {
        if ($Item.Name.StartsWith('REEFVISION_', [System.StringComparison]::OrdinalIgnoreCase)) {
            [void]$Names.Add($Item.Name)
        }
    }
    foreach ($Name in $Isolated.Keys) { [void]$Names.Add([string]$Name) }
    foreach ($Name in @('PYTHONPATH', 'PYTHONHOME', 'TRANSFORMERS_CACHE', 'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', 'WEBVIEW2_PIPE_FOR_SCRIPT_DEBUGGER')) {
        [void]$Names.Add($Name)
    }

    # Change variables through the PowerShell Env: provider, the same view
    # used by the acceptance tests and spawned PowerShell commands.
    $Previous = @{}
    foreach ($Name in $Names) {
        $Previous[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process')
        Remove-Item -LiteralPath ("Env:{0}" -f $Name) -ErrorAction SilentlyContinue
    }
    try {
        foreach ($Name in $Isolated.Keys) {
            Set-Item -LiteralPath ("Env:{0}" -f $Name) -Value ([string]$Isolated[$Name])
        }
        & $Action
    }
    finally {
        foreach ($Name in $Names) {
            if ($null -eq $Previous[$Name]) {
                Remove-Item -LiteralPath ("Env:{0}" -f $Name) -ErrorAction SilentlyContinue
            } else {
                Set-Item -LiteralPath ("Env:{0}" -f $Name) -Value ([string]$Previous[$Name])
            }
        }
    }
}

function Resolve-ReefVisionAcceptancePath {
    param([Parameter(Mandatory = $true)][string]$Path)
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $volumeRoot = [System.IO.Path]::GetPathRoot($fullPath)
    # Preserve C:\ or a UNC share root. Trimming to C: would turn an
    # absolute drive root into a drive-relative path on Windows.
    if ($fullPath -ieq $volumeRoot) { return $fullPath }
    return $fullPath.TrimEnd('\')
}

function Test-ReefVisionPathWithin {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Parent
    )
    $candidate = (Resolve-ReefVisionAcceptancePath $Path).TrimEnd('\') + '\'
    $boundary = (Resolve-ReefVisionAcceptancePath $Parent).TrimEnd('\') + '\'
    return $candidate.StartsWith($boundary, [System.StringComparison]::OrdinalIgnoreCase)
}

# Reject existing junctions/symbolic links anywhere in the acceptance-root
# ancestry. GetFullPath only normalizes lexical segments; it does not resolve
# reparse points, so a seemingly disposable path could redirect into real data.
function Assert-ReefVisionNoReparseAncestors {
    param([Parameter(Mandatory = $true)][string]$Path)
    $current = Resolve-ReefVisionAcceptancePath $Path
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Acceptance root traverses a junction or symbolic link: $current"
            }
        }
        $parent = Split-Path -Parent $current
        if (-not $parent -or $parent -ieq $current) { break }
        $current = $parent
    }
}

function Assert-ReefVisionSafeAcceptanceRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$DefaultDataRoot
    )
    $resolved = Resolve-ReefVisionAcceptancePath $Path
    # A drive root itself is never a safe acceptance directory. Its ordinary
    # descendants, however, can be safe when they do not overlap any of the
    # narrower protected paths below (Windows, Program Files, user data, repo).
    # Rejecting all descendants of C:\ prevented every disposable C:\ test.
    $volumeRoot = Resolve-ReefVisionAcceptancePath ([System.IO.Path]::GetPathRoot($resolved))
    $forbidden = @(
        (Resolve-ReefVisionAcceptancePath $RepositoryRoot),
        (Resolve-ReefVisionAcceptancePath $DefaultDataRoot),
        (Resolve-ReefVisionAcceptancePath $env:windir),
        (Resolve-ReefVisionAcceptancePath $env:ProgramFiles),
        (Resolve-ReefVisionAcceptancePath ${env:ProgramFiles(x86)}),
        (Resolve-ReefVisionAcceptancePath $env:USERPROFILE),
        (Resolve-ReefVisionAcceptancePath ([System.IO.Path]::GetPathRoot($resolved)))
    ) | Select-Object -Unique
    foreach ($item in $forbidden) {
        if ($item -ieq $volumeRoot -and $resolved -ine $volumeRoot) {
            # C:\acceptance is allowed by the volume boundary, but still
            # must pass all other protected-directory exclusions.
            continue
        }
        if ($resolved -ieq $item -or (Test-ReefVisionPathWithin -Path $resolved -Parent $item)) {
            if ($item -ieq (Resolve-ReefVisionAcceptancePath $env:USERPROFILE) -and $resolved -ine $item) {
                continue
            }
            throw "Unsafe acceptance root '$resolved' overlaps protected path '$item'."
        }
    }
    if (Test-ReefVisionPathWithin -Path $DefaultDataRoot -Parent $resolved) {
        throw "Acceptance root may not contain the normal ReefVision data directory: $DefaultDataRoot"
    }
    Assert-ReefVisionNoReparseAncestors -Path $resolved
    return $resolved
}

function Resolve-ReefVisionLineageFile {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ([System.IO.Path]::IsPathRooted($RelativePath)) {
        throw "$Label escapes fixture root."
    }
    $candidate = Resolve-ReefVisionAcceptancePath (Join-Path $Root $RelativePath)
    if (-not (Test-ReefVisionPathWithin -Path $candidate -Parent $Root)) {
        throw "$Label escapes fixture root."
    }
    Assert-ReefVisionNoReparseAncestors -Path $candidate
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "$Label is missing or is not a file."
    }
    return $candidate
}

function Assert-ReefVisionLineageHash {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($ExpectedSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "$Label SHA-256 is not a lowercase hexadecimal digest."
    }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -cne $ExpectedSha256) { throw "$Label SHA-256 mismatch." }
}

function Read-ReefVisionLineageFixture {
    param(
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$ProfileName,
        [Parameter(Mandatory = $true)][string]$VerificationPath
    )
    $manifestFile = (Resolve-Path -LiteralPath $ManifestPath).Path
    $verificationFile = (Resolve-Path -LiteralPath $VerificationPath).Path
    $root = Resolve-ReefVisionAcceptancePath (Split-Path -Parent $manifestFile)
    Assert-ReefVisionNoReparseAncestors -Path $root
    $manifest = Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json
    if ($manifest.schema_version -cne 'reefvision-windows-lineage-fixtures-1' -or
        $manifest.fixture_kind -cne 'synthetic_engineering') {
        throw 'Unsupported Windows lineage fixture manifest.'
    }
    $matches = @($manifest.profiles | Where-Object { $_.name -ceq $ProfileName })
    if ($matches.Count -ne 1) { throw 'Requested lineage profile is missing or duplicated.' }
    $profile = $matches[0]
    $verification = Get-Content -LiteralPath $verificationFile -Raw | ConvertFrom-Json
    if ($verification.status -cne 'verified' -or $verification.profile -cne $ProfileName -or
        $verification.revision -cne $profile.revision -or
        $verification.project_id -cne $profile.project_id) {
        throw 'Independent lineage verification report does not match the selected profile.'
    }
    $manifestRecordIds = @($profile.records | ForEach-Object { [string]$_.id })
    $verifiedRecordIds = @($verification.record_ids | ForEach-Object { [string]$_ })
    if ($manifestRecordIds.Count -ne $verifiedRecordIds.Count -or
        (Compare-Object $manifestRecordIds $verifiedRecordIds)) {
        throw 'Independent lineage verification record IDs do not match the manifest.'
    }
    $database = Resolve-ReefVisionLineageFile -Root $root -RelativePath ([string]$profile.database) -Label 'database path'
    $backup = Resolve-ReefVisionLineageFile -Root $root -RelativePath ([string]$profile.backup) -Label 'backup path'
    Assert-ReefVisionLineageHash -Path $database -ExpectedSha256 ([string]$profile.database_sha256) -Label 'database'
    Assert-ReefVisionLineageHash -Path $backup -ExpectedSha256 ([string]$profile.backup_sha256) -Label 'backup'
    $profileRoot = Resolve-ReefVisionAcceptancePath (Split-Path -Parent $database)
    $sourceFiles = @()
    foreach ($source in @($profile.source_files)) {
        $sourcePath = Resolve-ReefVisionLineageFile -Root $root -RelativePath ([string]$source.path) -Label 'source file path'
        Assert-ReefVisionLineageHash -Path $sourcePath -ExpectedSha256 ([string]$source.sha256) -Label 'source file'
        $managedPath = [System.IO.Path]::GetRelativePath($profileRoot, $sourcePath)
        if ([System.IO.Path]::IsPathRooted($managedPath) -or $managedPath.StartsWith('..')) {
            throw 'Source file is outside the selected profile root.'
        }
        $sourceFiles += [pscustomobject]@{
            source_path = $sourcePath
            managed_path = $managedPath
            sha256 = [string]$source.sha256
        }
    }
    return [pscustomobject]@{
        name = [string]$profile.name
        revision = [string]$profile.revision
        project_id = [string]$profile.project_id
        database = $database
        database_sha256 = [string]$profile.database_sha256
        backup = $backup
        backup_sha256 = [string]$profile.backup_sha256
        records = @($profile.records)
        record_ids = $manifestRecordIds
        source_files = $sourceFiles
        verification_path = $verificationFile
        verification_sha256 = (Get-FileHash -LiteralPath $verificationFile -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Copy-ReefVisionLineageProfile {
    param(
        [Parameter(Mandatory = $true)]$Fixture,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [switch]$UseBackup
    )
    $resolvedRoot = Resolve-ReefVisionAcceptancePath $DataRoot
    $marker = Join-Path $resolvedRoot '.reefvision-clean-install-acceptance'
    if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container) -or
        -not (Test-Path -LiteralPath $marker -PathType Leaf)) {
        throw 'Lineage staging requires a marker-gated isolated data root.'
    }
    Assert-ReefVisionNoReparseAncestors -Path $resolvedRoot
    $databaseTarget = Join-Path $resolvedRoot 'reefvision.db'
    if (Test-Path -LiteralPath $databaseTarget) {
        throw 'Refusing to overwrite an existing lineage database.'
    }
    $databaseSource = if ($UseBackup) { [string]$Fixture.backup } else { [string]$Fixture.database }
    Copy-Item -LiteralPath $databaseSource -Destination $databaseTarget
    $copiedSources = @()
    foreach ($source in @($Fixture.source_files)) {
        $target = Resolve-ReefVisionAcceptancePath (Join-Path $resolvedRoot ([string]$source.managed_path))
        if (-not (Test-ReefVisionPathWithin -Path $target -Parent $resolvedRoot)) {
            throw 'Managed lineage source path escapes the isolated data root.'
        }
        $parent = Split-Path -Parent $target
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
        Copy-Item -LiteralPath ([string]$source.source_path) -Destination $target
        Assert-ReefVisionLineageHash -Path $target -ExpectedSha256 ([string]$source.sha256) -Label 'staged source file'
        $copiedSources += $target
    }
    $expectedDatabaseHash = if ($UseBackup) { [string]$Fixture.backup_sha256 } else { [string]$Fixture.database_sha256 }
    Assert-ReefVisionLineageHash -Path $databaseTarget -ExpectedSha256 $expectedDatabaseHash -Label 'staged database'
    return [pscustomobject]@{database=$databaseTarget;source_files=$copiedSources;used_backup=[bool]$UseBackup}
}

function New-ReefVisionMsiArguments {
    param(
        [ValidateSet('Install', 'Uninstall')][string]$Action,
        [Parameter(Mandatory = $true)][string]$PackageOrProduct,
        [string]$InstallRoot,
        [Parameter(Mandatory = $true)][string]$LogPath
    )
    $operation = if ($Action -eq 'Install') { '/i' } else { '/x' }
    $arguments = @($operation, ('"{0}"' -f $PackageOrProduct), '/qn', '/norestart', '/L*v', ('"{0}"' -f $LogPath))
    if ($Action -eq 'Install' -and $InstallRoot) {
        $arguments += ('INSTALLDIR="{0}"' -f $InstallRoot)
    }
    return $arguments
}

function New-ReefVisionEvidenceResult {
    param([string]$Status = 'NOT RUN', [string]$Detail = '')
    return [ordered]@{ status = $Status; detail = $Detail; timestamp_utc = [DateTime]::UtcNow.ToString('o') }
}

function Write-ReefVisionEvidenceReport {
    param([Parameter(Mandatory = $true)]$Report, [Parameter(Mandatory = $true)][string]$Path)
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $Report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Wait-ReefVisionAcceptanceJob {
    param(
        [Parameter(Mandatory)][string]$Api,
        [Parameter(Mandatory)][guid]$JobId,
        [Parameter(Mandatory)][string]$Operation
    )
    $deadline = [datetime]::UtcNow.AddMinutes(3)
    do {
        $job = Invoke-RestMethod -Uri "$Api/jobs/$JobId" -NoProxy -TimeoutSec 10
        if ($job.status -eq 'succeeded') { return $job }
        if ($job.status -notin @('queued', 'running')) {
            throw "$Operation job $JobId ended as $($job.status): $($job.error_message)"
        }
        Start-Sleep -Milliseconds 250
    } while ([datetime]::UtcNow -lt $deadline)
    throw "$Operation job $JobId did not complete before the acceptance deadline."
}

function New-ReefVisionAcceptanceBackup {
    param([Parameter(Mandatory)][string]$Api)

    # Imports and their background work can finish at different times on the
    # installed predecessor. Its idle-queue conflict guarantees no job was created.
    $deadline = [DateTime]::UtcNow.AddMinutes(3)
    do {
        $response = Invoke-RestMethod -Uri "$Api/backups" -Method Post -ContentType 'application/json' `
            -Body '{"notes":"Disposable pre-upgrade rollback witness"}' -NoProxy -TimeoutSec 10 `
            -SkipHttpErrorCheck -StatusCodeVariable statusCode
        if ($statusCode -eq 201) { return $response }
        $detail = if ($response -and $response.PSObject.Properties['detail']) { [string]$response.detail } else { [string]$response }
        if ($statusCode -ne 409 -or $detail -cne 'Backups require an idle background queue; wait for current jobs to finish first') {
            throw "Pre-upgrade backup request returned HTTP $statusCode. $detail"
        }
        Start-Sleep -Milliseconds 300
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'The installed predecessor still has background work after three minutes. No pre-upgrade backup was created.'
}

function New-ReefVisionAcceptancePreUpgradeRecovery {
    param(
        [Parameter(Mandatory)][string]$Api,
        [Parameter(Mandatory)][string]$DataRoot,
        [Parameter(Mandatory)][string]$InitialRevision
    )
    if ($Api -notmatch '^http://127\.0\.0\.1:[1-9][0-9]{0,4}/api/v1$' -or
        -not (Test-Path -LiteralPath (Join-Path $DataRoot '.reefvision-clean-install-acceptance') -PathType Leaf)) {
        throw 'An acceptance recovery requires a marked disposable profile and its loopback API.'
    }
    Assert-ReefVisionNoReparseAncestors -Path $DataRoot
    $version = Invoke-RestMethod -Uri "$Api/system/version" -NoProxy -TimeoutSec 5
    if ((Resolve-ReefVisionAcceptancePath $version.data_dir) -ine (Resolve-ReefVisionAcceptancePath $DataRoot) -or
        $version.current_schema_revision -ne $InitialRevision -or $version.safe_mode) {
        throw 'The predecessor API does not own the expected disposable pre-upgrade profile.'
    }
    $created = New-ReefVisionAcceptanceBackup -Api $Api
    $backupJob = Wait-ReefVisionAcceptanceJob -Api $Api -JobId $created.job.id -Operation 'Pre-upgrade backup'
    $verify = Invoke-RestMethod -Uri "$Api/backups/$($created.backup.id)/verify" -Method Post -NoProxy -TimeoutSec 60
    if ($verify.status -ne 'valid' -or -not $verify.completion_marker_present -or
        $verify.current_schema_revision -ne $InitialRevision -or $verify.file_count -lt 2) {
        throw 'The predecessor did not verify a complete pre-upgrade backup.'
    }
    $manifestPath = Resolve-ReefVisionLineageFile -Root $DataRoot -RelativePath $created.backup.manifest_path -Label 'Pre-upgrade backup manifest'
    Assert-ReefVisionLineageHash -Path $manifestPath -ExpectedSha256 $backupJob.result_json.manifest_sha256 -Label 'Pre-upgrade backup manifest'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if (@($manifest.file_inventory).Count -ne $verify.file_count -or $manifest.backup_id -cne $created.backup.id) {
        throw 'The pre-upgrade backup manifest does not identify the verified archive.'
    }
    $restore = Invoke-RestMethod -Uri "$Api/backups/$($created.backup.id)/restore" -Method Post -ContentType 'application/json' `
        -Body '{"destination_name":"pre-upgrade-copy","overwrite_existing":false}' -NoProxy -TimeoutSec 60
    if ($restore.verification_status -ne 'valid' -or $restore.destination_path -cne 'recoveries/pre-upgrade-copy') {
        throw 'The predecessor did not schedule an independent verified restore.'
    }
    $restoreJob = Wait-ReefVisionAcceptanceJob -Api $Api -JobId $restore.job.id -Operation 'Pre-upgrade restore'
    if ($restoreJob.result_json.restored_file_count -ne $verify.file_count -or
        $restoreJob.result_json.destination_path -cne $restore.destination_path) {
        throw 'The rollback copy did not publish the full verified backup.'
    }
    $copy = Join-Path $DataRoot $restore.destination_path
    Assert-ReefVisionNoReparseAncestors -Path $copy
    foreach ($entry in $manifest.file_inventory) {
        $relative = if ($entry.path -ceq "database/$($manifest.database_filename)") {
            $manifest.database_filename
        } elseif ($entry.path.StartsWith('data/')) {
            $entry.path.Substring(5)
        } else {
            throw 'A pre-upgrade manifest member could not be mapped to its restored location.'
        }
        $file = Resolve-ReefVisionLineageFile -Root $copy -RelativePath $relative -Label 'Restored pre-upgrade member'
        if ((Get-Item -LiteralPath $file).Length -ne $entry.size_bytes) {
            throw 'A pre-upgrade restored member has a different size.'
        }
        Assert-ReefVisionLineageHash -Path $file -ExpectedSha256 $entry.sha256 -Label 'Restored pre-upgrade member'
    }
    return [pscustomobject]@{
        copy = $copy
        verified_files = $verify.file_count
        manifest_path = $manifestPath
        manifest_sha256 = $backupJob.result_json.manifest_sha256
    }
}

# Decode actual camera bytes rather than accepting a nonempty display response.
# Scientific annotation coordinates remain in the original camera raster frame.
function Assert-ReefVisionCameraRaster {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Bytes,
        [Parameter(Mandatory = $true)][ValidateSet('image/jpeg', 'image/png')][string]$ContentType,
        [Parameter(Mandatory = $true)][int]$ExpectedWidth,
        [Parameter(Mandatory = $true)][int]$ExpectedHeight
    )
    if ($Bytes.Length -eq 0 -or $ExpectedWidth -le 0 -or $ExpectedHeight -le 0) {
        throw 'Camera raster bytes and expected dimensions must be nonempty and positive.'
    }
    Add-Type -AssemblyName System.Drawing
    $stream = [System.IO.MemoryStream]::new([byte[]]$Bytes, $false)
    try {
        $raster = [System.Drawing.Image]::FromStream($stream, $false, $true)
        try {
            $expectedFormat = if ($ContentType -eq 'image/jpeg') {
                [System.Drawing.Imaging.ImageFormat]::Jpeg.Guid
            } else {
                [System.Drawing.Imaging.ImageFormat]::Png.Guid
            }
            if ($raster.RawFormat.Guid -ne $expectedFormat) {
                throw "Camera raster encoding does not match declared $ContentType."
            }
            if ($raster.Width -ne $ExpectedWidth -or $raster.Height -ne $ExpectedHeight) {
                throw "Camera raster dimensions $($raster.Width)x$($raster.Height) differ from original source frame ${ExpectedWidth}x${ExpectedHeight}."
            }
            return [pscustomobject]@{
                width = [int]$raster.Width
                height = [int]$raster.Height
                media_type = $ContentType
            }
        } finally { $raster.Dispose() }
    } finally { $stream.Dispose() }
}


# A camera image must render identically before and after an installed desktop
# restart. Matching dimensions alone would miss changed pixels or re-encoding.
# This deliberately requires byte-for-byte stability of the display response;
# no source camera bytes are modified by this check.
function Assert-ReefVisionStableCameraDisplay {
    param(
        [Parameter(Mandatory = $true)][byte[]]$InitialBytes,
        [Parameter(Mandatory = $true)][byte[]]$RestartBytes,
        [Parameter(Mandatory = $true)][string]$InitialContentType,
        [Parameter(Mandatory = $true)][string]$RestartContentType
    )
    if ($InitialBytes.Length -eq 0 -or $RestartBytes.Length -eq 0) {
        throw 'Camera display bytes must be nonempty before and after restart.'
    }
    if ($InitialContentType -cne $RestartContentType) {
        throw 'Camera display media type changed after desktop restart.'
    }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $before = [BitConverter]::ToString($sha.ComputeHash($InitialBytes)).Replace('-', '')
        $after = [BitConverter]::ToString($sha.ComputeHash($RestartBytes)).Replace('-', '')
    } finally { $sha.Dispose() }
    if ($before -cne $after) {
        throw 'Camera display bytes changed after desktop restart despite matching dimensions.'
    }
}

function Get-ReefVisionInstalledRegistrations {
    $roots = @(
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    return @(Get-ItemProperty $roots -ErrorAction SilentlyContinue | Where-Object {
        $displayName = $_.PSObject.Properties['DisplayName']
        $null -ne $displayName -and $displayName.Value -like 'ReefVision*'
    })
}

function Test-ReefVisionAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
