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
    foreach ($Name in @('PYTHONPATH', 'PYTHONHOME', 'TRANSFORMERS_CACHE')) {
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
    # A path in another user's profile (including Public) is not disposable.
    # The current user's Temp exception must not implicitly authorize sibling
    # profiles or shared directories under C:\Users.
    $profilesRoot = Resolve-ReefVisionAcceptancePath (Split-Path -Parent $env:USERPROFILE)
    if ($resolved -ieq $profilesRoot -or
        (Test-ReefVisionPathWithin -Path $resolved -Parent $profilesRoot)) {
        $localTemp = Resolve-ReefVisionAcceptancePath (Join-Path $env:LOCALAPPDATA 'Temp')
        if ($resolved -ieq $localTemp -or
            -not (Test-ReefVisionPathWithin -Path $resolved -Parent $localTemp)) {
            throw "Unsafe acceptance root '$resolved' overlaps shared or another user's profile directory '$profilesRoot'."
        }
    }
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
                # A disposable acceptance run may live in the Windows local
                # Temp folder, but never in Documents, Desktop, Downloads,
                # Roaming, or arbitrary user-profile directories. The old
                # exception allowed every descendant of USERPROFILE.
                $localTemp = Resolve-ReefVisionAcceptancePath (Join-Path $env:LOCALAPPDATA 'Temp')
                # The Temp directory itself can contain unrelated user files.
                # Only a disposable child directory may be an acceptance root.
                if ($resolved -ine $localTemp -and
                    (Test-ReefVisionPathWithin -Path $resolved -Parent $localTemp)) {
                    continue
                }
            }
            throw "Unsafe acceptance root '$resolved' overlaps protected path '$item'."
        }
    }
    # An acceptance root that *contains* a protected directory is just as
    # dangerous as one inside it: C:\Users, for example, could overwrite or
    # remove multiple user profiles even though it is outside USERPROFILE.
    # The drive root is already rejected above; do not exempt other ancestors.
    foreach ($item in $forbidden) {
        if ($item -ine $volumeRoot -and
            (Test-ReefVisionPathWithin -Path $item -Parent $resolved)) {
            throw "Unsafe acceptance root '$resolved' contains protected path '$item'."
        }
    }
    if (Test-ReefVisionPathWithin -Path $DefaultDataRoot -Parent $resolved) {
        throw "Acceptance root may not contain the normal ReefVision data directory: $DefaultDataRoot"
    }
    Assert-ReefVisionNoReparseAncestors -Path $resolved
    return $resolved
}

# A successful uninstall is not permission to delete an arbitrary path.
# Require the generated run name, the original marker token, and a fresh
# reparse-point check immediately before recursive cleanup. This also
# rejects a junction or symlink introduced after initial root validation.
function Assert-ReefVisionOwnedAcceptanceRun {
    param(
        [Parameter(Mandatory = $true)][string]$RunRoot,
        [Parameter(Mandatory = $true)][string]$AcceptanceRoot,
        [Parameter(Mandatory = $true)][string]$Token
    )
    if ($Token -cnotmatch '^[a-f0-9]{12}$') {
        throw 'Invalid disposable acceptance run token.'
    }
    $expected = Resolve-ReefVisionAcceptancePath (Join-Path $AcceptanceRoot "reefvision-clean-$Token")
    $actual = Resolve-ReefVisionAcceptancePath $RunRoot
    if ($actual -cne $expected) {
        throw 'Refusing cleanup outside the generated acceptance run.'
    }
    $marker = Join-Path $actual '.reefvision-acceptance-run'
    Assert-ReefVisionNoReparseAncestors -Path $marker
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
        throw 'Refusing cleanup without the acceptance run ownership marker.'
    }
    $lines = @(Get-Content -LiteralPath $marker -ErrorAction Stop)
    if ($lines.Count -ne 1 -or $lines[0] -cne $Token) {
        throw 'Refusing cleanup: acceptance run ownership token mismatch.'
    }
    # The ownership marker and parent ancestry are not sufficient: a junction
    # introduced *inside* the run could redirect recursive cleanup into real
    # user data. Enumerate without following links, and fail closed on every
    # reparse point (files and directories) before Remove-Item -Recurse.
    $pending = [System.Collections.Generic.Stack[string]]::new()
    $pending.Push($actual)
    while ($pending.Count -gt 0) {
        $directory = $pending.Pop()
        foreach ($child in @(Get-ChildItem -LiteralPath $directory -Force -ErrorAction Stop)) {
            if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing cleanup: disposable acceptance run contains a junction or symbolic link: $($child.FullName)"
            }
            if ($child.PSIsContainer) { $pending.Push($child.FullName) }
        }
    }
}

