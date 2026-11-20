Set-StrictMode -Version Latest

function Get-ReefVisionLoopbackDebugPort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return $listener.LocalEndpoint.Port
    } finally {
        $listener.Stop()
    }
}

function Get-ReefVisionWebView2DiagnosticArguments([string]$CommandLine) {
    # Keep only debug transport flags. Raw argv may contain tokens or profile paths.
    $debugPort = if ($CommandLine -match '(?:^|[\s"])--remote-debugging-port="?([0-9]{1,5})(?=$|[\s"])') {
        [int]$Matches[1]
    } else { $null }
    $debugAddress = if ($CommandLine -match '(?:^|[\s"])--remote-debugging-address="?([^\s"]+)') {
        if ($Matches[1] -in @('127.0.0.1', '::1')) { $Matches[1] } else { 'other' }
    } else { $null }
    return [ordered]@{
        remote_debugging_port = $debugPort
        remote_debugging_address = $debugAddress
        user_data_dir_arg_present = $CommandLine -match '(?:^|[\s"])--user-data-dir='
    }
}

function Write-ReefVisionWebView2StartupFailure {
    param(
        [string]$Path,
        [int]$Port,
        [int]$DesktopProcessId,
        [Nullable[datetime]]$DesktopStartedUtc,
        [long]$WaitMilliseconds,
        [object[]]$ObservedListeners,
        [System.Collections.IDictionary]$Probe
    )

    $launch = Get-Process -Id $PID -ErrorAction SilentlyContinue
    $desktop = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $DesktopProcessId AND Name = 'ReefVision.exe'" -ErrorAction SilentlyContinue
    $desktopOwner = $null
    $hasMainWindow = $null
    $responding = $null
    if ($desktop) {
        $desktopOwner = Invoke-CimMethod -InputObject $desktop -MethodName GetOwner -ErrorAction SilentlyContinue
        try {
            $desktopWindow = Get-Process -Id $DesktopProcessId -ErrorAction Stop
            $hasMainWindow = $desktopWindow.MainWindowHandle -ne [IntPtr]::Zero
            $responding = $desktopWindow.Responding
        } catch {
            # The process may have exited after the CIM lookup.
        }
    }
    $children = @(Get-CimInstance -ClassName Win32_Process -Filter "ParentProcessId = $DesktopProcessId AND Name = 'msedgewebview2.exe'" -ErrorAction SilentlyContinue)
    $now = [DateTime]::UtcNow
    $evidence = [ordered]@{
        expected_port = $Port
        checked_at_utc = $now.ToString('o')
        wait_milliseconds = $WaitMilliseconds
        desktop_elapsed_milliseconds = if ($null -ne $DesktopStartedUtc) { [long]($now - $DesktopStartedUtc).TotalMilliseconds } else { $null }
        launch = [ordered]@{
            user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
            pid = $PID
            session_id = if ($launch) { $launch.SessionId } else { $null }
        }
        desktop = [ordered]@{
            pid = $DesktopProcessId
            found = [bool]$desktop
            executable = if ($desktop) { $desktop.ExecutablePath } else { $null }
            parent_pid = if ($desktop) { $desktop.ParentProcessId } else { $null }
            session_id = if ($desktop) { $desktop.SessionId } else { $null }
            owner = if ($desktopOwner -and $desktopOwner.ReturnValue -eq 0) { "$($desktopOwner.Domain)\$($desktopOwner.User)" } else { $null }
            has_main_window = $hasMainWindow
            responding = $responding
        }
        webview2_children = @($children | ForEach-Object {
            [ordered]@{
                pid = $_.ProcessId
                parent_pid = $_.ParentProcessId
                session_id = $_.SessionId
                executable = $_.ExecutablePath
                arguments = Get-ReefVisionWebView2DiagnosticArguments $_.CommandLine
            }
        })
        listeners = $ObservedListeners
        version_probe = $Probe
    }
    $evidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding utf8
}

