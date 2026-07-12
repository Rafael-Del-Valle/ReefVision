param(
    [string]$AppPath = "",
    [int]$LaunchTimeoutSeconds = 30,
    [int]$ShutdownTimeoutSeconds = 10
)

$ErrorActionPreference = "Stop"

function Get-ReefVisionProcess {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    return Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
}

function Get-ReefVisionProcessesByName {
    param([Parameter(Mandatory = $true)][string]$Name)

    return @(Get-Process -Name $Name -ErrorAction SilentlyContinue)
}

function Get-ReefVisionProcessesByPath {
    param([Parameter(Mandatory = $true)][string]$ExecutablePath)

    $processName = [System.IO.Path]::GetFileNameWithoutExtension($ExecutablePath)
    return @(Get-Process -Name $processName -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $ExecutablePath })
}

function Wait-ReefVisionCondition {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Condition,
        [Parameter(Mandatory = $true)][string]$FailureMessage,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $result = & $Condition
        if ($result) {
            return $result
        }
        Start-Sleep -Milliseconds 250
    }

    throw $FailureMessage
}

function Assert-ReefVisionProcessCounts {
    param(
        [Parameter(Mandatory = $true)][string]$DesktopProcessName,
        [Parameter(Mandatory = $true)][string]$BackendExecutablePath,
        [Parameter(Mandatory = $true)][int]$ExpectedDesktopCount,
        [Parameter(Mandatory = $true)][int]$MinimumBackendCount,
        [Parameter(Mandatory = $true)][int]$MaximumBackendCount
    )

    $desktopCount = (Get-ReefVisionProcessesByName -Name $DesktopProcessName).Count
    if ($desktopCount -ne $ExpectedDesktopCount) {
        throw "Expected exactly $ExpectedDesktopCount $DesktopProcessName process(es), but found $desktopCount."
    }

    $backendCount = (Get-ReefVisionProcessesByPath -ExecutablePath $BackendExecutablePath).Count
    if ($backendCount -lt $MinimumBackendCount -or $backendCount -gt $MaximumBackendCount) {
        throw "Expected between $MinimumBackendCount and $MaximumBackendCount reefvision-api.exe process(es) from $BackendExecutablePath, but found $backendCount."
    }
}

function Start-ReefVisionInstance {
    param(
        [Parameter(Mandatory = $true)][string]$ExecutablePath,
        [Parameter(Mandatory = $true)][string]$DesktopProcessName,
        [Parameter(Mandatory = $true)][string]$BackendExecutablePath,
        [Parameter(Mandatory = $true)][int]$LaunchTimeoutSeconds
    )

    $desktopProcess = Start-Process -FilePath $ExecutablePath -PassThru
    Write-Host "Launched ReefVision.exe (PID $($desktopProcess.Id))." -ForegroundColor DarkGray

    $desktopProcess = Wait-ReefVisionCondition -TimeoutSeconds $LaunchTimeoutSeconds -FailureMessage "ReefVision.exe did not stay running long enough for the smoke test." -Condition {
        $process = Get-ReefVisionProcess -ProcessId $desktopProcess.Id
        if ($null -eq $process -or $process.HasExited) {
            return $null
        }
        return $process
    }

    $desktopProcess = Wait-ReefVisionCondition -TimeoutSeconds $LaunchTimeoutSeconds -FailureMessage "ReefVision did not expose a main window handle in time." -Condition {
        $process = Get-ReefVisionProcess -ProcessId $desktopProcess.Id
        if ($null -eq $process -or $process.HasExited -or $process.MainWindowHandle -eq 0) {
            return $null
        }
        return $process
    }

    Wait-ReefVisionCondition -TimeoutSeconds $LaunchTimeoutSeconds -FailureMessage "reefvision-api.exe did not start in time." -Condition {
        $backendProcesses = Get-ReefVisionProcessesByPath -ExecutablePath $BackendExecutablePath
        if ($backendProcesses.Count -lt 1) {
            return $null
        }
        return $true
    }

    Start-Sleep -Seconds 2
    $backendProcesses = Get-ReefVisionProcessesByPath -ExecutablePath $BackendExecutablePath
    Assert-ReefVisionProcessCounts -DesktopProcessName $DesktopProcessName -BackendExecutablePath $BackendExecutablePath -ExpectedDesktopCount 1 -MinimumBackendCount 1 -MaximumBackendCount 2

    return [PSCustomObject]@{
        DesktopProcess = $desktopProcess
        BackendProcessIds = @($backendProcesses | ForEach-Object { $_.Id } | Sort-Object)
    }
}

function Close-ReefVisionInstance {
    param(
        [Parameter(Mandatory = $true)]$DesktopProcess,
        [Parameter(Mandatory = $true)][string]$BackendExecutablePath,
        [Parameter(Mandatory = $true)][int]$ShutdownTimeoutSeconds
    )

    if (-not $DesktopProcess.CloseMainWindow()) {
        throw "ReefVision.exe did not accept a normal main-window close request."
    }

    Write-Host "Requested a normal ReefVision window close." -ForegroundColor DarkGray

    Wait-ReefVisionCondition -TimeoutSeconds $ShutdownTimeoutSeconds -FailureMessage "ReefVision.exe did not exit after a normal close request." -Condition {
        $process = Get-ReefVisionProcess -ProcessId $DesktopProcess.Id
        if ($null -eq $process -or $process.HasExited) {
            return $true
        }
        return $null
    } | Out-Null

    Wait-ReefVisionCondition -TimeoutSeconds $ShutdownTimeoutSeconds -FailureMessage "reefvision-api.exe remained running after ReefVision closed." -Condition {
        $processes = Get-ReefVisionProcessesByPath -ExecutablePath $BackendExecutablePath
        if ($processes.Count -eq 0) {
            return $true
        }
        return $null
    } | Out-Null
}

