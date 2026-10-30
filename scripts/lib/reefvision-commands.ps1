Set-StrictMode -Version Latest

$script:ReefVisionCommandVersion = "1.0.2"
$script:ReefVisionManagedWrapperMarker = "ReefVision managed command wrapper"

function Write-ReefVisionCommandStep {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Host $Message -ForegroundColor Green
}

function Write-ReefVisionCommandNote {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Host $Message -ForegroundColor DarkGray
}

function Get-ReefVisionCommandsRoot {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "LOCALAPPDATA is not available in this session."
    }
    return Join-Path $env:LOCALAPPDATA "ReefVision"
}

function Get-ReefVisionCommandBinDir {
    return Join-Path (Get-ReefVisionCommandsRoot) "bin"
}

function Get-ReefVisionCommandSupportDir {
    return Join-Path (Get-ReefVisionCommandsRoot) "commands"
}

function Get-ReefVisionCommandConfigPath {
    return Join-Path (Get-ReefVisionCommandsRoot) "config\commands.json"
}

function Get-ReefVisionCommandRuntimeDir {
    return Join-Path (Get-ReefVisionCommandsRoot) "runtime"
}

function Get-ReefVisionCommandLockPath {
    return Join-Path (Get-ReefVisionCommandRuntimeDir) "update.lock"
}

function New-ReefVisionCommandDirectoryLayout {
    foreach ($path in @(
        (Get-ReefVisionCommandsRoot),
        (Get-ReefVisionCommandBinDir),
        (Get-ReefVisionCommandSupportDir),
        (Split-Path -Parent (Get-ReefVisionCommandConfigPath)),
        (Get-ReefVisionCommandRuntimeDir)
    )) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
    }
}

function Get-ReefVisionCommandConfig {
    $default = @{
        command_version = $script:ReefVisionCommandVersion
        repo_path = $null
        installed_app_path = $null
        dependency_signature = $null
        last_installer_path = $null
        last_installer_sha256 = $null
        last_installer_version = $null
        last_installer_source_commit = $null
    }
    $configPath = Get-ReefVisionCommandConfigPath
    if (-not (Test-Path $configPath -PathType Leaf)) {
        return $default
    }

    try {
        $raw = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
        $loaded = @{}
        if ($raw -is [hashtable]) {
            foreach ($entry in $raw.GetEnumerator()) {
                $loaded[$entry.Key] = $entry.Value
            }
        }
        elseif ($null -ne $raw) {
            foreach ($property in $raw.PSObject.Properties) {
                $loaded[$property.Name] = $property.Value
            }
        }
        foreach ($key in $default.Keys) {
            if (-not $loaded.ContainsKey($key)) {
                $loaded[$key] = $default[$key]
            }
        }
        return $loaded
    }
    catch {
        return $default
    }
}

function Save-ReefVisionCommandConfig {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Config
    )

    New-ReefVisionCommandDirectoryLayout
    $Config["command_version"] = $script:ReefVisionCommandVersion
    $configPath = Get-ReefVisionCommandConfigPath
    $Config | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $configPath -Encoding UTF8
}

function Test-ReefVisionRepoRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    try {
        $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    }
    catch {
        return $false
    }

    return (
        (Test-Path (Join-Path $resolved "pyproject.toml") -PathType Leaf) -and
        (Test-Path (Join-Path $resolved "apps\web\package.json") -PathType Leaf) -and
        (Test-Path (Join-Path $resolved "scripts\build-desktop.ps1") -PathType Leaf)
    )
}

