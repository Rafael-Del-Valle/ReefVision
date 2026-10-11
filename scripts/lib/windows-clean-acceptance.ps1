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
    $Names = @(@(Get-ChildItem Env: | Where-Object { $_.Name -like 'REEFVISION_*' } | ForEach-Object { $_.Name }) +
        @($Isolated.Keys) + @('PYTHONPATH', 'PYTHONHOME', 'TRANSFORMERS_CACHE')) | Select-Object -Unique
    $Previous = @{}
    foreach ($Name in $Names) {
        $Previous[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process')
        [Environment]::SetEnvironmentVariable($Name, $null, 'Process')
    }
    try {
        foreach ($Name in $Isolated.Keys) { [Environment]::SetEnvironmentVariable($Name, $Isolated[$Name], 'Process') }
        & $Action
    }
    finally {
        foreach ($Name in $Names) { [Environment]::SetEnvironmentVariable($Name, $Previous[$Name], 'Process') }
    }
}

function Resolve-ReefVisionAcceptancePath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Test-ReefVisionPathWithin {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Parent
    )
    $candidate = (Resolve-ReefVisionAcceptancePath $Path) + '\'
    $boundary = (Resolve-ReefVisionAcceptancePath $Parent) + '\'
    return $candidate.StartsWith($boundary, [System.StringComparison]::OrdinalIgnoreCase)
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
