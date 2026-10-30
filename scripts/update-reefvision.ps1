param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = "Stop"

$helperPath = Join-Path $PSScriptRoot "reefvision-commands.ps1"
if (-not (Test-Path $helperPath -PathType Leaf)) {
    $helperPath = Join-Path $PSScriptRoot "lib\reefvision-commands.ps1"
}
. $helperPath
$msiHelperPath = Join-Path $PSScriptRoot "reefvision-msi-update.ps1"
if (-not (Test-Path -LiteralPath $msiHelperPath -PathType Leaf)) {
    $msiHelperPath = Join-Path $PSScriptRoot "lib\reefvision-msi-update.ps1"
}
if (-not (Test-Path -LiteralPath $msiHelperPath -PathType Leaf)) {
    throw "Missing ReefVision MSI update helper. Reinstall the managed command shortcuts."
}
. $msiHelperPath

$Arguments = @($Arguments | Where-Object {
    $null -ne $_ -and -not [string]::IsNullOrWhiteSpace([string]$_)
})

function Show-UpdateReefVisionHelp {
    @"
update-reefvision v$script:ReefVisionCommandVersion

Usage:
  update-reefvision
  update-reefvision --help
  update-reefvision --status
  update-reefvision --configure-repo PATH
  update-reefvision --setup
  update-reefvision --skip-setup
  update-reefvision --build-only
  update-reefvision --install-only
  update-reefvision --no-launch
  update-reefvision --clean-build
  update-reefvision --verbose
  update-reefvision --dry-run
  update-reefvision --test
"@
}

function Get-UpdateDependencyFiles {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoPath
    )

    @(
        (Join-Path $RepoPath "pyproject.toml"),
        (Join-Path $RepoPath "apps\web\package.json"),
        (Join-Path $RepoPath "apps\web\package-lock.json"),
        (Join-Path $RepoPath "apps\web\src-tauri\Cargo.toml"),
        (Join-Path $RepoPath "apps\web\src-tauri\tauri.conf.json"),
        (Join-Path $RepoPath "requirements\providers-windows-cu121-py312.txt")
    ) | Where-Object { Test-Path $_ -PathType Leaf }
}

function Get-UpdateDependencySignature {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoPath
    )

    $parts = @(foreach ($file in (Get-UpdateDependencyFiles -RepoPath $RepoPath)) {
        $hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
        $relative = $file.Substring($RepoPath.Length).TrimStart("\", "/")
        "$relative=$hash"
    })
    if ($parts.Count -eq 0) {
        return $null
    }
    $payload = ($parts | Sort-Object) -join "`n"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
    $stream = New-Object System.IO.MemoryStream(, $bytes)
    try {
        return (Get-FileHash -InputStream $stream -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    finally {
        $stream.Dispose()
    }
}

function Get-ReefVisionVersionSources {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoPath
    )

    $pyproject = Get-Content -LiteralPath (Join-Path $RepoPath "pyproject.toml") -Raw
    $pyprojectVersion = ([regex]::Match($pyproject, 'version\s*=\s*"([^"]+)"')).Groups[1].Value

    $packageVersion = (Get-Content -LiteralPath (Join-Path $RepoPath "apps\web\package.json") -Raw | ConvertFrom-Json).version
    $tauriVersion = (Get-Content -LiteralPath (Join-Path $RepoPath "apps\web\src-tauri\tauri.conf.json") -Raw | ConvertFrom-Json).version
    $cargo = Get-Content -LiteralPath (Join-Path $RepoPath "apps\web\src-tauri\Cargo.toml") -Raw
    $cargoVersion = ([regex]::Match($cargo, 'version\s*=\s*"([^"]+)"')).Groups[1].Value
    $apiInit = Get-Content -LiteralPath (Join-Path $RepoPath "apps\api\reefvision\__init__.py") -Raw
    $apiVersion = ([regex]::Match($apiInit, '__version__\s*=\s*"([^"]+)"')).Groups[1].Value

    return [ordered]@{
        pyproject = $pyprojectVersion
        web_package = $packageVersion
        tauri = $tauriVersion
        cargo = $cargoVersion
        api = $apiVersion
    }
}

function Assert-ReefVisionVersionConsistency {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoPath
    )

    $versions = Get-ReefVisionVersionSources -RepoPath $RepoPath
    $distinct = @($versions.Values | Select-Object -Unique)
    if ($distinct.Count -ne 1) {
        throw "ReefVision version metadata is inconsistent: $($versions | ConvertTo-Json -Compress)"
    }
    return $distinct[0]
}