function Resolve-ReefVisionRepoPath {
    param(
        [string]$PreferredPath
    )

    if (-not [string]::IsNullOrWhiteSpace($PreferredPath) -and (Test-ReefVisionRepoRoot -Path $PreferredPath)) {
        return (Resolve-Path -LiteralPath $PreferredPath).Path
    }

    $config = Get-ReefVisionCommandConfig
    if (-not [string]::IsNullOrWhiteSpace($config.repo_path) -and (Test-ReefVisionRepoRoot -Path $config.repo_path)) {
        return (Resolve-Path -LiteralPath $config.repo_path).Path
    }

    $scriptCandidates = @(
        (Split-Path -Parent $PSScriptRoot),
        (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
    ) | Where-Object { $_ }
    foreach ($candidate in $scriptCandidates | Select-Object -Unique) {
        if (Test-ReefVisionRepoRoot -Path $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    return $null
}

function Set-ReefVisionRepoPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoPath
    )

    if (-not (Test-ReefVisionRepoRoot -Path $RepoPath)) {
        throw "The provided repository path does not look like a ReefVision checkout: $RepoPath"
    }

    $resolved = (Resolve-Path -LiteralPath $RepoPath).Path
    $config = Get-ReefVisionCommandConfig
    $config.repo_path = $resolved
    Save-ReefVisionCommandConfig -Config $config
    return $resolved
}

function Get-ReefVisionInstalledDesktopCandidates {
    $config = Get-ReefVisionCommandConfig
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($config.installed_app_path)) {
        $candidates += $config.installed_app_path
    }
    $candidates += @(
        (Join-Path $env:LOCALAPPDATA "ReefVision\reefvision-desktop.exe"),
        (Join-Path $env:LOCALAPPDATA "ReefVision\ReefVision.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\ReefVision\ReefVision.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\ReefVision\reefvision-desktop.exe"),
        (Join-Path ${env:ProgramFiles} "ReefVision\ReefVision.exe")
    )
    if (-not [string]::IsNullOrWhiteSpace(${env:ProgramFiles})) {
        $candidates += (Join-Path ${env:ProgramFiles} "ReefVision\reefvision-desktop.exe")
    }
    if ($env:ProgramFiles -ne $env:ProgramW6432 -and -not [string]::IsNullOrWhiteSpace($env:ProgramW6432)) {
        $candidates += (Join-Path $env:ProgramW6432 "ReefVision\ReefVision.exe")
        $candidates += (Join-Path $env:ProgramW6432 "ReefVision\reefvision-desktop.exe")
    }
    if (-not [string]::IsNullOrWhiteSpace(${env:ProgramFiles(x86)})) {
        $candidates += (Join-Path ${env:ProgramFiles(x86)} "ReefVision\ReefVision.exe")
        $candidates += (Join-Path ${env:ProgramFiles(x86)} "ReefVision\reefvision-desktop.exe")
    }
    return $candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique
}

function Resolve-ReefVisionInstalledDesktopPath {
    param(
        [string]$PreferredPath
    )

    foreach ($candidate in @($PreferredPath) + (Get-ReefVisionInstalledDesktopCandidates)) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }
        if (Test-Path $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Get-ReefVisionExecutableVersion {
    param(
        [string]$ExecutablePath
    )

    if ([string]::IsNullOrWhiteSpace($ExecutablePath)) {
        return $null
    }
    if (-not (Test-Path $ExecutablePath -PathType Leaf)) {
        return $null
    }

    try {
        $item = Get-Item -LiteralPath $ExecutablePath
        $version = $item.VersionInfo.ProductVersion
        if ([string]::IsNullOrWhiteSpace($version)) {
            $version = $item.VersionInfo.FileVersion
        }
        if ([string]::IsNullOrWhiteSpace($version)) {
            return $null
        }
        return [string]$version
    }
    catch {
        return $null
    }
}

function Resolve-ReefVisionInstalledDirectory {
    param(
        [string]$PreferredExecutablePath
    )

    $desktopPath = Resolve-ReefVisionInstalledDesktopPath -PreferredPath $PreferredExecutablePath
    if ($desktopPath) {
        return Split-Path -Parent $desktopPath
    }
    return $null
}

function Get-ReefVisionDesktopProcessNames {
    $processNames = @(
        "ReefVision",
        "reefvision-desktop"
    )
    foreach ($candidate in Get-ReefVisionInstalledDesktopCandidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }
        $processName = [System.IO.Path]::GetFileNameWithoutExtension($candidate)
        if (-not [string]::IsNullOrWhiteSpace($processName)) {
            $processNames += $processName
        }
    }
    return $processNames |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Select-Object -Unique
}

