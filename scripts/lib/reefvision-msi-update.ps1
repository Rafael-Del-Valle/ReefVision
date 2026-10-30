# Offline-first Windows MSI updater support. No install or deletion in this module.
Set-StrictMode -Version Latest

function Get-ReefVisionMsiDirectory {
    param([Parameter(Mandatory = $true)][string]$RepoPath)
    Join-Path $RepoPath 'apps\web\src-tauri\target\x86_64-pc-windows-msvc\release\bundle\msi'
}

function Get-ReefVisionLatestMsi {
    param([string]$RepoPath, [string]$ExpectedVersion)
    $dir = Get-ReefVisionMsiDirectory -RepoPath $RepoPath
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) { return $null }
    Get-ChildItem -LiteralPath $dir -Filter ('ReefVision_' + $ExpectedVersion + '_*.msi') -File |
        Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
}

function Get-ReefVisionFreshMsi {
    param([string]$RepoPath, [string]$ExpectedVersion, [datetime]$BuildStartedAtUtc)
    $candidate = Get-ReefVisionLatestMsi -RepoPath $RepoPath -ExpectedVersion $ExpectedVersion
    if ($null -eq $candidate -or $candidate.LastWriteTimeUtc -lt $BuildStartedAtUtc) { return $null }
    return $candidate
}

function Assert-ReefVisionMsiLocalPath {
    param([string]$InstallerPath, [string]$RepoPath)
    $expected = [System.IO.Path]::GetFullPath(
        (Get-ReefVisionMsiDirectory -RepoPath $RepoPath)
    ).TrimEnd([char]92)
    $actual = [System.IO.Path]::GetFullPath($InstallerPath)
    if ([System.IO.Path]::GetDirectoryName($actual).TrimEnd([char]92) -ine $expected) {
        throw "Refusing MSI outside the exact local build directory: $actual"
    }
    if (-not (Test-Path -LiteralPath $actual -PathType Leaf)) {
        throw "MSI is missing from the local build directory: $actual"
    }
    $current = $actual
    while (-not [string]::IsNullOrWhiteSpace($current)) {
        $entry = Get-Item -LiteralPath $current -Force -ErrorAction Stop
        if (($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing MSI through a symlink/junction: $current"
        }
        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) { break }
        $current = $parent
    }
    return $actual
}

