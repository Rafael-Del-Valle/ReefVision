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

$ResolvedRepoPath = Resolve-ReefVisionRepoPath -PreferredPath $RepoPath
if ($null -eq $ResolvedRepoPath) {
    $ResolvedRepoPath = Set-ReefVisionRepoPath -RepoPath $Root
}
else {
    $ResolvedRepoPath = Set-ReefVisionRepoPath -RepoPath $ResolvedRepoPath
}

Write-ReefVisionCommandStep "Installing ReefVision command shortcuts"
Write-ReefVisionCommandNote "Repository: $ResolvedRepoPath"

New-ReefVisionCommandDirectoryLayout
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
    }
)

foreach ($asset in $sourceAssets) {
    if (-not (Test-Path $asset.Source -PathType Leaf)) {
        throw "Required command asset is missing from the repository: $($asset.Source)"
    }
    Copy-Item -LiteralPath $asset.Source -Destination $asset.Destination -Force
}

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

$conflicts = @()
foreach ($wrapper in $wrappers) {
    if ((Test-Path $wrapper.Path -PathType Leaf) -and -not $Force -and -not (Test-ReefVisionManagedWrapper -Path $wrapper.Path)) {
        $conflicts += $wrapper.Path
        continue
    }
    Write-ManagedWrapper -WrapperPath $wrapper.Path -ScriptName $wrapper.ScriptName
}

if ($conflicts.Count -gt 0) {
    throw "Existing command wrappers are not ReefVision-managed. Resolve these conflicts or rerun with -Force: $($conflicts -join ', ')"
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