function Wait-ReefVisionWebView2DebugEndpoint {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][int]$DesktopProcessId,
        [string]$FailureEvidencePath
    )

    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    $desktopStartedUtc = $null
    if ($FailureEvidencePath) {
        try {
            $initialDesktop = Get-Process -Id $DesktopProcessId -ErrorAction Stop
            if ($initialDesktop.ProcessName -ieq 'ReefVision') {
                $desktopStartedUtc = $initialDesktop.StartTime.ToUniversalTime()
            }
        } catch {
            # Metadata is best-effort and does not gate the actual attach.
        }
    }
    $observedListeners = @()
    $probe = [ordered]@{ attempt_count = 0; result = 'not_attempted'; status = $null; error_type = $null }
    try {
        do {
            $tcpErrors = @()
            $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue -ErrorVariable tcpErrors)
            if ($listeners.Count -gt 0) { $observedListeners = @() }
            foreach ($listener in $listeners) {
                $observation = [ordered]@{
                    address = $listener.LocalAddress
                    pid = $listener.OwningProcess
                    owner_name = $null
                    owner_parent_pid = $null
                    expected_owner = $false
                }
                $observedListeners += $observation
                if ($listener.LocalAddress -notin @('127.0.0.1', '::1')) {
                    throw "WebView2 debugging is not limited to loopback on port $Port."
                }
                $owner = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
                if ($owner) {
                    $observation.owner_name = $owner.Name
                    $observation.owner_parent_pid = $owner.ParentProcessId
                    $observation.expected_owner = $owner.Name -ieq 'msedgewebview2.exe' -and $owner.ParentProcessId -eq $DesktopProcessId
                }
                if (-not $observation.expected_owner) {
                    throw "The listener on port $Port does not belong to this acceptance WebView2 process."
                }
            }
            if ($listeners.Count -gt 0 -and $listeners.LocalAddress -contains '127.0.0.1') {
                $version = $null
                $debugHttpStatus = $null
                $probe.attempt_count++
                $probe.status = $null
                $probe.error_type = $null
                try {
                    $version = Invoke-RestMethod "http://127.0.0.1:$Port/json/version" -NoProxy -TimeoutSec 3 -StatusCodeVariable debugHttpStatus
                    $probe.status = $debugHttpStatus
                    $probe.result = if ($version) { 'json_received' } else { 'empty_response' }
                } catch {
                    # Record error type and status only. A response or error message can contain secrets.
                    $probe.result = 'request_failed'
                    $probe.error_type = $_.Exception.GetType().Name
                    $response = $_.Exception.PSObject.Properties['Response']
                    if ($response -and $response.Value -and $response.Value.PSObject.Properties['StatusCode']) {
                        $probe.status = [int]$response.Value.StatusCode
                    }
                }
                if ($version) {
                    $property = $version.PSObject.Properties['webSocketDebuggerUrl']
                    $endpoint = if ($property) { [string]$property.Value } else { '' }
                    if ($endpoint -notmatch "^ws://127[.]0[.]0[.]1:$Port/devtools/browser/[a-f0-9-]+$") {
                        $probe.result = 'unexpected_endpoint'
                        throw 'WebView2 reported an unexpected debugger endpoint.'
                    }
                    return $endpoint
                }
            }
            Start-Sleep -Milliseconds 250
        } while ($timer.Elapsed.TotalSeconds -lt 30)

        throw "WebView2 did not publish a loopback debugging endpoint on port $Port."
    } catch {
        if ($FailureEvidencePath) {
            $probe.last_listener_lookup_error_id = if ($tcpErrors.Count -gt 0) { [string]$tcpErrors[-1].FullyQualifiedErrorId } else { $null }
            try {
                Write-ReefVisionWebView2StartupFailure -Path $FailureEvidencePath -Port $Port `
                    -DesktopProcessId $DesktopProcessId -DesktopStartedUtc $desktopStartedUtc `
                    -WaitMilliseconds $timer.ElapsedMilliseconds -ObservedListeners $observedListeners -Probe $probe
            } catch {
                Write-Warning 'Could not collect sanitized WebView2 startup diagnostics.'
            }
        }
        throw
    }
}

function Wait-ReefVisionWebView2DebugClosure([int]$Port) {
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
            return
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "WebView2 debugging was still listening on port $Port after the acceptance desktop closed."
}