# A signed source SHA is insufficient if local tracked or untracked files can
# silently change the desktop payload. Validate both before and after building.
# This is intentionally not required for offline --install-only: its pinned MSI
# and independent provenance checks are the authority for that path.
function Assert-ReefVisionSourceTreeClean {
    param(
        [Parameter(Mandatory = $true)][string]$RepoPath,
        [Parameter(Mandatory = $true)][string]$ExpectedCommit
    )
    if ($ExpectedCommit -cnotmatch '^[0-9a-fA-F]{40}
# FileVersion may have a fourth numeric component; MSI ProductVersion has three.
# Unknown installed versions fail closed rather than silently replacing a
# researcher's working installation with an older build.
function Assert-ReefVisionMsiNoDowngrade {
    param(
        [string]$InstalledVersion,
        [Parameter(Mandatory = $true)][string]$TargetVersion
    )
    if ($TargetVersion -cnotmatch '^\d{1,3}\.\d{1,3}\.\d{1,5}$') {
        throw "Target ReefVision MSI version is invalid: $TargetVersion"
    }
    $targetParts = @($TargetVersion.Split('.') | ForEach-Object { [int]$_ })
    if ($targetParts[0] -gt 255 -or $targetParts[1] -gt 255 -or $targetParts[2] -gt 65535) {
        throw "Target ReefVision MSI version exceeds Windows Installer numeric limits."
    }
    if ([string]::IsNullOrWhiteSpace($InstalledVersion)) { return }
    if ($InstalledVersion -cnotmatch '^\d{1,3}\.\d{1,3}\.\d{1,5}(?:\.\d{1,5})?$') {
        throw "Cannot verify installed ReefVision version '$InstalledVersion'; refusing unattended replacement."
    }
    $installedParts = @($InstalledVersion.Split('.') | ForEach-Object { [int]$_ })
    if ($installedParts.Count -eq 3) { $installedParts += 0 }
    $targetParts += 0
    for ($index = 0; $index -lt 4; $index++) {
        if ($targetParts[$index] -lt $installedParts[$index]) {
            throw "Refusing ReefVision MSI downgrade from $InstalledVersion to $TargetVersion."
        }
        if ($targetParts[$index] -gt $installedParts[$index]) { return }
    }
    # Same-version repair is allowed; MSI itself retains ownership of rollback.
}

# --install-only is permitted only for a previously verified, pinned build.
# A manifest alone is not a trustworthy replacement for the cached MSI hash.
function Assert-ReefVisionCachedMsi {
    param(
        [Parameter(Mandatory = $true)][string]$InstallerPath,
        [Parameter(Mandatory = $true)][string]$RepoPath,
        [string]$ExpectedSha256
    )
    if ($ExpectedSha256 -cnotmatch '^[0-9a-fA-F]{64}$') {
        throw "Missing or invalid cached MSI SHA-256. Run update-reefvision --build-only first."
    }
    $msiPath = Assert-ReefVisionMsiLocalPath -InstallerPath $InstallerPath -RepoPath $RepoPath
    $actualSha256 = (Get-FileHash -LiteralPath $msiPath -Algorithm SHA256).Hash
    if (-not [string]::Equals($actualSha256, $ExpectedSha256, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Cached MSI SHA-256 mismatch. Run update-reefvision --build-only again."
    }
    return Get-Item -LiteralPath $msiPath
}

# Provenance validation is standard-library-only. Prefer the project's Python,
# but allow an already installed system Python for offline --install-only.
# Never bootstrap a Python environment or fetch packages in this resolver.
function Resolve-ReefVisionProvenancePython {
    param([Parameter(Mandatory = $true)][string]$RepoPath)
    # Prefer the repository interpreter, but do not let a broken or outdated
    # .venv block an already installed, compatible offline system Python.
    $candidates = @()
    $venvPython = Join-Path $RepoPath '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $candidates += $venvPython
    }
    foreach ($command in @(Get-Command python.exe -All -CommandType Application -ErrorAction SilentlyContinue)) {
        if (-not [string]::IsNullOrWhiteSpace($command.Source) -and $command.Source -notin $candidates) {
            $candidates += $command.Source
        }
    }
    foreach ($candidate in $candidates) {
        $python = [System.IO.Path]::GetFullPath($candidate)
        # Windows App Execution Aliases can open the Microsoft Store instead
        # of running Python; never invoke them during an offline MSI install.
        if ($python -match '(?i)[\\/]WindowsApps[\\/]') { continue }
        if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { continue }
        try {
            $version = & $python -I -S -B -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>$null
            if ($LASTEXITCODE -eq 0 -and [string]$version -match '^3\.(\d+)$' -and [int]$Matches[1] -ge 11) {
                return $python
            }
        }
        catch {
            # A corrupt .venv or incompatible interpreter is not sufficient
            # reason to stop searching installed, offline alternatives.
            continue
        }
    }
    throw "Python 3.11+ is required for isolated MSI provenance verification. No usable local interpreter was found; no installation or package download was attempted."
}

function Assert-ReefVisionMsiPayload {
    param(
        [string]$InstallerPath,
        [string]$RepoPath,
        [string]$ExpectedVersion,
        [string]$ExpectedCommit
    )
    $msiPath = Assert-ReefVisionMsiLocalPath -InstallerPath $InstallerPath -RepoPath $RepoPath
    if ([System.IO.Path]::GetFileName($msiPath) -cne ('ReefVision_' + $ExpectedVersion + '_x64_en-US.msi')) {
        throw "MSI filename differs from the expected version."
    }
    if ($ExpectedCommit -notmatch '^[0-9a-fA-F]{40}$') {
        throw "Expected source commit must be a complete Git SHA."
    }
    $python = Resolve-ReefVisionProvenancePython -RepoPath $RepoPath
    $validator = Join-Path $RepoPath 'scripts\validate_msi_provenance.py'
    if (-not (Test-Path -LiteralPath $validator -PathType Leaf)) {
        throw "MSI provenance validator is missing."
    }
    $directory = [System.IO.Path]::GetDirectoryName($msiPath)
    & $python -I -S -B $validator --directory $directory --expected-version $ExpectedVersion --expected-commit $ExpectedCommit | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "MSI/CAB provenance validation failed." }

    # The MSI Media table, not the manifest, determines the required CABs.
    $installer = New-Object -ComObject WindowsInstaller.Installer
    $database = $installer.OpenDatabase($msiPath, 0)
    $tick = [char]96
    $versionSql = 'SELECT ' + $tick + 'Value' + $tick + ' FROM ' + $tick + 'Property' + $tick +
        ' WHERE ' + $tick + 'Property' + $tick + "='ProductVersion'"
    $versionView = $database.OpenView($versionSql)
    try {
        $versionView.Execute()
        $record = $versionView.Fetch()
        if ($null -eq $record -or $record.StringData(1) -ne $ExpectedVersion) {
            throw "MSI ProductVersion differs from expected version."
        }
    }
    finally { $versionView.Close() }
    $mediaView = $database.OpenView(('SELECT ' + $tick + 'Cabinet' + $tick + ' FROM ' + $tick + 'Media' + $tick))
    $required = @()
    try {
        $mediaView.Execute()
        while ($record = $mediaView.Fetch()) {
            $name = [string]$record.StringData(1)
            if (-not $name -or $name.StartsWith('#')) { continue }
            if ($name -cnotmatch '^[A-Za-z0-9_-][A-Za-z0-9_.-]*\.cab$') {
                throw "Unsafe MSI Media cabinet filename: $name"
            }
            $required += $name
        }
    }
    finally { $mediaView.Close() }
    if ($required.Count -eq 0 -or @($required | Sort-Object -Unique).Count -ne $required.Count) {
        throw "MSI must declare a nonempty, unique external CAB set."
    }
    $actual = @(Get-ChildItem -LiteralPath $directory -Filter '*.cab' -File | ForEach-Object { $_.Name })
    if ($actual.Count -ne $required.Count -or
        @($actual | Where-Object { $_ -notin $required }).Count -gt 0) {
        throw "MSI Media table and verified CAB payload disagree."
    }
    return [pscustomobject]@{
        installer = $msiPath
        source_commit = $ExpectedCommit
        external_cabinets = $required
        verified = $true
    }
}

function Assert-ReefVisionMsiLogDirectory {
    param([Parameter(Mandatory = $true)][string]$LogDirectory)
    $fullPath = [System.IO.Path]::GetFullPath($LogDirectory)
    $current = $fullPath
    while (-not [string]::IsNullOrWhiteSpace($current)) {
        $entry = Get-Item -LiteralPath $current -Force -ErrorAction SilentlyContinue
        if ($null -ne $entry) {
            if (($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing MSI log through a symlink/junction: $current"
            }
            if ($current -eq $fullPath -and -not $entry.PSIsContainer) {
                throw "Refusing MSI log directory occupied by a file: $fullPath"
            }
        }
        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) { break }
        $current = $parent
    }
    return $fullPath
}
) {
        throw 'Expected ReefVision source commit must be a complete Git SHA.'
    }
    $head = & git -C $RepoPath rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace([string]$head)) {
        throw 'Cannot verify ReefVision source HEAD before MSI packaging.'
    }
    if ([string]$head.Trim() -cne $ExpectedCommit) {
        throw 'ReefVision source HEAD changed during MSI packaging; refusing an untraceable build.'
    }
    $changes = @(& git -C $RepoPath status --porcelain=v1 --untracked-files=normal)
    if ($LASTEXITCODE -ne 0) {
        throw 'Cannot verify ReefVision source cleanliness before MSI packaging.'
    }
    if (@($changes | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }).Count -gt 0) {
        throw 'Refusing MSI build from uncommitted or untracked ReefVision source files; commit or isolate changes first.'
    }
}