function Set-ReefVisionInstalledDesktopPath {
    param(
        [string]$ExecutablePath
    )

    if ([string]::IsNullOrWhiteSpace($ExecutablePath)) {
        return
    }
    if (-not (Test-Path $ExecutablePath -PathType Leaf)) {
        return
    }
    $config = Get-ReefVisionCommandConfig
    $config.installed_app_path = (Resolve-Path -LiteralPath $ExecutablePath).Path
    Save-ReefVisionCommandConfig -Config $config
}

function Get-ReefVisionUserDataDir {
    return Join-Path $env:APPDATA "org.reefvision.desktop"
}

function Get-ReefVisionLogsDir {
    return Join-Path (Get-ReefVisionUserDataDir) "logs"
}

function Get-ReefVisionRuntimePortPath {
    return Join-Path (Get-ReefVisionUserDataDir) "runtime\backend-port.txt"
}

function Get-ReefVisionApiBaseUrl {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    return "http://127.0.0.1:$Port/api/v1"
}

function Get-ReefVisionPublishedApiPort {
    $portPath = Get-ReefVisionRuntimePortPath
    if (-not (Test-Path $portPath -PathType Leaf)) {
        return $null
    }

    $raw = (Get-Content -LiteralPath $portPath -Raw).Trim()
    $parsed = 0
    if ([int]::TryParse($raw, [ref]$parsed) -and $parsed -gt 0 -and $parsed -le 65535) {
        return $parsed
    }
    return $null
}

function Invoke-ReefVisionApiJson {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port,
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [ValidateSet("GET", "POST")]
        [string]$Method = "GET",
        [object]$Body = $null,
        [int]$TimeoutSec = 3
    )

    $uri = "$(Get-ReefVisionApiBaseUrl -Port $Port)$Path"
    $parameters = @{
        Uri = $uri
        Method = $Method
        TimeoutSec = $TimeoutSec
        ErrorAction = "Stop"
    }
    if ($null -ne $Body) {
        $parameters["ContentType"] = "application/json"
        $parameters["Body"] = ($Body | ConvertTo-Json -Depth 8)
    }
    return Invoke-RestMethod @parameters
}

function Get-ReefVisionHealthSnapshot {
    $port = Get-ReefVisionPublishedApiPort
    if ($null -eq $port) {
        return @{
            available = $false
            port = $null
            api_base_url = $null
            message = "No published desktop API port file was found."
            version = $null
            safe_mode = $null
        }
    }

    try {
        $health = Invoke-ReefVisionApiJson -Port $port -Path "/health" -Method GET -TimeoutSec 3
        $systemVersion = Invoke-ReefVisionApiJson -Port $port -Path "/system/version" -Method GET -TimeoutSec 3
        return @{
            available = $true
            port = $port
            api_base_url = Get-ReefVisionApiBaseUrl -Port $port
            message = "Local desktop API is healthy."
            version = $health.version
            safe_mode = $systemVersion.safe_mode
        }
    }
    catch {
        return @{
            available = $false
            port = $port
            api_base_url = Get-ReefVisionApiBaseUrl -Port $port
            message = $_.Exception.Message
            version = $null
            safe_mode = $null
        }
    }
}

function Get-ReefVisionDesktopProcessList {
    $desktopProcessNames = @(Get-ReefVisionDesktopProcessNames)
    $desktopProcessLookup = @{}
    foreach ($name in $desktopProcessNames) {
        $desktopProcessLookup[$name] = $true
    }
    $desktop = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $desktopProcessLookup.ContainsKey($_.ProcessName)
    })
    $sidecars = @(Get-Process | Where-Object { $_.ProcessName -like "reefvision-api*" })
    return @{
        desktop = $desktop
        sidecars = $sidecars
    }
}