function Get-ReefVisionInstalledJourneyEvidence([scriptblock]$RunJourney) {
    try {
        $result = & $RunJourney
        $detail = "Installed WebView2 passed $($result.completed_journeys) desktop journeys. Two synthetic originals were reviewed and compared in graph $($result.graph_record_id), runs $($result.first_run_id) and $($result.replay_run_id), with downloaded comparison SHA-256 $($result.artifact.payload_sha256)."
        return New-ReefVisionEvidenceResult -Status 'PASS' -Detail $detail
    } catch {
        return New-ReefVisionEvidenceResult -Status 'FAIL' -Detail $_.Exception.Message
    }
}

function Invoke-ReefVisionSpatialWebView2Acceptance {
    param(
        [Parameter(Mandatory = $true)][string]$NodePath,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$EvidenceRoot,
        [Parameter(Mandatory = $true)][string]$Api,
        [Parameter(Mandatory = $true)][int]$DebugPort,
        [Parameter(Mandatory = $true)][int]$DesktopProcessId
    )

    $endpoint = Wait-ReefVisionWebView2DebugEndpoint -Port $DebugPort -DesktopProcessId $DesktopProcessId `
        -FailureEvidencePath (Join-Path $EvidenceRoot 'spatial-webview2-startup.log')
    $playwrightRoot = Join-Path $RepositoryRoot 'apps\web'
    $playwrightCli = Join-Path $playwrightRoot 'node_modules\@playwright\test\cli.js'
    $output = Join-Path $EvidenceRoot 'spatial-playwright'
    $log = Join-Path $EvidenceRoot 'spatial-playwright.log'
    $report = Join-Path $EvidenceRoot 'spatial-playwright.json'
    $variables = @{
        REEFVISION_GUIDED_TEST_API = $Api
        REEFVISION_SPATIAL_WEBVIEW2_ENDPOINT = $endpoint
        PLAYWRIGHT_JSON_OUTPUT_FILE = $report
    }
    $previous = @{}
    foreach ($name in $variables.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $variables[$name], 'Process')
    }
    Push-Location -LiteralPath $playwrightRoot
    try {
        # Only the test driver uses the absolute Node path. The existing MSI
        # and desktop/sidecar processes still inherit the restricted PATH.
        $specs = @(
            'spatial-guided-workflow-live.spec.ts',
            'project-spatial-comparison-live.spec.ts',
            'anatomical-branch-live.spec.ts',
            'spatial-condition-live.spec.ts',
            'reviewed-coral-growth-live.spec.ts',
            'paired-growth-contrast-live.spec.ts',
            'dataset-export-layout-live.spec.ts',
            'ordinary-project-live.spec.ts'
        )
        & $NodePath $playwrightCli test @specs --workers=1 --retries=0 --reporter=list,json --output=$output *> $log
        if ($LASTEXITCODE -ne 0) {
            $tail = Get-Content -LiteralPath $log -Tail 25 | Out-String
            throw "Packaged WebView2 spatial workflow failed with exit code $LASTEXITCODE. $tail"
        }
    } finally {
        Pop-Location
        foreach ($name in $variables.Keys) {
            [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
        }
    }

    $stats = (Get-Content -LiteralPath $report -Raw | ConvertFrom-Json).stats
    if ($stats.expected -ne $specs.Count -or $stats.skipped -ne 0 -or $stats.unexpected -ne 0) {
        throw 'Every requested packaged desktop journey must execute successfully.'
    }
    $results = @(Get-ChildItem -LiteralPath $output -Recurse -File -Filter 'spatial-workflow.json')
    if ($results.Count -ne 1) { throw 'Expected one completed two-acquisition spatial replay report.' }
    $result = Get-Content -LiteralPath $results[0].FullName -Raw | ConvertFrom-Json
    if ($result.surface -ne 'tauri-webview2') { throw 'The spatial replay did not run in ReefVision WebView2.' }
    $result | Add-Member -NotePropertyName completed_journeys -NotePropertyValue $stats.expected
    return $result
}