# Reject accidental MSI downgrades before stopping a running desktop.
# FileVersion may have a fourth numeric component; MSI ProductVersion has three.
# Unknown installed versions fail closed rather than silently replacing a
# researcher's working installation with an older build.
function Assert-ReefVisionMsiNoDowngrade {
    param(
        [string]$InstalledVersion,
        [Parameter(Mandatory = $true)][string]$TargetVersion
    )
    if ($TargetVersion -cnotmatch '^\d{1,3}\.\d{1,3}\.\d{1,5}$') {
        throw "Target ReefVision MSI version is invalid: $TargetVersion"
    }
    $targetParts = @($TargetVersion.Split('.') | ForEach-Object { [int]$_ })
    if ($targetParts[0] -gt 255 -or $targetParts[1] -gt 255 -or $targetParts[2] -gt 65535) {
        throw "Target ReefVision MSI version exceeds Windows Installer numeric limits."
    }
    if ([string]::IsNullOrWhiteSpace($InstalledVersion)) { return }
    if ($InstalledVersion -cnotmatch '^\d{1,3}\.\d{1,3}\.\d{1,5}(?:\.\d{1,5})?$') {
        throw "Cannot verify installed ReefVision version '$InstalledVersion'; refusing unattended replacement."
    }
    $installedParts = @($InstalledVersion.Split('.') | ForEach-Object { [int]$_ })
    if ($installedParts.Count -eq 3) { $installedParts += 0 }
    $targetParts += 0
    for ($index = 0; $index -lt 4; $index++) {
        if ($targetParts[$index] -lt $installedParts[$index]) {
            throw "Refusing ReefVision MSI downgrade from $InstalledVersion to $TargetVersion."
        }
        if ($targetParts[$index] -gt $installedParts[$index]) { return }
    }
    # Same-version repair is allowed; MSI itself retains ownership of rollback.
}

