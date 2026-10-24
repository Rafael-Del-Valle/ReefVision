param(
    [string]$RepoPath,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

. (Join-Path $PSScriptRoot "lib\reefvision-commands.ps1")

function Write-ManagedWrapper {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WrapperPath,
        [Parameter(Mandatory = $true)]
        [string]$ScriptName
    )

    $wrapperContent = @(
        "@rem $script:ReefVisionManagedWrapperMarker v$script:ReefVisionCommandVersion"
        "@echo off"
        "setlocal"
        "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ""%LOCALAPPDATA%\ReefVision\commands\$ScriptName"" %*"
    ) -join [Environment]::NewLine

    Set-Content -LiteralPath $WrapperPath -Value $wrapperContent -Encoding ASCII
}

# Check all predictable conflicts before touching configuration, support files,
# command wrappers, or the user's PATH. -Force only authorizes replacement of
# existing unmanaged wrapper *files*, not directory collisions.
$ResolvedRepoPath = Resolve-ReefVisionRepoPath -PreferredPath $RepoPath
if ($null -eq $ResolvedRepoPath) {
    $ResolvedRepoPath = $Root
}

$binDir = Get-ReefVisionCommandBinDir
$supportDir = Get-ReefVisionCommandSupportDir
$sourceAssets = @(
    @{
        Source = Join-Path $ResolvedRepoPath "scripts\start-reefvision.ps1"
        Destination = Join-Path $supportDir "start-reefvision.ps1"
    },
    @{
        Source = Join-Path $ResolvedRepoPath "scripts\update-reefvision.ps1"
        Destination = Join-Path $supportDir "update-reefvision.ps1"
    },
    @{
        Source = Join-Path $ResolvedRepoPath "scripts\lib\reefvision-commands.ps1"
        Destination = Join-Path $supportDir "reefvision-commands.ps1"
    },
    @{
        Source = Join-Path $ResolvedRepoPath "scripts\lib\reefvision-msi-update.ps1"
        Destination = Join-Path $supportDir "reefvision-msi-update.ps1"
    }
)
$wrappers = @(
    @{
        Path = Join-Path $binDir "start-reefvision.cmd"
        ScriptName = "start-reefvision.ps1"
    },
    @{
        Path = Join-Path $binDir "update-reefvision.cmd"
        ScriptName = "update-reefvision.ps1"
    }
)

$managedDirectories = @(
    (Get-ReefVisionCommandsRoot),
    $binDir,
    $supportDir,
    (Split-Path -Parent (Get-ReefVisionCommandConfigPath)),
    (Get-ReefVisionCommandRuntimeDir)
)
foreach ($directory in $managedDirectories) {
    if (Test-Path -LiteralPath $directory -PathType Leaf) {
        throw "Refusing to replace a file with a ReefVision command directory: $directory"
    }
    # A junction/symlink may redirect writes outside the managed user area.
    $entry = Get-Item -LiteralPath $directory -Force -ErrorAction SilentlyContinue
    if ($null -ne $entry -and
        ($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing to write through a reparse-point command directory: $directory"
    }
}
# Configuration must not be redirected even when its parent is safe.
$configPath = Get-ReefVisionCommandConfigPath
$configEntry = Get-Item -LiteralPath $configPath -Force -ErrorAction SilentlyContinue
if ($null -ne $configEntry -and
    ($configEntry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "Refusing to overwrite a reparse-point command configuration: $configPath"
}
foreach ($asset in $sourceAssets) {
    if (-not (Test-Path -LiteralPath $asset.Source -PathType Leaf)) {
        throw "Required command asset is missing from the repository: $($asset.Source)"
    }
    if (Test-Path -LiteralPath $asset.Destination -PathType Container) {
        throw "Refusing to replace a directory with a ReefVision support script: $($asset.Destination)"
    }
    $destinationEntry = Get-Item -LiteralPath $asset.Destination -Force -ErrorAction SilentlyContinue
    if ($null -ne $destinationEntry -and
        ($destinationEntry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing to overwrite a reparse-point support script: $($asset.Destination)"
    }
}
$conflicts = @()
foreach ($wrapper in $wrappers) {
    if (Test-Path -LiteralPath $wrapper.Path -PathType Container) {
        throw "Refusing to replace a directory with a ReefVision command wrapper: $($wrapper.Path)"
    }
    $wrapperEntry = Get-Item -LiteralPath $wrapper.Path -Force -ErrorAction SilentlyContinue
    if ($null -ne $wrapperEntry -and
        ($wrapperEntry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing to overwrite a reparse-point command wrapper: $($wrapper.Path)"
    }
    if ((Test-Path -LiteralPath $wrapper.Path -PathType Leaf) -and -not $Force -and -not (Test-ReefVisionManagedWrapper -Path $wrapper.Path)) {
        $conflicts += $wrapper.Path
    }
}
if ($conflicts.Count -gt 0) {
    throw "Existing command wrappers are not ReefVision-managed. Resolve these conflicts or rerun with -Force: $($conflicts -join ', ')"
}

$ResolvedRepoPath = Set-ReefVisionRepoPath -RepoPath $ResolvedRepoPath
Write-ReefVisionCommandStep "Installing ReefVision command shortcuts"
Write-ReefVisionCommandNote "Repository: $ResolvedRepoPath"
New-ReefVisionCommandDirectoryLayout
foreach ($asset in $sourceAssets) {
    Copy-Item -LiteralPath $asset.Source -Destination $asset.Destination -Force
}
foreach ($wrapper in $wrappers) {
    Write-ManagedWrapper -WrapperPath $wrapper.Path -ScriptName $wrapper.ScriptName
}

$pathResult = Ensure-ReefVisionBinOnUserPath
$verification = @{
    start_exists = Test-Path (Join-Path $binDir "start-reefvision.cmd") -PathType Leaf
    update_exists = Test-Path (Join-Path $binDir "update-reefvision.cmd") -PathType Leaf
    support_start_exists = Test-Path (Join-Path $supportDir "start-reefvision.ps1") -PathType Leaf
    support_update_exists = Test-Path (Join-Path $supportDir "update-reefvision.ps1") -PathType Leaf
    bin_dir = $binDir
    repo_path = $ResolvedRepoPath
    path_changed = $pathResult.changed
}

$config = Get-ReefVisionCommandConfig
$config.repo_path = $ResolvedRepoPath
Save-ReefVisionCommandConfig -Config $config

Write-ReefVisionCommandNote "Command directory: $binDir"
if ($pathResult.changed) {
    Write-ReefVisionCommandNote "Added ReefVision command directory to the current user's PATH. Open a new terminal to use the commands everywhere."
}
else {
    Write-ReefVisionCommandNote "The ReefVision command directory is already present in the current user's PATH."
}

$verification | ConvertTo-Json -Depth 4
