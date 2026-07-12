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

$Arguments = @($Arguments | Where-Object {
    $null -ne $_ -and -not [string]::IsNullOrWhiteSpace([string]$_)
})

function Show-StartReefVisionHelp {
    @"
start-reefvision v$script:ReefVisionCommandVersion

Usage:
  start-reefvision
  start-reefvision --help
  start-reefvision --status
  start-reefvision --restart
  start-reefvision --safe-mode
  start-reefvision --logs
  start-reefvision --diagnostics
  start-reefvision --configure-repo PATH
  start-reefvision --dev
  start-reefvision --web-dev
  start-reefvision --api-only
  start-reefvision --no-wait
  start-reefvision --verbose
"@
}

$showHelp = $false
$showStatus = $false
$restart = $false
$safeMode = $false
$showLogs = $false
$runDiagnostics = $false
$devMode = $false
$webDevMode = $false
$apiOnly = $false
$noWait = $false
$verbose = $false
$configureRepoPath = $null

for ($index = 0; $index -lt $Arguments.Count; $index += 1) {
    switch ($Arguments[$index]) {
        "--help" { $showHelp = $true }
        "--status" { $showStatus = $true }
        "--restart" { $restart = $true }
        "--safe-mode" { $safeMode = $true }
        "--logs" { $showLogs = $true }
        "--diagnostics" { $runDiagnostics = $true }
        "--dev" { $devMode = $true }
        "--web-dev" { $webDevMode = $true }
        "--api-only" { $apiOnly = $true }
        "--no-wait" { $noWait = $true }
        "--verbose" { $verbose = $true }
        "--configure-repo" {
            $index += 1
            if ($index -ge $Arguments.Count) {
                throw "--configure-repo requires a repository path."
            }
            $configureRepoPath = $Arguments[$index]
        }
        default {
            throw "Unknown start-reefvision option: $($Arguments[$index])"
        }
    }
}

if ($showHelp) {
    Show-StartReefVisionHelp
    exit 0
}

if ($configureRepoPath) {
    $resolved = Set-ReefVisionRepoPath -RepoPath $configureRepoPath
    Write-ReefVisionCommandNote "Configured ReefVision repository: $resolved"
    if (-not ($showStatus -or $devMode -or $webDevMode -or $apiOnly)) {
        exit 0
    }
}

$selectedDevModes = @($devMode, $webDevMode, $apiOnly) | Where-Object { $_ }
if (@($selectedDevModes).Count -gt 1) {
    throw "Choose only one development mode at a time."
}

$repoPath = Resolve-ReefVisionRepoPath
if ($verbose -and $repoPath) {
    Write-ReefVisionCommandNote "Repository path: $repoPath"
}

if ($devMode -or $webDevMode -or $apiOnly) {
    if ($null -eq $repoPath) {
        throw "A ReefVision repository is required for development modes. Run start-reefvision --configure-repo PATH first."
    }

    if ($apiOnly) {
        Start-Process -FilePath "powershell.exe" -WindowStyle Normal -ArgumentList @(
            "-NoProfile",
            "-NoExit",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            (Join-Path $repoPath "scripts\dev-api.ps1")
        )
        Write-ReefVisionCommandNote "Started the ReefVision API-only development server. No application window will appear."
        exit 0
    }

    if ($devMode) {
        Start-Process -FilePath "powershell.exe" -WindowStyle Normal -ArgumentList @(
            "-NoProfile",
            "-NoExit",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            (Join-Path $repoPath "scripts\dev-desktop.ps1")
        )
        Write-ReefVisionCommandNote "Started ReefVision desktop development mode."
        exit 0
    }

    Start-Process -FilePath "powershell.exe" -WindowStyle Normal -ArgumentList @(
        "-NoProfile",
        "-NoExit",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Join-Path $repoPath "scripts\dev-api.ps1")
    )
    Start-Process -FilePath "powershell.exe" -WindowStyle Normal -ArgumentList @(
        "-NoProfile",
        "-NoExit",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Join-Path $repoPath "scripts\dev-web.ps1")
    )
    Write-ReefVisionCommandNote "Started ReefVision browser development mode."
    exit 0
}

$status = Get-ReefVisionDesktopStatus
if ($showStatus) {
    Format-ReefVisionDesktopStatus -Status $status
    exit 0
}

if ($showLogs) {
    Write-Output "Logs: $(Get-ReefVisionLogsDir)"
    if (Test-Path (Get-ReefVisionLogsDir) -PathType Container) {
        Get-ChildItem -Path (Get-ReefVisionLogsDir) -File |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 5 FullName, Length, LastWriteTimeUtc
    }
    exit 0
}

if ($runDiagnostics) {
    $health = Get-ReefVisionHealthSnapshot
    if (-not $health.available -or $null -eq $health.port) {
        throw "ReefVision diagnostics require a running local desktop API. Start ReefVision first."
    }
    $diagnostics = Invoke-ReefVisionApiJson -Port $health.port -Path "/system/diagnostics" -Method POST -Body @{
        strict_redaction = $true
    }
    Write-Output "Queued diagnostic bundle job: $($diagnostics.job.id)"
    exit 0
}

$desktopPath = Resolve-ReefVisionInstalledDesktopPath
if ($null -eq $desktopPath) {
    throw "ReefVision is not installed in a standard desktop location. Install the packaged desktop app or configure the installed executable path."
}
Set-ReefVisionInstalledDesktopPath -ExecutablePath $desktopPath

if ($restart) {
    Write-ReefVisionCommandStep "Restarting ReefVision"
    Stop-ReefVisionRunningProcesses
    Start-Sleep -Milliseconds 300
    $status = Get-ReefVisionDesktopStatus -InstalledExecutablePath $desktopPath
}
elseif ($status.desktop_process_count -gt 0) {
    Write-ReefVisionCommandNote "ReefVision is already running."
    Format-ReefVisionDesktopStatus -Status $status
    exit 0
}
elseif ($status.sidecar_process_count -gt 0) {
    Write-ReefVisionCommandNote "An orphaned ReefVision sidecar was detected. Stopping it before launch."
    Stop-ReefVisionRunningProcesses
    Start-Sleep -Milliseconds 300
}

Write-ReefVisionCommandStep "Launching ReefVision"
Write-ReefVisionCommandNote "Desktop executable: $desktopPath"
Start-ReefVisionExecutable -ExecutablePath $desktopPath -SafeMode:$safeMode

if ($noWait) {
    Write-ReefVisionCommandNote "Launch requested. Skipping the API health wait because --no-wait was provided."
    exit 0
}

$healthyStatus = Wait-ReefVisionHealth
if (-not $healthyStatus.available) {
    throw "ReefVision started but the local desktop API did not become healthy in time. $($healthyStatus.message)"
}

Format-ReefVisionDesktopStatus -Status (Get-ReefVisionDesktopStatus -InstalledExecutablePath $desktopPath)
