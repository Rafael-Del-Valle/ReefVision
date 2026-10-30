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
        if ([string]::IsNullOrWhiteSpace($name) -or $name.StartsWith('#')) { continue }
        if ($name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*\.cab
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
) {
            throw "Unsafe MSI Media cabinet name: $name"
        }
        [void]$expected.Add($name)
    }
    if ($expected.Count -eq 0) {
        throw 'MSI Media table declares no external cabinet payloads.'
    }
    $actual = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($name in $AvailableCabinets) {
        if ([string]::IsNullOrWhiteSpace($name) -or $name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*\.cab
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
) {
            throw "Unsafe external cabinet filename: $name"
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