# --install-only is permitted only for a previously verified, pinned build.
# A manifest alone is not a trustworthy replacement for the cached MSI hash.
function Assert-ReefVisionCachedMsi {
    param(
        [Parameter(Mandatory = $true)][string]$InstallerPath,
        [Parameter(Mandatory = $true)][string]$RepoPath,
        [string]$ExpectedSha256
    )
    if ($ExpectedSha256 -cnotmatch '^[0-9a-fA-F]{64}$') {
        throw "Missing or invalid cached MSI SHA-256. Run update-reefvision --build-only first."
    }
    $msiPath = Assert-ReefVisionMsiLocalPath -InstallerPath $InstallerPath -RepoPath $RepoPath
    $actualSha256 = (Get-FileHash -LiteralPath $msiPath -Algorithm SHA256).Hash
    if (-not [string]::Equals($actualSha256, $ExpectedSha256, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Cached MSI SHA-256 mismatch. Run update-reefvision --build-only again."
    }
    return Get-Item -LiteralPath $msiPath
}

# Provenance validation is standard-library-only. Prefer the project's Python,
# but allow an already installed system Python for offline --install-only.
# Never bootstrap a Python environment or fetch packages in this resolver.
function Resolve-ReefVisionProvenancePython {
    param([Parameter(Mandatory = $true)][string]$RepoPath)
    # Prefer the repository interpreter, but do not let a broken or outdated
    # .venv block an already installed, compatible offline system Python.
    $candidates = @()
    $venvPython = Join-Path $RepoPath '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $candidates += $venvPython
    }
    foreach ($command in @(Get-Command python.exe -All -CommandType Application -ErrorAction SilentlyContinue)) {
        if (-not [string]::IsNullOrWhiteSpace($command.Source) -and $command.Source -notin $candidates) {
            $candidates += $command.Source
        }
    }
    foreach ($candidate in $candidates) {
        $python = [System.IO.Path]::GetFullPath($candidate)
        # Windows App Execution Aliases can open the Microsoft Store instead
        # of running Python; never invoke them during an offline MSI install.
        if ($python -match '(?i)[\\/]WindowsApps[\\/]') { continue }
        if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { continue }
        try {
            $version = & $python -I -S -B -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>$null
            if ($LASTEXITCODE -eq 0 -and [string]$version -match '^3\.(\d+)$' -and [int]$Matches[1] -ge 11) {
                return $python
            }
        }
        catch {
            # A corrupt .venv or incompatible interpreter is not sufficient
            # reason to stop searching installed, offline alternatives.
            continue
        }
    }
    throw "Python 3.11+ is required for isolated MSI provenance verification. No usable local interpreter was found; no installation or package download was attempted."
}

