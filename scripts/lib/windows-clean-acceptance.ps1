Set-StrictMode -Version Latest

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

# Lexical containment is insufficient on Windows: a junction under an apparently
# disposable path can resolve into an unrelated user's research directory.
# Inspect existing ancestors as well as the requested path before any writes.
function Assert-ReefVisionAcceptanceNoReparseAncestors {
    param([Parameter(Mandatory = $true)][string]$Path)
    $current = [System.IO.Path]::GetFullPath($Path)
    while (-not [string]::IsNullOrWhiteSpace($current)) {
        $entry = Get-Item -LiteralPath $current -Force -ErrorAction SilentlyContinue
        if ($null -ne $entry -and
            ($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Unsafe acceptance path crosses a symlink/junction: $current"
        }
        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) { break }
        $current = $parent
    }
    return $true
}

# Run-root cleanup is allowed only for a tree without linked descendants.
# Never recurse through a reparse point, even if the generated marker exists.
function Assert-ReefVisionAcceptanceTreeNoReparsePoints {
    param([Parameter(Mandatory = $true)][string]$Path)
    [void](Assert-ReefVisionAcceptanceNoReparseAncestors -Path $Path)
    if (Test-Path -LiteralPath $Path -PathType Container) {
        foreach ($entry in (Get-ChildItem -LiteralPath $Path -Force -Recurse -ErrorAction Stop)) {
            if (($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Unsafe acceptance cleanup contains a symlink/junction: $($entry.FullName)"
            }
        }
    }
    return $true
}

function Assert-ReefVisionSafeAcceptanceRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$DefaultDataRoot
    )
    $resolved = Resolve-ReefVisionAcceptancePath $Path
    [void](Assert-ReefVisionAcceptanceNoReparseAncestors -Path $resolved)
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
    return $resolved
}


# An MSI reinstall of the same ProductVersion is not evidence of a version
# upgrade. Windows Installer compares only the three numeric MSI fields.
function Assert-ReefVisionUpgradeVersion {
    param(
        [Parameter(Mandatory = $true)][string]$PreviousVersion,
        [Parameter(Mandatory = $true)][string]$TargetVersion
    )
    foreach ($candidate in @($PreviousVersion, $TargetVersion)) {
        if ($candidate -notmatch '^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,5})$') {
            throw "Invalid MSI ProductVersion '$candidate'; expected major.minor.build."
        }
        $parts = @($candidate.Split('.') | ForEach-Object { [int]$_ })
        if ($parts[0] -gt 255 -or $parts[1] -gt 255 -or $parts[2] -gt 65535) {
            throw "Invalid MSI ProductVersion '$candidate'; numeric component exceeds Windows Installer limits."
        }
    }
    if ([version]$TargetVersion -le [version]$PreviousVersion) {
        throw "Refusing non-upgrade MSI acceptance: target $TargetVersion must exceed previous $PreviousVersion."
    }
    return $true
}

# COM methods may write extra null objects into the PowerShell success
# pipeline. Keep the MSI version a scalar string: arrays corrupt JSON evidence
# and make Windows Installer upgrade comparisons unreliable.
function Assert-ReefVisionMsiVersionScalar {
    param([AllowNull()][object]$Value)
    if ($Value -isnot [string] -or $Value -notmatch '^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,5})

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
        throw 'MSI ProductVersion must be a single major.minor.build string.'
    }
    $parts = @($Value.Split('.') | ForEach-Object { [int]$_ })
    if ($parts[0] -gt 255 -or $parts[1] -gt 255 -or $parts[2] -gt 65535) {
        throw 'MSI ProductVersion exceeds Windows Installer numeric limits.'
    }
    return [string]$Value
}

function Get-ReefVisionMsiProductVersion {
    param([Parameter(Mandatory = $true)][string]$Path)
    $installer = New-Object -ComObject WindowsInstaller.Installer
    $database = $installer.OpenDatabase($Path, 0)
    $view = $database.OpenView("SELECT `Value` FROM `Property` WHERE `Property`='ProductVersion'")
    try {
        [void]$view.Execute()
        $record = $view.Fetch()
        if ($null -eq $record) { throw "MSI has no ProductVersion: $Path" }
        return (Assert-ReefVisionMsiVersionScalar -Value ([string]$record.StringData(1)))
    } finally {
        [void]$view.Close()
    }
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