function Get-ReefVisionNsisDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoPath
    )

    return Join-Path $RepoPath "apps\web\src-tauri\target\x86_64-pc-windows-msvc\release\bundle\nsis"
}

function Get-ReefVisionLatestInstaller {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoPath,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedVersion
    )

    $nsisDir = Get-ReefVisionNsisDirectory -RepoPath $RepoPath
    if (-not (Test-Path $nsisDir -PathType Container)) {
        return $null
    }

    return Get-ChildItem -Path $nsisDir -Filter "ReefVision_${ExpectedVersion}_*-setup.exe" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
}

function Get-ReefVisionFreshInstaller {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoPath,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedVersion,
        [Parameter(Mandatory = $true)]
        [datetime]$BuildStartedAtUtc
    )

    $candidate = Get-ReefVisionLatestInstaller -RepoPath $RepoPath -ExpectedVersion $ExpectedVersion
    if ($null -eq $candidate) {
        return $null
    }
    if ($candidate.LastWriteTimeUtc -lt $BuildStartedAtUtc) {
        return $null
    }
    return $candidate
}

function Get-ReefVisionReleaseArtifacts {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoPath,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedVersion
    )

    $releaseDir = Join-Path $RepoPath "apps\web\src-tauri\target\x86_64-pc-windows-msvc\release"
    $desktopExecutablePath = Join-Path $releaseDir "reefvision-desktop.exe"
    $backendDirectory = Join-Path $RepoPath "apps\web\src-tauri\binaries"
    $apiExecutablePath = Join-Path $backendDirectory "reefvision-api\reefvision-api.exe"
    foreach ($path in @($desktopExecutablePath, $apiExecutablePath)) {
        if (-not (Test-Path $path -PathType Leaf)) {
            throw "Expected release artifact is missing: $path"
        }
    }
    if (-not (Test-Path $backendDirectory -PathType Container)) {
        throw "Expected packaged backend resource directory is missing: $backendDirectory"
    }

    $desktopVersion = Get-ReefVisionExecutableVersion -ExecutablePath $desktopExecutablePath
    if ($desktopVersion -ne $ExpectedVersion) {
        throw "The built ReefVision desktop executable version is '$desktopVersion', expected '$ExpectedVersion'."
    }

    return [pscustomobject]@{
        release_dir = $releaseDir
        desktop_executable = $desktopExecutablePath
        api_executable = $apiExecutablePath
        backend_directory = $backendDirectory
        desktop_version = $desktopVersion
    }
}

function Get-ReefVisionCurrentUserRegistrationPaths {
    @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ReefVision",
        "HKCU:\Software\reefvision\ReefVision"
    )
}

function Test-ReefVisionCurrentUserInstallRegistration {
    foreach ($path in Get-ReefVisionCurrentUserRegistrationPaths) {
        if (Test-Path $path) {
            return $true
        }
    }
    return $false
}

function Resolve-ReefVisionPortableInstallDirectory {
    param(
        [string]$PreferredExecutablePath
    )

    $resolved = Resolve-ReefVisionInstalledDirectory -PreferredExecutablePath $PreferredExecutablePath
    if ($resolved) {
        return $resolved
    }
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        return $null
    }
    return Join-Path $env:LOCALAPPDATA "ReefVision"
}

function Test-ReefVisionInstalledBackendBundle {
    param(
        [string]$InstallDirectory
    )

    if ([string]::IsNullOrWhiteSpace($InstallDirectory)) {
        return $false
    }
    return Test-Path (Join-Path $InstallDirectory "backend\reefvision-api\reefvision-api.exe") -PathType Leaf
}