function Wait-ReefVisionHealth {
    param(
        [int]$Attempts = 40,
        [int]$DelayMilliseconds = 250
    )

    for ($index = 0; $index -lt $Attempts; $index += 1) {
        $snapshot = Get-ReefVisionHealthSnapshot
        if ($snapshot.available) {
            return $snapshot
        }
        Start-Sleep -Milliseconds $DelayMilliseconds
    }

    return Get-ReefVisionHealthSnapshot
}

function Start-ReefVisionExecutable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ExecutablePath,
        [switch]$SafeMode
    )

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $ExecutablePath
    $startInfo.WorkingDirectory = Split-Path -Parent $ExecutablePath
    $startInfo.UseShellExecute = $false
    if ($SafeMode) {
        $startInfo.EnvironmentVariables["REEFVISION_SAFE_MODE"] = "1"
    }
    else {
        $startInfo.EnvironmentVariables["REEFVISION_SAFE_MODE"] = "0"
    }
    [void][System.Diagnostics.Process]::Start($startInfo)
}

function Stop-ReefVisionRunningProcesses {
    $processes = Get-ReefVisionDesktopProcessList
    foreach ($process in @($processes.desktop) + @($processes.sidecars)) {
        try {
            Stop-Process -Id $process.Id -Force -ErrorAction Stop
        }
        catch {
            Write-Warning "Could not stop process $($process.ProcessName) ($($process.Id)): $($_.Exception.Message)"
        }
    }
}

function Get-ReefVisionDesktopStatus {
    param(
        [string]$InstalledExecutablePath
    )

    $desktopPath = Resolve-ReefVisionInstalledDesktopPath -PreferredPath $InstalledExecutablePath
    $processes = Get-ReefVisionDesktopProcessList
    $health = Get-ReefVisionHealthSnapshot
    $version = Get-ReefVisionExecutableVersion -ExecutablePath $desktopPath

    return [pscustomobject]@{
        command_version = $script:ReefVisionCommandVersion
        installed_version = $version
        desktop_executable = $desktopPath
        desktop_process_count = @($processes.desktop).Count
        sidecar_process_count = @($processes.sidecars).Count
        api_port = $health.port
        api_base_url = $health.api_base_url
        api_healthy = $health.available
        api_version = $health.version
        safe_mode = $health.safe_mode
        user_data_dir = Get-ReefVisionUserDataDir
        logs_dir = Get-ReefVisionLogsDir
        status_message = $health.message
    }
}

function Format-ReefVisionDesktopStatus {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Status
    )

    $installedVersion = if ($null -ne $Status.installed_version -and -not [string]::IsNullOrWhiteSpace([string]$Status.installed_version)) {
        [string]$Status.installed_version
    }
    else {
        "Unknown"
    }
    $desktopExecutable = if ($null -ne $Status.desktop_executable -and -not [string]::IsNullOrWhiteSpace([string]$Status.desktop_executable)) {
        [string]$Status.desktop_executable
    }
    else {
        "Not found"
    }
    $apiPort = if ($null -ne $Status.api_port) { [string]$Status.api_port } else { "Unknown" }
    $apiBaseUrl = if ($null -ne $Status.api_base_url -and -not [string]::IsNullOrWhiteSpace([string]$Status.api_base_url)) {
        [string]$Status.api_base_url
    }
    else {
        "Unknown"
    }
    $apiVersion = if ($null -ne $Status.api_version -and -not [string]::IsNullOrWhiteSpace([string]$Status.api_version)) {
        [string]$Status.api_version
    }
    else {
        "Unknown"
    }
    $safeMode = if ($null -ne $Status.safe_mode) { [string]$Status.safe_mode } else { "Unknown" }

    @(
        "ReefVision command version: $($Status.command_version)"
        "Installed version: $installedVersion"
        "Desktop executable: $desktopExecutable"
        "Desktop process count: $($Status.desktop_process_count)"
        "Sidecar process count: $($Status.sidecar_process_count)"
        "API port: $apiPort"
        "API base URL: $apiBaseUrl"
        "API healthy: $($Status.api_healthy)"
        "API version: $apiVersion"
        "Safe mode: $safeMode"
        "User data: $($Status.user_data_dir)"
        "Logs: $($Status.logs_dir)"
        "Status: $($Status.status_message)"
    ) -join [Environment]::NewLine
}