# Administrative MSI extraction and packaged-backend self-tests use two
# disposable directories. Unlike a lexical path check, an ownership marker
# plus a fresh recursive reparse scan prevents cleanup from following a
# substituted junction or deleting an unrelated directory after a collision.
function Assert-ReefVisionOwnedMsiVerificationRun {
    param(
        [Parameter(Mandatory = $true)][string]$RunRoot,
        [Parameter(Mandatory = $true)][string]$ParentRoot,
        [Parameter(Mandatory = $true)][ValidateSet('rv1', 'rvd')][string]$Kind,
        [Parameter(Mandatory = $true)][string]$Token
    )
    if ($Token -cnotmatch '^[a-f0-9]{8}$') {
        throw 'Invalid MSI verification ownership token.'
    }
    $expected = Resolve-ReefVisionAcceptancePath (Join-Path $ParentRoot "${Kind}-$Token")
    $actual = Resolve-ReefVisionAcceptancePath $RunRoot
    if ($actual -cne $expected) {
        throw 'Refusing MSI verification cleanup outside the generated directory.'
    }
    $marker = Join-Path $actual '.reefvision-msi-verification-run'
    Assert-ReefVisionNoReparseAncestors -Path $marker
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
        throw 'Refusing MSI verification cleanup without its ownership marker.'
    }
    $lines = @(Get-Content -LiteralPath $marker -ErrorAction Stop)
    if ($lines.Count -ne 1 -or $lines[0] -cne "${Kind}:$Token") {
        throw 'Refusing MSI verification cleanup: ownership marker mismatch.'
    }
    $pending = [System.Collections.Generic.Stack[string]]::new()
    $pending.Push($actual)
    while ($pending.Count -gt 0) {
        $directory = $pending.Pop()
        foreach ($child in @(Get-ChildItem -LiteralPath $directory -Force -ErrorAction Stop)) {
            if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing MSI verification cleanup: nested junction or symbolic link: $($child.FullName)"
            }
            if ($child.PSIsContainer) { $pending.Push($child.FullName) }
        }
    }
}

# An MSI with duplicate critical payloads is ambiguous even when one copy
# passes a version or model-policy check. Never silently select the first one.
# An absent manifest field must not be silently cast to numeric zero. Counts
# are JSON integer fields, not strings, booleans, nulls, or fractional values.
# This is a release-policy gate: no pretrained/provider assets are packaged.
function Assert-ReefVisionWeightFreeManifest {
    param([Parameter(Mandatory = $true)]$Manifest)
    if ($null -eq $Manifest -or $Manifest -isnot [pscustomobject]) {
        throw 'Bundled-model manifest must be a JSON object.'
    }
    $policy = @($Manifest.PSObject.Properties | Where-Object { $_.Name -ceq 'model_policy' })
    if ($policy.Count -ne 1 -or $policy[0].Value -cne 'architecture_first_no_pretrained_weights') {
        throw 'Bundled-model manifest has a missing or invalid model policy.'
    }
    foreach ($name in @('asset_count', 'provider_asset_count', 'total_size_bytes')) {
        $field = @($Manifest.PSObject.Properties | Where-Object { $_.Name -ceq $name })
        if ($field.Count -ne 1) {
            throw "Bundled-model manifest is missing required integer field: $name"
        }
        $value = $field[0].Value
        if (($value -isnot [int] -and $value -isnot [long]) -or $value -ne 0) {
            throw "Bundled-model manifest field $name must be the integer zero."
        }
    }
}

function Get-ReefVisionUniquePackagedFile {
    param(
        [AllowEmptyCollection()][object[]]$Candidates = @(),
        [Parameter(Mandatory = $true)][string]$Description
    )
    if ([string]::IsNullOrWhiteSpace($Description)) {
        throw 'Packaged file description must not be empty.'
    }
    $found = @($Candidates | Where-Object { $null -ne $_ })
    if ($found.Count -ne 1) {
        throw "Expected exactly one $Description in extracted MSI; found $($found.Count)."
    }
    return $found[0]
}

