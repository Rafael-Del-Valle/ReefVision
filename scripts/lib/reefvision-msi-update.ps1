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
    $python = Join-Path $RepoPath '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "ReefVision Python environment missing; cannot verify MSI provenance."
    }
    $validator = Join-Path $RepoPath 'scripts\validate_msi_provenance.py'
    if (-not (Test-Path -LiteralPath $validator -PathType Leaf)) {
        throw "MSI provenance validator is missing."
    }
    $directory = [System.IO.Path]::GetDirectoryName($msiPath)
    & $python $validator --directory $directory --expected-version $ExpectedVersion --expected-commit $ExpectedCommit | Out-Null
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
