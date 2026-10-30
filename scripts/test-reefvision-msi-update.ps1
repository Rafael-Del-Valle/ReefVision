# Windows-only, disposable, read-only regression for MSI updater path safety.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'lib\reefvision-msi-update.ps1')
$root = Join-Path $env:TEMP ('rv-msi-preflight-' + [guid]::NewGuid().ToString('N'))
$repo = Join-Path $root 'repo'
$bundle = Get-ReefVisionMsiDirectory -RepoPath $repo
$msi = Join-Path $bundle 'ReefVision_1.0.2_x64_en-US.msi'
$sentinel = Join-Path $root 'preserve.txt'
$passed = 0

function Assert-Throws {
    param([scriptblock]$Action, [string]$Fragment)
    $message = $null
    try { & $Action | Out-Null } catch { $message = $_.Exception.Message }
    if ($null -eq $message -or -not $message.Contains($Fragment)) {
        throw "Expected '$Fragment', received '$message'"
    }
    $script:passed++
}

try {
    New-Item -ItemType Directory -Path $bundle -Force | Out-Null
    Set-Content -LiteralPath $msi -Value 'not an installer' -Encoding ASCII
    Set-Content -LiteralPath $sentinel -Value 'preserve external data' -Encoding ASCII
    $sentinelHash = (Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash
    $actual = Assert-ReefVisionMsiLocalPath -InstallerPath $msi -RepoPath $repo
    if ($actual -ne [System.IO.Path]::GetFullPath($msi)) {
        throw 'Local MSI preflight changed the expected path.'
    }
    $passed++
    # The cached digest is a second independent guard for --install-only.
    $pinnedSha = (Get-FileHash -LiteralPath $msi -Algorithm SHA256).Hash
    $pinned = Assert-ReefVisionCachedMsi -InstallerPath $msi -RepoPath $repo -ExpectedSha256 ($pinnedSha.ToLowerInvariant())
    if ($pinned.FullName -ne [System.IO.Path]::GetFullPath($msi)) {
        throw 'Pinned MSI validation changed the selected installer.'
    }
    $passed++
    Assert-Throws {
        Assert-ReefVisionCachedMsi -InstallerPath $msi -RepoPath $repo -ExpectedSha256 ('0' * 64)
    } 'Cached MSI SHA-256 mismatch'
    Assert-Throws {
        Assert-ReefVisionCachedMsi -InstallerPath $msi -RepoPath $repo -ExpectedSha256 ''
    } 'Missing or invalid cached MSI SHA-256'
    Assert-Throws {
        Assert-ReefVisionCachedMsi -InstallerPath $sentinel -RepoPath $repo -ExpectedSha256 $pinnedSha
    } 'outside the exact local build directory'
    Assert-Throws {
        Assert-ReefVisionMsiLocalPath -InstallerPath $sentinel -RepoPath $repo
    } 'outside the exact local build directory'
    Assert-Throws {
        Assert-ReefVisionMsiLocalPath -InstallerPath (Join-Path $bundle 'missing.msi') -RepoPath $repo
    } 'missing from the local build directory'
    # The recorded Git SHA must describe the actual MSI build input. Exercise
    # the real helper against a disposable repository, never the user's data.
    $sourceRepo = Join-Path $root 'source-repo'
    New-Item -ItemType Directory -Path $sourceRepo -Force | Out-Null
    & git -C $sourceRepo init --quiet | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot initialize disposable Git source fixture.' }
    $tracked = Join-Path $sourceRepo 'tracked.txt'
    Set-Content -LiteralPath $tracked -Value 'baseline' -Encoding ASCII
    & git -C $sourceRepo add -- tracked.txt | Out-Null
    & git -C $sourceRepo -c user.name=ReefVisionCI -c user.email=ci@example.invalid commit --quiet -m baseline | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot commit disposable Git source fixture.' }
    $sourceCommit = (& git -C $sourceRepo rev-parse HEAD).Trim()
    Assert-ReefVisionSourceTreeClean -RepoPath $sourceRepo -ExpectedCommit $sourceCommit
    $passed++
    Assert-Throws {
        Assert-ReefVisionSourceTreeClean -RepoPath $sourceRepo -ExpectedCommit ('a' * 40)
    } 'HEAD changed during MSI packaging'
    Set-Content -LiteralPath $tracked -Value 'edited' -Encoding ASCII
    Assert-Throws {
        Assert-ReefVisionSourceTreeClean -RepoPath $sourceRepo -ExpectedCommit $sourceCommit
    } 'uncommitted or untracked'
    Set-Content -LiteralPath $tracked -Value 'baseline' -Encoding ASCII
    $untracked = Join-Path $sourceRepo 'untracked.txt'
    Set-Content -LiteralPath $untracked -Value 'not in provenance' -Encoding ASCII
    Assert-Throws {
        Assert-ReefVisionSourceTreeClean -RepoPath $sourceRepo -ExpectedCommit $sourceCommit
    } 'uncommitted or untracked'
    Remove-Item -LiteralPath $untracked -Force
    Assert-ReefVisionSourceTreeClean -RepoPath $sourceRepo -ExpectedCommit $sourceCommit
    $passed++

    # A pinned MSI must use the version and source commit captured at build
    # time, even when the repository has advanced since --build-only.
    $pinnedConfig = @{
        last_installer_version = '1.0.3'
        last_installer_source_commit = $sourceCommit
    }
    $pinnedIdentity = Get-ReefVisionPinnedMsiIdentity -Config $pinnedConfig
    if ($pinnedIdentity.version -ne '1.0.3' -or $pinnedIdentity.source_commit -ne $sourceCommit) {
        throw 'Pinned MSI identity did not preserve its original build provenance.'
    }
    $passed++
    Assert-Throws {
        Get-ReefVisionPinnedMsiIdentity -Config @{ last_installer_version = '1.0.3' }
    } 'Pinned MSI version or source commit'
    Assert-Throws {
        Get-ReefVisionPinnedMsiIdentity -Config @{ last_installer_source_commit = $sourceCommit }
    } 'Pinned MSI version or source commit'
    Assert-Throws {
        Get-ReefVisionPinnedMsiIdentity -Config @{
            last_installer_version = '1.0.3'
            last_installer_source_commit = ('z' * 40)
        }
    } 'Pinned MSI version or source commit'
    Assert-Throws {
        Get-ReefVisionPinnedMsiIdentity -Config @{
            last_installer_version = '256.0.0'
            last_installer_source_commit = $sourceCommit
        }
    } 'Windows Installer numeric limits'
    $passed += 4

    # A valid, locally pinned MSI must not replace a newer installed desktop.
    # Three-component MSI versions compare against four-component FileVersion.
    foreach ($case in @(
        @{ Installed = $null; Target = '1.0.3' },
        @{ Installed = '1.0.3'; Target = '1.0.3' },
        @{ Installed = '1.0.3.0'; Target = '1.0.3' },
        @{ Installed = '1.0.2.9'; Target = '1.0.3' },
        @{ Installed = '1.0.3'; Target = '1.0.4' }
    )) {
        Assert-ReefVisionMsiNoDowngrade -InstalledVersion $case.Installed -TargetVersion $case.Target
        $passed++
    }
    Assert-Throws {
        Assert-ReefVisionMsiNoDowngrade -InstalledVersion '1.0.4' -TargetVersion '1.0.3'
    } 'Refusing ReefVision MSI downgrade'
    Assert-Throws {
        Assert-ReefVisionMsiNoDowngrade -InstalledVersion '1.0.3.1' -TargetVersion '1.0.3'
    } 'Refusing ReefVision MSI downgrade'
    Assert-Throws {
        Assert-ReefVisionMsiNoDowngrade -InstalledVersion 'v1.0.4' -TargetVersion '1.0.3'
    } 'Cannot verify installed ReefVision version'
    Assert-Throws {
        Assert-ReefVisionMsiNoDowngrade -InstalledVersion '1.0.3' -TargetVersion '256.0.0'
    } 'Windows Installer numeric limits'

    # No .venv exists in this disposable repository. The offline provenance
    # validator must use an already installed Python 3.11+ from PATH, without
    # bootstrapping a virtual environment or installing dependencies.
    $systemPython = Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $systemPython) {
        throw 'Windows CI must provide Python 3.11+ for the offline fallback regression.'
    }
    $resolvedPython = Resolve-ReefVisionProvenancePython -RepoPath $repo
    if ($resolvedPython -ne $systemPython.Source) {
        throw 'Offline provenance fallback did not select the existing system Python.'
    }
    $passed++
    # A stale/broken repository Python must not force a dependency bootstrap
    # or prevent fallback to a compatible Python already installed on PATH.
    $venvScripts = Join-Path $repo '.venv\Scripts'
    New-Item -ItemType Directory -Path $venvScripts -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $venvScripts 'python.exe') -Value 'invalid executable' -Encoding ASCII
    $recoveredPython = Resolve-ReefVisionProvenancePython -RepoPath $repo
    if ($recoveredPython -ne $systemPython.Source) {
        throw 'Broken local Python prevented offline provenance fallback.'
    }
    $passed++
    # The resolver must not run Windows Store App Execution Aliases.
    $resolverSource = (Get-Command Resolve-ReefVisionProvenancePython).ScriptBlock.ToString()
    if (-not $resolverSource.Contains('WindowsApps')) {
        throw 'Offline provenance resolver no longer excludes Windows Store aliases.'
    }
    $passed++
    Assert-Throws {
        Assert-ReefVisionMsiPayload -InstallerPath $msi -RepoPath $repo -ExpectedVersion '1.0.2' -ExpectedCommit ('a' * 40)
    } 'MSI provenance validator is missing'

    # A junction can preserve the apparent MSI directory suffix but redirect
    # to a different location. Reject it before any manifest or MSI access.
    $linkedRepo = Join-Path $root 'linked-repo'
    New-Item -ItemType Junction -Path $linkedRepo -Target $repo | Out-Null
    try {
        $linked = Join-Path (Get-ReefVisionMsiDirectory -RepoPath $linkedRepo) (Split-Path -Leaf $msi)
        Assert-Throws {
            Assert-ReefVisionMsiLocalPath -InstallerPath $linked -RepoPath $linkedRepo
        } 'symlink/junction'
    }
    finally {
        Remove-Item -LiteralPath $linkedRepo -Force
    }
    if ((Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -ne $sentinelHash) {
        throw 'MSI preflight changed an unrelated file.'
    }
    $passed++

    # MSI logs must never be redirected into unrelated user directories.
    $validLog = Join-Path $root 'managed-logs'
    if ((Assert-ReefVisionMsiLogDirectory -LogDirectory $validLog) -ne
        [System.IO.Path]::GetFullPath($validLog)) {
        throw 'Valid MSI log directory was not accepted.'
    }
    $passed++
    $logFile = Join-Path $root 'log-file'
    Set-Content -LiteralPath $logFile -Value 'preserve' -Encoding ASCII
    Assert-Throws {
        Assert-ReefVisionMsiLogDirectory -LogDirectory $logFile
    } 'occupied by a file'
    $redirectedLog = Join-Path $root 'redirected-logs'
    New-Item -ItemType Junction -Path $redirectedLog -Target $repo | Out-Null
    try {
        Assert-Throws {
            Assert-ReefVisionMsiLogDirectory -LogDirectory (Join-Path $redirectedLog 'logs')
        } 'symlink/junction'
    }
    finally {
        Remove-Item -LiteralPath $redirectedLog -Force
    }
    # Regression contract for the actual installed command: never silently
    # reintroduce NSIS execution or direct portable-backend overwrites.
    $updateScript = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'update-reefvision.ps1') -Raw
    $installerScript = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'install-reefvision-commands.ps1') -Raw
    if ($updateScript.Split('Assert-ReefVisionSourceTreeClean -RepoPath $repoPath -ExpectedCommit $expectedSourceCommit').Count -ne 3) {
        throw 'MSI updater must check source cleanliness both before and after building.'
    }
    $passed++
    if ($updateScript.Contains('$installer = Get-ReefVisionFreshInstaller')) {
        throw 'Updater still selects the legacy NSIS installer.'
    }
    if ($updateScript.Contains('$portableSync = Sync-ReefVisionPortableInstall')) {
        throw 'Updater still overwrites portable backend files.'
    }
    if (-not $updateScript.Contains('$installer = Assert-ReefVisionCachedMsi') -or
        $updateScript.Contains('$installer = $latestInstaller')) {
        throw 'Install-only must use the pinned MSI path and digest, without a fallback.'
    }

    if (-not $updateScript.Contains('Get-ReefVisionPinnedMsiIdentity -Config $config') -or
        -not $updateScript.Contains('$pinnedMsiIdentity.version') -or
        -not $updateScript.Contains('$expectedSourceCommit = $pinnedMsiIdentity.source_commit') -or
        -not $updateScript.Contains('$config.last_installer_version = $expectedVersion') -or
        -not $updateScript.Contains('$config.last_installer_source_commit = $expectedSourceCommit')) {
        throw 'Install-only must use the persisted MSI build identity, not the current checkout.'
    }
    $passed++

    # Evaluate the actual updater setup expression without executing an
    # installer. A pinned --install-only must not bootstrap dependencies even
    # when the repository has missing environments or a changed signature.
    $parseTokens = $null
    $parseErrors = $null
    $updateAst = [System.Management.Automation.Language.Parser]::ParseInput(
        $updateScript, [ref]$parseTokens, [ref]$parseErrors
    )
    if ($null -ne $parseErrors -and $parseErrors.Count -gt 0) {
        throw 'Updater PowerShell source did not parse.'
    }
    $setupAssignments = @($updateAst.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
            $node.Left.Extent.Text -eq '$setupNeeded'
    }, $true))
    if ($setupAssignments.Count -ne 1) {
        throw 'Expected exactly one updater setup decision.'
    }
    $setupDecision = [scriptblock]::Create($setupAssignments[0].Extent.Text + "`n`$setupNeeded")
    $repoPath = $repo
    $dependencySignature = 'changed'
    $config = [pscustomobject]@{ dependency_signature = 'previous' }
    foreach ($case in @(
        @{ InstallOnly = $true; RunSetup = $false; SkipSetup = $false; Expected = $false },
        @{ InstallOnly = $true; RunSetup = $false; SkipSetup = $true; Expected = $false },
        @{ InstallOnly = $false; RunSetup = $false; SkipSetup = $false; Expected = $true },
        @{ InstallOnly = $false; RunSetup = $false; SkipSetup = $true; Expected = $false },
        @{ InstallOnly = $false; RunSetup = $true; SkipSetup = $false; Expected = $true }
    )) {
        $installOnly = $case.InstallOnly
        $runSetup = $case.RunSetup
        $skipSetup = $case.SkipSetup
        $actual = & $setupDecision
        if ([bool]$actual -ne [bool]$case.Expected) {
            throw "Unexpected setup decision for installOnly=$installOnly runSetup=$runSetup skipSetup=$skipSetup"
        }
        $passed++
    }
    if (-not $updateScript.Contains('if ($installOnly -and $runSetup)')) {
        throw 'Install-only must explicitly reject a conflicting --setup request.'
    }
    $passed++

    $verificationPosition = $updateScript.LastIndexOf('Assert-ReefVisionMsiPayload')
    $stopPosition = $updateScript.IndexOf('Stop-ReefVisionRunningProcesses', $verificationPosition)
    if ($verificationPosition -lt 0 -or $stopPosition -le $verificationPosition) {
        throw 'MSI verification must precede stopping the desktop.'
    }
    $enginePreflight = $updateScript.IndexOf('if (-not (Test-Path -LiteralPath $msiexec -PathType Leaf))')
    $logPreflight = $updateScript.IndexOf('Assert-ReefVisionMsiLogDirectory')
    if ($enginePreflight -le $verificationPosition -or $enginePreflight -ge $stopPosition -or
        $logPreflight -le $verificationPosition -or $logPreflight -ge $stopPosition) {
        throw 'MSI executable and safe log preflight must precede stopping the desktop.'
    }
    $downgradePreflight = $updateScript.IndexOf(
        'Assert-ReefVisionMsiNoDowngrade -InstalledVersion $installedVersion -TargetVersion $expectedVersion'
    )
    if ($downgradePreflight -le $verificationPosition -or $downgradePreflight -ge $stopPosition) {
        throw 'Downgrade preflight must run after MSI verification and before desktop shutdown.'
    }
    $passed++
    $passed++
    if ($updateScript -notmatch '(?s)if \(\$process\.ExitCode -eq 3010\) \{\s*Write-Warning[^\r\n]*\s*return\s*\}') {
        throw 'Reboot-required MSI result must defer version verification and relaunch.'
    }
    $passed++
    if (-not $updateScript.Contains('msiexec.exe') -or
        -not $updateScript.Contains('--clean-build is disabled')) {
        throw 'Updater MSI installation or safe-cleanup contract is missing.'
    }
    if (-not $installerScript.Contains('Destination = Join-Path $supportDir "reefvision-msi-update.ps1"')) {
        throw 'Managed command installation does not deploy the MSI helper.'
    }
    $passed += 6
    Write-Host "MSI update preflight: $passed passed" -ForegroundColor Green
}
finally {
    if (Test-Path -LiteralPath $root) {
        Remove-Item -LiteralPath $root -Recurse -Force
    }
}