function Assert-ReefVisionMsiPayload {
    param(
        [string]$InstallerPath,
        [string]$RepoPath,
        [string]$ExpectedVersion,
        [string]$ExpectedCommit
    )
    $msiPath = Assert-ReefVisionMsiLocalPath -InstallerPath $InstallerPath -RepoPath $RepoPath
    if ([System.IO.Path]::GetFileName($msiPath) -cne ('ReefVision_' + $ExpectedVersion + '_x64_en-US.msi')) {
        throw "MSI filename differs from the expected version."
    }
    if ($ExpectedCommit -notmatch '^[0-9a-fA-F]{40}$') {
        throw "Expected source commit must be a complete Git SHA."
    }
    $python = Resolve-ReefVisionProvenancePython -RepoPath $RepoPath
    $validator = Join-Path $RepoPath 'scripts\validate_msi_provenance.py'
    if (-not (Test-Path -LiteralPath $validator -PathType Leaf)) {
        throw "MSI provenance validator is missing."
    }
    $directory = [System.IO.Path]::GetDirectoryName($msiPath)
    & $python -I -S -B $validator --directory $directory --expected-version $ExpectedVersion --expected-commit $ExpectedCommit | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "MSI/CAB provenance validation failed." }

    # The MSI Media table, not the manifest, determines the required CABs.
    $installer = New-Object -ComObject WindowsInstaller.Installer
    $database = $installer.OpenDatabase($msiPath, 0)
    $tick = [char]96
    $versionSql = 'SELECT ' + $tick + 'Value' + $tick + ' FROM ' + $tick + 'Property' + $tick +
        ' WHERE ' + $tick + 'Property' + $tick + "='ProductVersion'"
    $versionView = $database.OpenView($versionSql)
    try {
        $versionView.Execute()
        $record = $versionView.Fetch()
        if ($null -eq $record -or $record.StringData(1) -ne $ExpectedVersion) {
            throw "MSI ProductVersion differs from expected version."
        }
    }
    finally { $versionView.Close() }
    $mediaView = $database.OpenView(('SELECT ' + $tick + 'Cabinet' + $tick + ' FROM ' + $tick + 'Media' + $tick))
    $required = @()
    try {
        $mediaView.Execute()
        while ($record = $mediaView.Fetch()) {
            $name = [string]$record.StringData(1)
            if (-not $name -or $name.StartsWith('#')) { continue }
            if ($name -cnotmatch '^[A-Za-z0-9_-][A-Za-z0-9_.-]*\.cab$') {
                throw "Unsafe MSI Media cabinet filename: $name"
            }
            $required += $name
        }
    }
    finally { $mediaView.Close() }
    if ($required.Count -eq 0 -or @($required | Sort-Object -Unique).Count -ne $required.Count) {
        throw "MSI must declare a nonempty, unique external CAB set."
    }
    $actual = @(Get-ChildItem -LiteralPath $directory -Filter '*.cab' -File | ForEach-Object { $_.Name })
    if ($actual.Count -ne $required.Count -or
        @($actual | Where-Object { $_ -notin $required }).Count -gt 0) {
        throw "MSI Media table and verified CAB payload disagree."
    }
    return [pscustomobject]@{
        installer = $msiPath
        source_commit = $ExpectedCommit
        external_cabinets = $required
        verified = $true
    }
}

function Assert-ReefVisionMsiLogDirectory {
    param([Parameter(Mandatory = $true)][string]$LogDirectory)
    $fullPath = [System.IO.Path]::GetFullPath($LogDirectory)
    $current = $fullPath
    while (-not [string]::IsNullOrWhiteSpace($current)) {
        $entry = Get-Item -LiteralPath $current -Force -ErrorAction SilentlyContinue
        if ($null -ne $entry) {
            if (($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing MSI log through a symlink/junction: $current"
            }
            if ($current -eq $fullPath -and -not $entry.PSIsContainer) {
                throw "Refusing MSI log directory occupied by a file: $fullPath"
            }
        }
        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) { break }
        $current = $parent
    }
    return $fullPath
}