function Sync-ReefVisionPortableInstall {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoPath,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedVersion,
        [Parameter(Mandatory = $true)]
        [string]$InstallDirectory
    )

    $artifacts = Get-ReefVisionReleaseArtifacts -RepoPath $RepoPath -ExpectedVersion $ExpectedVersion
    $normalizedInstallDirectory = [System.IO.Path]::GetFullPath($InstallDirectory).TrimEnd("\")
    $allowedRoots = @(
        (Join-Path $env:LOCALAPPDATA "ReefVision"),
        (Join-Path $env:LOCALAPPDATA "Programs\ReefVision")
    ) |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        ForEach-Object { [System.IO.Path]::GetFullPath($_).TrimEnd("\") }

    $allowed = $false
    foreach ($root in $allowedRoots) {
        if ($normalizedInstallDirectory -eq $root) {
            $allowed = $true
            break
        }
    }
    if (-not $allowed) {
        throw "Refusing to repair a portable ReefVision install outside the approved user locations: $normalizedInstallDirectory"
    }

    New-Item -ItemType Directory -Path $normalizedInstallDirectory -Force | Out-Null
    $desktopTarget = Join-Path $normalizedInstallDirectory "reefvision-desktop.exe"
    $apiTarget = Join-Path $normalizedInstallDirectory "reefvision-api.exe"
    $backendTarget = Join-Path $normalizedInstallDirectory "backend"

    Copy-Item -LiteralPath $artifacts.desktop_executable -Destination $desktopTarget -Force
    Copy-Item -LiteralPath $artifacts.api_executable -Destination $apiTarget -Force
    if (Test-Path $backendTarget -PathType Container) {
        Get-ChildItem -LiteralPath $backendTarget -Force | Remove-Item -Recurse -Force
    }
    else {
        New-Item -ItemType Directory -Path $backendTarget -Force | Out-Null
    }
    Get-ChildItem -LiteralPath $artifacts.backend_directory -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $backendTarget -Recurse -Force
    }

    $installedVersion = Get-ReefVisionExecutableVersion -ExecutablePath $desktopTarget
    if ($installedVersion -ne $ExpectedVersion) {
        throw "The repaired ReefVision desktop executable version is '$installedVersion', expected '$ExpectedVersion'."
    }
    if (-not (Test-ReefVisionInstalledBackendBundle -InstallDirectory $normalizedInstallDirectory)) {
        throw "The packaged ReefVision backend bundle is still missing after the repair step: $(Join-Path $normalizedInstallDirectory 'backend\reefvision-api\reefvision-api.exe')"
    }

    Set-ReefVisionInstalledDesktopPath -ExecutablePath $desktopTarget
    return [pscustomobject]@{
        install_directory = $normalizedInstallDirectory
        desktop_executable = $desktopTarget
        api_executable = $apiTarget
        backend_directory = $backendTarget
        installed_version = $installedVersion
    }
}

$showHelp = $false
$showStatus = $false
$runSetup = $false
$skipSetup = $false
$buildOnly = $false
$installOnly = $false
$noLaunch = $false
$cleanBuild = $false
$verbose = $false
$dryRun = $false
$runTests = $false
$configureRepoPath = $null

for ($index = 0; $index -lt $Arguments.Count; $index += 1) {
    switch ($Arguments[$index]) {
        "--help" { $showHelp = $true }
        "--status" { $showStatus = $true }
        "--setup" { $runSetup = $true }
        "--skip-setup" { $skipSetup = $true }
        "--build-only" { $buildOnly = $true }
        "--install-only" { $installOnly = $true }
        "--no-launch" { $noLaunch = $true }
        "--clean-build" { $cleanBuild = $true }
        "--verbose" { $verbose = $true }
        "--dry-run" { $dryRun = $true }
        "--test" { $runTests = $true }
        "--configure-repo" {
            $index += 1
            if ($index -ge $Arguments.Count) {
                throw "--configure-repo requires a repository path."
            }
            $configureRepoPath = $Arguments[$index]
        }
        default {
            throw "Unknown update-reefvision option: $($Arguments[$index])"
        }
    }
}

if ($showHelp) {
    Show-UpdateReefVisionHelp
    exit 0
}

if ($configureRepoPath) {
    $resolved = Set-ReefVisionRepoPath -RepoPath $configureRepoPath
    Write-ReefVisionCommandNote "Configured ReefVision repository: $resolved"
    if (-not $showStatus) {
        exit 0
    }
}

if ($buildOnly -and $installOnly) {
    throw "--build-only and --install-only cannot be used together."
}

if ($runSetup -and $skipSetup) {
    throw "--setup and --skip-setup cannot be used together."
}

if ($installOnly -and $runSetup) {
    throw "--install-only cannot be combined with --setup. Run setup separately before installing a pinned MSI."
}

$repoPath = Resolve-ReefVisionRepoPath
if ($null -eq $repoPath) {
    throw "A ReefVision repository is required. Run update-reefvision --configure-repo PATH first."
}

$config = Get-ReefVisionCommandConfig
$pinnedMsiIdentity = if ($installOnly) { Get-ReefVisionPinnedMsiIdentity -Config $config } else { $null }
$expectedVersion = if ($installOnly) {
    $pinnedMsiIdentity.version
}
else {
    Assert-ReefVisionVersionConsistency -RepoPath $repoPath
}
$dependencySignature = Get-UpdateDependencySignature -RepoPath $repoPath
$msiDir = Get-ReefVisionMsiDirectory -RepoPath $repoPath
$latestInstaller = Get-ReefVisionLatestMsi -RepoPath $repoPath -ExpectedVersion $expectedVersion
$installedDesktopPath = Resolve-ReefVisionInstalledDesktopPath
$installedVersion = Get-ReefVisionExecutableVersion -ExecutablePath $installedDesktopPath
$registeredInstall = Test-ReefVisionCurrentUserInstallRegistration
$portableInstallDirectory = Resolve-ReefVisionPortableInstallDirectory -PreferredExecutablePath $installedDesktopPath
$installedBackendBundlePresent = Test-ReefVisionInstalledBackendBundle -InstallDirectory $portableInstallDirectory

if ($showStatus) {
    [pscustomobject]@{
        command_version = $script:ReefVisionCommandVersion
        repo_path = $repoPath
        reefvision_version = $expectedVersion
        dependency_signature = $dependencySignature
        stored_dependency_signature = $config.dependency_signature
        registered_current_user_install = $registeredInstall
        installed_desktop = $installedDesktopPath
        installed_version = $installedVersion
        portable_install_directory = $portableInstallDirectory
        installed_backend_bundle_present = $installedBackendBundlePresent
        latest_installer = if ($latestInstaller) { $latestInstaller.FullName } else { $null }
        latest_installer_written_at = if ($latestInstaller) { $latestInstaller.LastWriteTimeUtc } else { $null }
        msi_directory = $msiDir
    } | ConvertTo-Json -Depth 4
    exit 0
}

$lock = $null
if (-not $dryRun) {
    $lock = New-ReefVisionUpdateLock
}

try {
    Write-ReefVisionCommandStep "Preparing ReefVision update"
    Write-ReefVisionCommandNote "Repository: $repoPath"
    Write-ReefVisionCommandNote "Version: $expectedVersion"

    $gitStatus = "unavailable"
    if (Get-Command git -ErrorAction SilentlyContinue) {
        try {
            Push-Location $repoPath
            $gitStatus = (& git status --short)
        }
        catch {
            $gitStatus = "unavailable"
        }
        finally {
            Pop-Location
        }
    }
    if ($verbose) {
        Write-ReefVisionCommandNote "Git status: $gitStatus"
    }

    # Installing an already verified, pinned MSI must remain offline and must
    # never bootstrap Python/Node dependencies or fetch packages.
    $setupNeeded = -not $installOnly -and ($runSetup -or (-not $skipSetup -and (
        $dependencySignature -ne $config.dependency_signature -or
        -not (Test-Path (Join-Path $repoPath ".venv") -PathType Container) -or
        -not (Test-Path (Join-Path $repoPath "apps\web\node_modules") -PathType Container)
    )))

    if ($dryRun) {
        [pscustomobject]@{
            repo_path = $repoPath
            reefvision_version = $expectedVersion
            setup_needed = $setupNeeded
            build_only = $buildOnly
            install_only = $installOnly
            clean_build = $cleanBuild
            tests = $runTests
            registered_current_user_install = $registeredInstall
            installed_desktop = $installedDesktopPath
            installed_version = $installedVersion
            portable_install_directory = $portableInstallDirectory
            installed_backend_bundle_present = $installedBackendBundlePresent
            latest_installer = if ($latestInstaller) { $latestInstaller.FullName } else { $null }
        } | ConvertTo-Json -Depth 4
        exit 0
    }

    if ($cleanBuild) {
        throw "--clean-build is disabled for MSI updates until artifact-only, ownership-verified cleanup is validated. No files were deleted."
    }

    if ($runTests) {
        Write-ReefVisionCommandStep "Running ReefVision tests"
        & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoPath "scripts\test.ps1")
        if ($LASTEXITCODE -ne 0) {
            throw "ReefVision tests failed."
        }
    }

    if ($setupNeeded) {
        Write-ReefVisionCommandStep "Running ReefVision setup"
        & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoPath "scripts\bootstrap.ps1") -ProviderRequirementsFile "requirements/providers-windows-cu121-py312.txt"
        if ($LASTEXITCODE -ne 0) {
            throw "ReefVision setup failed."
        }
        $config = Get-ReefVisionCommandConfig
        $config.dependency_signature = $dependencySignature
        Save-ReefVisionCommandConfig -Config $config
    }

    if ($installOnly) {
        # The checkout may advance after --build-only. Trust only the cached
        # identity, then verify it against the pinned MSI and external CABs.
        $expectedSourceCommit = $pinnedMsiIdentity.source_commit
    }
    else {
        $expectedSourceCommit = (& git -C $repoPath rev-parse HEAD).Trim()
        if ($LASTEXITCODE -ne 0 -or $expectedSourceCommit -notmatch '^[0-9a-fA-F]{40}$') {
            throw "Unable to resolve the checked-out ReefVision source commit."
        }
    }
    $installer = $null
    if (-not $installOnly) {
        # The commit recorded in MSI provenance must describe the actual source.
        Assert-ReefVisionSourceTreeClean -RepoPath $repoPath -ExpectedCommit $expectedSourceCommit
        $buildStartedAtUtc = (Get-Date).ToUniversalTime().AddSeconds(-1)
        Write-ReefVisionCommandStep "Building the ReefVision desktop installer"
        & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoPath "scripts\build-desktop.ps1")
        if ($LASTEXITCODE -ne 0) {
            throw "The ReefVision desktop build failed."
        }
        # Refuse to publish a build if source changed while compilation ran.
        Assert-ReefVisionSourceTreeClean -RepoPath $repoPath -ExpectedCommit $expectedSourceCommit

        $installer = Get-ReefVisionFreshMsi -RepoPath $repoPath -ExpectedVersion $expectedVersion -BuildStartedAtUtc $buildStartedAtUtc
        if ($null -eq $installer) {
            throw "No fresh ReefVision v$expectedVersion installer was produced by the completed build. Stale installers were rejected."
        }
        # Includes --build-only: never cache an unverified MSI path.
        $null = Assert-ReefVisionMsiPayload -InstallerPath $installer.FullName -RepoPath $repoPath -ExpectedVersion $expectedVersion -ExpectedCommit $expectedSourceCommit

        $installerSha = (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash
        $config = Get-ReefVisionCommandConfig
        $config.last_installer_path = $installer.FullName
        $config.last_installer_sha256 = $installerSha
        $config.last_installer_version = $expectedVersion
        $config.last_installer_source_commit = $expectedSourceCommit
        Save-ReefVisionCommandConfig -Config $config

        Write-ReefVisionCommandNote "Fresh installer: $($installer.FullName)"
        Write-ReefVisionCommandNote "SHA-256: $installerSha"
    }

    if ($buildOnly) {
        exit 0
    }

    if ($installOnly) {
        # A fresh build or --build-only pins both the local path and its SHA-256.
        # Never silently fall back to an unpinned MSI discovered by timestamp.
        if ([string]::IsNullOrWhiteSpace([string]$config.last_installer_path)) {
            throw "No pinned ReefVision MSI is available. Run update-reefvision --build-only first."
        }
        $installer = Assert-ReefVisionCachedMsi -InstallerPath ([string]$config.last_installer_path) -RepoPath $repoPath -ExpectedSha256 ([string]$config.last_installer_sha256)
    }

    if ($null -eq $installer) {
        throw "No ReefVision installer is available to install."
    }

    # Verify again before stopping the existing application.
    $verifiedMsi = Assert-ReefVisionMsiPayload -InstallerPath $installer.FullName -RepoPath $repoPath -ExpectedVersion $expectedVersion -ExpectedCommit $expectedSourceCommit
    Write-ReefVisionCommandNote "Verified MSI source commit: $($verifiedMsi.source_commit)"
    # Reject a verified but older installer before stopping the existing desktop.
    Assert-ReefVisionInstalledDesktopVersionKnown -InstalledExecutablePath $installedDesktopPath -InstalledVersion $installedVersion -RegisteredInstall $registeredInstall
    Assert-ReefVisionMsiNoDowngrade -InstalledVersion $installedVersion -TargetVersion $expectedVersion

    # Preflight the MSI engine and a safe log destination before stopping the
    # user's running desktop. Invalid paths must leave the application running.
    $msiexec = Join-Path $env:SystemRoot 'System32\msiexec.exe'
    if (-not (Test-Path -LiteralPath $msiexec -PathType Leaf)) {
        throw "Windows Installer executable is unavailable: $msiexec"
    }
    $logDir = Assert-ReefVisionMsiLogDirectory -LogDirectory (Get-ReefVisionCommandRuntimeDir)
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $logPath = Join-Path $logDir ("msi-update-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N') + '.log')

    Write-ReefVisionCommandStep "Stopping running ReefVision processes"
    Stop-ReefVisionRunningProcesses
    Start-Sleep -Milliseconds 500

    # MSI owns installation and rollback. Never overwrite portable backend
    # files or remove any existing user assets during the update.
    $arguments = "/i `"$($installer.FullName)`" /passive /norestart /L*v `"$logPath`""
    Write-ReefVisionCommandStep "Installing verified ReefVision MSI"
    $process = Start-Process -FilePath $msiexec -ArgumentList $arguments -PassThru -Wait
    if ($process.ExitCode -notin @(0, 3010)) {
        throw "MSI installation failed with exit code $($process.ExitCode). See $logPath"
    }
    Write-ReefVisionCommandNote "MSI log: $logPath"
    if ($process.ExitCode -eq 3010) {
        Write-Warning "MSI installation requires a Windows restart. Desktop version verification and relaunch are deferred until after reboot. See $logPath"
        return
    }
    $installedDesktopPath = Resolve-ReefVisionInstalledDesktopPath
    $installedVersion = Get-ReefVisionExecutableVersion -ExecutablePath $installedDesktopPath
    if ($installedVersion -notin @($expectedVersion, "$expectedVersion.0")) {
        throw "MSI completed but installed desktop version is '$installedVersion' (expected '$expectedVersion'). See $logPath"
    }
    if (-not $noLaunch) {
        Write-ReefVisionCommandStep "Launching the updated ReefVision desktop app"
        & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoPath "scripts\start-reefvision.ps1") --no-wait
        if ($LASTEXITCODE -ne 0) {
            throw "The updated ReefVision desktop app did not launch successfully."
        }
    }
}
finally {
    if ($lock) {
        Close-ReefVisionUpdateLock -Lock $lock
    }
}