$candidateAppPaths = @(
    $AppPath,
    (Join-Path $env:LOCALAPPDATA "ReefVision\reefvision-desktop.exe"),
    (Join-Path $env:LOCALAPPDATA "ReefVision\ReefVision.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\ReefVision\reefvision-desktop.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\ReefVision\ReefVision.exe")
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

$resolvedAppPath = $null
foreach ($candidate in $candidateAppPaths) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $resolvedAppPath = (Resolve-Path -LiteralPath $candidate).Path
        break
    }
}

if ($null -eq $resolvedAppPath) {
    throw "ReefVision executable not found. Pass -AppPath with the installed or built desktop executable path."
}

$desktopProcessName = [System.IO.Path]::GetFileNameWithoutExtension($resolvedAppPath)
$backendExecutablePath = Join-Path (Split-Path -Parent $resolvedAppPath) "reefvision-api.exe"
$baselineDesktopProcesses = Get-ReefVisionProcessesByName -Name $desktopProcessName
$baselineBackendProcesses = Get-ReefVisionProcessesByPath -ExecutablePath $backendExecutablePath
if ($baselineDesktopProcesses.Count -gt 0 -or $baselineBackendProcesses.Count -gt 0) {
    throw "Close any existing ReefVision desktop or reefvision-api.exe processes before running the shutdown smoke test."
}

$desktopProcess = $null
$startedDesktopProcessIds = [System.Collections.Generic.List[int]]::new()
$startedBackendProcessIds = [System.Collections.Generic.List[int]]::new()

try {
    $instance = Start-ReefVisionInstance -ExecutablePath $resolvedAppPath -DesktopProcessName $desktopProcessName -BackendExecutablePath $backendExecutablePath -LaunchTimeoutSeconds $LaunchTimeoutSeconds
    $desktopProcess = $instance.DesktopProcess
    $startedDesktopProcessIds.Add($desktopProcess.Id)
    foreach ($backendProcessId in $instance.BackendProcessIds) {
        $startedBackendProcessIds.Add($backendProcessId)
    }
    $expectedBackendIds = @($instance.BackendProcessIds | Sort-Object)

    $secondLaunchProcess = Start-Process -FilePath $resolvedAppPath -PassThru
    $startedDesktopProcessIds.Add($secondLaunchProcess.Id)
    Wait-ReefVisionCondition -TimeoutSeconds 10 -FailureMessage "Launching a second ReefVision instance created an extra desktop or backend process." -Condition {
        $duplicateProcess = Get-ReefVisionProcess -ProcessId $secondLaunchProcess.Id
        $desktopCount = (Get-ReefVisionProcessesByName -Name $desktopProcessName).Count
        $currentBackendIds = @(Get-ReefVisionProcessesByPath -ExecutablePath $backendExecutablePath | ForEach-Object { $_.Id } | Sort-Object)
        $backendIdsUnchanged = ($currentBackendIds.Count -eq $expectedBackendIds.Count) -and -not (Compare-Object $expectedBackendIds $currentBackendIds)
        if (($null -eq $duplicateProcess -or $duplicateProcess.HasExited) -and $desktopCount -eq 1 -and $backendIdsUnchanged) {
            return $true
        }
        return $null
    } | Out-Null
    Write-Host "Verified that launching a second instance did not create a second backend." -ForegroundColor DarkGray

    Close-ReefVisionInstance -DesktopProcess $desktopProcess -BackendExecutablePath $backendExecutablePath -ShutdownTimeoutSeconds $ShutdownTimeoutSeconds

    Assert-ReefVisionProcessCounts -DesktopProcessName $desktopProcessName -BackendExecutablePath $backendExecutablePath -ExpectedDesktopCount 0 -MinimumBackendCount 0 -MaximumBackendCount 0

    $instance = Start-ReefVisionInstance -ExecutablePath $resolvedAppPath -DesktopProcessName $desktopProcessName -BackendExecutablePath $backendExecutablePath -LaunchTimeoutSeconds $LaunchTimeoutSeconds
    $desktopProcess = $instance.DesktopProcess
    $startedDesktopProcessIds.Add($desktopProcess.Id)
    foreach ($backendProcessId in $instance.BackendProcessIds) {
        $startedBackendProcessIds.Add($backendProcessId)
    }

    Close-ReefVisionInstance -DesktopProcess $desktopProcess -BackendExecutablePath $backendExecutablePath -ShutdownTimeoutSeconds $ShutdownTimeoutSeconds

    Write-Host "Desktop shutdown smoke test passed: reefvision-api.exe exited with the ReefVision window." -ForegroundColor Green
}
finally {
    foreach ($processId in $startedDesktopProcessIds | Select-Object -Unique) {
        $desktopCleanup = Get-ReefVisionProcess -ProcessId $processId
        if ($null -ne $desktopCleanup -and -not $desktopCleanup.HasExited) {
            Stop-Process -Id $desktopCleanup.Id -Force
        }
    }

    $residualBackendIds = @(Get-ReefVisionProcessesByPath -ExecutablePath $backendExecutablePath | ForEach-Object { $_.Id })
    foreach ($processId in @($startedBackendProcessIds + $residualBackendIds) | Select-Object -Unique) {
        $backendCleanup = Get-ReefVisionProcess -ProcessId $processId
        if ($null -ne $backendCleanup -and -not $backendCleanup.HasExited) {
            Stop-Process -Id $backendCleanup.Id -Force
        }
    }
}