function New-ReefVisionMsiArguments {
    param(
        [Parameter(Mandatory = $true)][ValidateSet('Install', 'Uninstall')][string]$Action,
        [Parameter(Mandatory = $true)][string]$PackageOrProduct,
        [string]$InstallRoot,
        [Parameter(Mandatory = $true)][string]$LogPath
    )
    # Start-Process joins ArgumentList into one command line. Embedded quotes
    # or newlines could escape an argument and alter the msiexec operation.
    foreach ($value in @($PackageOrProduct, $LogPath)) {
        if ([string]::IsNullOrWhiteSpace($value) -or $value -match '[\r\n"]' -or $value -match '[\\/]$') {
            throw 'MSI package/product and log arguments must be nonempty and cannot contain quotes, newlines, or trailing separators.'
        }
    }
    if ($Action -eq 'Install') {
        # Acceptance installs must never silently fall back to the real
        # default installation directory if the disposable root is omitted.
        if ([string]::IsNullOrWhiteSpace($InstallRoot) -or $InstallRoot -match '[\r\n"]' -or $InstallRoot -match '[\\/]$') {
            throw 'MSI acceptance installation requires a safe, nonempty INSTALLDIR without quotes, newlines, or trailing separators.'
        }
    } elseif (-not [string]::IsNullOrWhiteSpace($InstallRoot)) {
        throw 'MSI uninstall must not supply INSTALLDIR.'
    }
    $operation = if ($Action -eq 'Install') { '/i' } else { '/x' }
    $arguments = @($operation, ('"{0}"' -f $PackageOrProduct), '/qn', '/norestart', '/L*v', ('"{0}"' -f $LogPath))
    if ($Action -eq 'Install') {
        $arguments += ('INSTALLDIR="{0}"' -f $InstallRoot)
    }
    return $arguments
}


# Start-Process joins ArgumentList elements into a single Windows command line.
# Quote paths explicitly so MSI/CAB acceptance works from folders with spaces,
# including user profiles, without changing the installed product or its data.
# Windows Installer exit code 3010 means a reboot is required, not that a
# disposable clean-install acceptance has completed. Never report PASS when
# binaries, registry state, or file removals may still be pending a reboot.
function Assert-ReefVisionMsiCompletedWithoutReboot {
    param(
        [Parameter(Mandatory = $true)][ValidateSet('Install', 'Uninstall', 'Extract')][string]$Action,
        [Parameter(Mandatory = $true)][int]$ExitCode,
        [Parameter(Mandatory = $true)][string]$LogPath
    )
    if ($ExitCode -eq 0) { return }
    if ($ExitCode -in @(3010, 1641)) {
        throw "msiexec $Action requires a Windows reboot (exit code $ExitCode); acceptance cannot be marked PASS before reboot. Review $LogPath and rerun on a fresh disposable machine."
    }
    throw "msiexec $Action failed with exit code $ExitCode. See $LogPath"
}

function New-ReefVisionMsiAdministrativeArguments {
    param(
        [Parameter(Mandatory = $true)][string]$PackagePath,
        [Parameter(Mandatory = $true)][string]$ExtractRoot,
        [Parameter(Mandatory = $true)][string]$LogPath
    )
    foreach ($value in @($PackagePath, $ExtractRoot, $LogPath)) {
        if ([string]::IsNullOrWhiteSpace($value) -or $value -match '[\r\n"]' -or $value -match '[\\/]$') {
            throw 'MSI administrative extraction paths must be nonempty and cannot contain quotes, newlines, or trailing separators.'
        }
    }
    return @(
        '/a',
        ('"{0}"' -f $PackagePath),
        '/qn',
        ('TARGETDIR="{0}"' -f $ExtractRoot),
        '/L*v',
        ('"{0}"' -f $LogPath)
    )
}

# Validate the MSI Media table against the adjacent external CAB payload before
# administrative extraction. An unexpected CAB is as unsafe as a missing one:
# both indicate an incomplete or mixed installer artifact set.
function Assert-ReefVisionMsiCabinetSet {
    param(
        [string[]]$DeclaredCabinets = @(),
        [string[]]$AvailableCabinets = @()
    )
    $expected = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($name in $DeclaredCabinets) {
        # Empty Cabinet cells are permitted for uncompressed Media rows.
        if ([string]::IsNullOrWhiteSpace($name)) { continue }
        if ($name.StartsWith('#')) {
            # Embedded cabinets belong to the MSI itself, but malformed names
            # must not bypass the Media-table integrity check.
            if ($name -notmatch '^#[A-Za-z0-9][A-Za-z0-9._-]*$') {
                throw "Unsafe embedded MSI cabinet name: $name"
            }
            continue
        }
        if ($name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*\.cab$') {
            throw "Unsafe MSI Media cabinet name: $name"
        }
        # Windows reserves DOS device basenames even when an extension is present.
        if ($name -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])\.cab$') {
            throw "Reserved Windows device name in MSI Media cabinet: $name"
        }
        if (-not $expected.Add($name)) {
            throw "Duplicate MSI Media cabinet declaration: $name"
        }
    }
    if ($expected.Count -eq 0) {
        throw 'MSI Media table declares no external cabinet payloads.'
    }
    $actual = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($name in $AvailableCabinets) {
        if ([string]::IsNullOrWhiteSpace($name) -or $name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*\.cab$') {
            throw "Unsafe external cabinet filename: $name"
        }
        if ($name -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])\.cab$') {
            throw "Reserved Windows device name in external cabinet: $name"
        }
        if (-not $actual.Add($name)) {
            throw "Duplicate external cabinet filename: $name"
        }
    }
    $missing = @($expected | Where-Object { -not $actual.Contains($_) } | Sort-Object)
    $unexpected = @($actual | Where-Object { -not $expected.Contains($_) } | Sort-Object)
    if ($missing.Count -gt 0 -or $unexpected.Count -gt 0) {
        throw "MSI/CAB mismatch; missing: $($missing -join ', '); unexpected: $($unexpected -join ', ')."
    }
    return [pscustomobject]@{ Count = $expected.Count; Names = @($expected | Sort-Object) }
}