function Get-ReefVisionUserPathEntries {
    $raw = $null
    try {
        $raw = (Get-ItemProperty -Path "HKCU:\Environment" -Name Path -ErrorAction Stop).Path
    }
    catch {
        $raw = [Environment]::GetEnvironmentVariable("Path", "User")
    }
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return @()
    }
    return $raw.Split(";", [System.StringSplitOptions]::RemoveEmptyEntries) |
        ForEach-Object { $_.Trim() } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Select-Object -Unique
}

function Ensure-ReefVisionBinOnUserPath {
    $binDir = (Get-ReefVisionCommandBinDir)
    $normalize = {
        param([string]$Value)
        if ([string]::IsNullOrWhiteSpace($Value)) {
            return ""
        }
        return $Value.Trim().TrimEnd("\").ToLowerInvariant()
    }
    $current = @(Get-ReefVisionUserPathEntries)
    $normalizedBinDir = & $normalize $binDir
    $normalizedCurrent = @($current | ForEach-Object { & $normalize $_ })
    if ($normalizedCurrent -contains $normalizedBinDir) {
        if ($env:Path -notlike "*$binDir*") {
            $env:Path = (
                @($env:Path, $binDir) |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                ForEach-Object { $_ -split ";" } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                Select-Object -Unique
            ) -join ";"
        }
        return @{
            changed = $false
            path = ($current -join ";")
        }
    }
    $updated = @($current + $binDir) | Select-Object -Unique
    $updatedPath = $updated -join ";"
    [Environment]::SetEnvironmentVariable("Path", $updatedPath, "User")
    try {
        New-Item -Path "HKCU:\Environment" -Force | Out-Null
        New-ItemProperty -Path "HKCU:\Environment" -Name Path -PropertyType ExpandString -Value $updatedPath -Force | Out-Null
    }
    catch {
        Write-Warning "ReefVision could not write the command directory to HKCU:\\Environment: $($_.Exception.Message)"
    }

    $persistedEntries = @(Get-ReefVisionUserPathEntries)
    $normalizedPersisted = @($persistedEntries | ForEach-Object { & $normalize $_ })
    if ($normalizedPersisted -notcontains $normalizedBinDir) {
        $regExe = Join-Path $env:SystemRoot "System32\reg.exe"
        if (Test-Path $regExe -PathType Leaf) {
            try {
                & $regExe ADD HKCU\Environment /v Path /t REG_EXPAND_SZ /d $updatedPath /f | Out-Null
            }
            catch {
                Write-Warning "ReefVision could not update the user PATH through reg.exe: $($_.Exception.Message)"
            }
        }
    }

    $env:Path = (
        @($env:Path, $binDir) |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        ForEach-Object { $_ -split ";" } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Select-Object -Unique
    ) -join ";"
    return @{
        changed = $true
        path = $updatedPath
    }
}

function Test-ReefVisionManagedWrapper {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path $Path -PathType Leaf)) {
        return $false
    }
    $firstLine = Get-Content -LiteralPath $Path -TotalCount 1 -ErrorAction SilentlyContinue
    return $firstLine -like "*$script:ReefVisionManagedWrapperMarker*"
}

function New-ReefVisionUpdateLock {
    New-ReefVisionCommandDirectoryLayout
    $lockPath = Get-ReefVisionCommandLockPath
    $fileStream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    return [pscustomobject]@{
        Path = $lockPath
        Stream = $fileStream
    }
}

function Close-ReefVisionUpdateLock {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Lock
    )

    try {
        $Lock.Stream.Dispose()
    }
    finally {
        Remove-Item -LiteralPath $Lock.Path -Force -ErrorAction SilentlyContinue
    }
}
