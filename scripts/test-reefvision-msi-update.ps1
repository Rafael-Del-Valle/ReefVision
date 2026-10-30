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