# An automated MSI smoke test is not release acceptance if required evidence
# was skipped. In particular, a successful API probe does not establish real
# camera compatibility, an upgrade, or a complete uninstall.
function Get-ReefVisionAutomatedAcceptanceGaps {
    param([Parameter(Mandatory = $true)]$Report)
    $required = @(
        'install', 'shortcuts', 'first_launch', 'frontend_backend_connectivity',
        'model_policy', 'external_annotation_imports', 'camera_jpeg',
        'project_persistence', 'restart', 'project_exchange',
        'upgrade', 'uninstall', 'data_retention'
    )
    foreach ($name in $required) {
        # Reports are written as ordered dictionaries but are commonly
        # inspected after ConvertFrom-Json, which yields PSCustomObject.
        # Validate both representations without trusting malformed entries.
        $entry = if ($Report -is [System.Collections.IDictionary]) {
            $Report[$name]
        } else {
            $property = $Report.PSObject.Properties[$name]
            if ($null -ne $property) { $property.Value } else { $null }
        }
        if ($null -eq $entry) {
            "$($name): MISSING"
            continue
        }
        $fields = @{}
        foreach ($field in @('status', 'detail', 'timestamp_utc')) {
            if ($entry -is [System.Collections.IDictionary]) {
                $fields[$field] = $entry[$field]
            } else {
                $property = $entry.PSObject.Properties[$field]
                $fields[$field] = if ($null -ne $property) { $property.Value } else { $null }
            }
        }
        $status = [string]$fields.status
        if ($status -cne 'PASS') {
            "$($name): $status"
            continue
        }
        # A bare PASS without a recorded observation or timestamp is not
        # reproducible installer evidence, even if every gate is named.
        if ([string]::IsNullOrWhiteSpace([string]$fields.detail)) {
            "$($name): MISSING DETAIL"
        }
        # ConvertFrom-Json may materialize ISO-8601 timestamps as DateTime
        # instead of preserving their original text. Casting that value to
        # [string] uses the machine's locale and incorrectly rejects valid
        # persisted UTC evidence. Accept only explicitly UTC typed values;
        # Local/Unspecified DateTime cannot prove the original UTC offset.
        $rawTimestamp = $fields.timestamp_utc
        $timestamp = if ($rawTimestamp -is [DateTime]) {
            if ($rawTimestamp.Kind -eq [DateTimeKind]::Utc) { $rawTimestamp.ToString('o') } else { '' }
        } elseif ($rawTimestamp -is [DateTimeOffset]) {
            $rawTimestamp.ToString('o')
        } else {
            [string]$rawTimestamp
        }
        $parsedTimestamp = [DateTimeOffset]::MinValue
        # New-ReefVisionEvidenceResult writes DateTime.UtcNow.ToString('o')
        # (ending in Z). Also accept DateTimeOffset's canonical +00:00,
        # but never accept local, offsetless, or non-UTC timestamps as UTC
        # acceptance provenance. The exact shape check prevents permissive
        # culture-dependent date parsing from weakening this evidence gate.
        $canonicalUtc = $timestamp -cmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{7}(?:Z|\+00:00)$'
        if (-not $canonicalUtc -or -not [DateTimeOffset]::TryParse(
            $timestamp, [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::AssumeUniversal, [ref]$parsedTimestamp
        ) -or $parsedTimestamp.Offset -ne [TimeSpan]::Zero) {
            "$($name): INVALID TIMESTAMP"
        }
    }
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
