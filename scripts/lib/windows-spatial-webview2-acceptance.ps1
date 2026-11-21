Set-StrictMode -Version Latest

function Get-ReefVisionStudyDesignJourneyTitle {
    return 'study design freezes, reopens, exports and replays a reviewed declaration'
}

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
        [string]$FailureEvidencePath,
        [string]$AttachmentEvidencePath,
        [string]$ExpectedBrowserSid
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
                    owner_sid = $null
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
                    if ($observation.expected_owner -and $ExpectedBrowserSid) {
                        $browserOwner = Invoke-CimMethod -InputObject $owner -MethodName GetOwnerSid
                        $observation.owner_sid = $browserOwner.Sid
                        $observation.expected_owner = $browserOwner.ReturnValue -eq 0 -and $browserOwner.Sid -eq $ExpectedBrowserSid
                    }
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
                    if ($AttachmentEvidencePath) {
                        [ordered]@{port=$Port; desktop_pid=$DesktopProcessId; listeners=$observedListeners} |
                            ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $AttachmentEvidencePath -Encoding utf8
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
        $detail = "Installed WebView2 passed $($result.completed_journeys) desktop journeys. Reviewed graph $($result.graph_record_id) ran as $($result.first_run_id) and $($result.replay_run_id) with comparison SHA-256 $($result.artifact.payload_sha256). Scratch detector $($result.ordinary_detector.model_id) produced checkpoint SHA-256 $($result.ordinary_detector.checkpoint_sha256). Managed restore job $($result.backup_restore.restore_job_id) recovered $($result.backup_restore.restored_files) verified files."
        return New-ReefVisionEvidenceResult -Status 'PASS' -Detail $detail
    } catch {
        return New-ReefVisionEvidenceResult -Status 'FAIL' -Detail $_.Exception.Message
    }
}

function Invoke-ReefVisionInstalledPlaywrightSuite {
    param(
        [Parameter(Mandatory)][string]$NodePath,
        [Parameter(Mandatory)][string]$RepositoryRoot,
        [Parameter(Mandatory)][string]$EvidenceRoot,
        [Parameter(Mandatory)][string]$Api,
        [Parameter(Mandatory)][int]$DebugPort,
        [Parameter(Mandatory)][int]$DesktopProcessId,
        [Parameter(Mandatory)][ValidateSet('first-use', 'workspace', 'schedule-before', 'schedule-after', 'monitoring', 'research-tools')][string]$Suite,
        [Parameter(Mandatory)][string[]]$Specs,
        [string]$ExpectedBrowserSid,
        [string]$BrowserArtifactsDirectory,
        [hashtable]$AdditionalEnvironment = @{}
    )
    $endpoint = Wait-ReefVisionWebView2DebugEndpoint -Port $DebugPort -DesktopProcessId $DesktopProcessId `
        -ExpectedBrowserSid $ExpectedBrowserSid -FailureEvidencePath (Join-Path $EvidenceRoot "$Suite-webview2-startup.log") `
        -AttachmentEvidencePath (Join-Path $EvidenceRoot "$Suite-webview2-attached.log")
    $report = Join-Path $EvidenceRoot "$Suite-playwright.json"
    $log = Join-Path $EvidenceRoot "$Suite-playwright.log"
    $output = Join-Path $EvidenceRoot "$Suite-playwright"
    $variables = @{
        REEFVISION_GUIDED_TEST_API = $Api
        REEFVISION_SPATIAL_WEBVIEW2_ENDPOINT = $endpoint
        REEFVISION_SPATIAL_WEBVIEW2_ARTIFACTS_DIR = $BrowserArtifactsDirectory
        REEFVISION_FIRST_USE_ACCEPTANCE = if ($Suite -eq 'first-use') { '1' } else { '0' }
        PLAYWRIGHT_JSON_OUTPUT_FILE = $report
    }
    foreach ($key in $AdditionalEnvironment.Keys) {
        if ($variables.ContainsKey($key)) { throw "Cannot override installed Playwright binding $key." }
        $variables[$key] = $AdditionalEnvironment[$key]
    }
    $previous = @{}
    Push-Location -LiteralPath (Join-Path $RepositoryRoot 'apps/web')
    try {
        foreach ($name in $variables.Keys) {
            $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
            [Environment]::SetEnvironmentVariable($name, $variables[$name], 'Process')
        }
        $trace = if ($Suite -eq 'research-tools') { @('--trace=off') } else { @() }
        & $NodePath 'node_modules/@playwright/test/cli.js' test @Specs @trace --workers=1 --retries=0 --reporter=list,json --output=$output *> $log
        if ($LASTEXITCODE -ne 0) {
            $tail = Get-Content -LiteralPath $log -Tail 25 | Out-String
            throw "Installed $Suite journeys failed with exit code $LASTEXITCODE. $tail"
        }
    } finally {
        Pop-Location
        foreach ($name in $previous.Keys) {
            [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
        }
    }
    $stats = (Get-Content -LiteralPath $report -Raw | ConvertFrom-Json).stats
    if ($stats.expected -ne $Specs.Count -or $stats.skipped -ne 0 -or $stats.unexpected -ne 0 -or $stats.flaky -ne 0) {
        throw "Every installed $Suite journey must execute successfully."
    }
    return $output
}

function Invoke-ReefVisionFirstUseAcceptance {
    param(
        [Parameter(Mandatory)][string]$NodePath,
        [Parameter(Mandatory)][string]$RepositoryRoot,
        [Parameter(Mandatory)][string]$EvidenceRoot,
        [Parameter(Mandatory)][string]$Api,
        [Parameter(Mandatory)][int]$DebugPort,
        [Parameter(Mandatory)][int]$DesktopProcessId,
        [Parameter(Mandatory)][string]$ExpectedVersion,
        [string]$ExpectedBrowserSid,
        [string]$BrowserArtifactsDirectory
    )
    $output = Invoke-ReefVisionInstalledPlaywrightSuite -NodePath $NodePath -RepositoryRoot $RepositoryRoot `
        -EvidenceRoot $EvidenceRoot -Api $Api -DebugPort $DebugPort -DesktopProcessId $DesktopProcessId `
        -ExpectedBrowserSid $ExpectedBrowserSid -BrowserArtifactsDirectory $BrowserArtifactsDirectory `
        -Suite 'first-use' -Specs @('ordinary-project-live.spec.ts')
    $files = @(Get-ChildItem -LiteralPath $output -Recurse -File -Filter 'first-use-evidence.json')
    if ($files.Count -ne 1) {
        throw 'The installed first-use suite must produce exactly one passing native receipt.'
    }
    $proof = Get-Content -LiteralPath $files[0].FullName -Raw | ConvertFrom-Json
    if ($proof.surface -ne 'tauri-webview2' -or $proof.application_version -ne $ExpectedVersion -or
        $proof.empty_before_project_submission -ne $true -or $proof.welcome_focus_handoff -ne $true -or
        $proof.startup_dismissal_persisted -ne $true -or $proof.emulated_device_scale_factor -ne 1.5 -or
        !$proof.nonlocal_browser_http_blocked -or $proof.external_http_attempt_count -ne 0 -or
        $proof.annotation_status -ne 'reviewed' -or $proof.image_sha256 -notmatch '^[a-f0-9]{64}$' -or
        $proof.export_sha256 -notmatch '^[a-f0-9]{64}$') {
        throw 'The first-use receipt lacks the fresh-profile, keyboard, scale, offline, review or export evidence.'
    }
    return $proof
}

function Invoke-ReefVisionWorkspaceAcceptance {
    param(
        [Parameter(Mandatory)][string]$NodePath,
        [Parameter(Mandatory)][string]$RepositoryRoot,
        [Parameter(Mandatory)][string]$EvidenceRoot,
        [Parameter(Mandatory)][string]$Api,
        [Parameter(Mandatory)][int]$DebugPort,
        [Parameter(Mandatory)][int]$DesktopProcessId,
        [Parameter(Mandatory)][string]$Profile,
        [Parameter(Mandatory)][string]$Version,
        [Parameter(Mandatory)][string]$Revision,
        [string]$ExpectedBrowserSid,
        [string]$BrowserArtifactsDirectory
    )
    $journeys = [ordered]@{
        help_handoff = @('project-help-handoff-live.spec.ts', 'help-handoff-evidence.json')
        class_lifecycle = @('safe-class-lifecycle-live.spec.ts', 'class-lifecycle-evidence.json')
        quality_control = @('qc-review-workflow-live.spec.ts', 'qc-review-workflow.json')
        dense_image = @('dense-image-live.spec.ts', 'dense-image-evidence.json')
        manual_video = @('manual-video-editor-live.spec.ts', 'manual-video-editor-evidence.json')
        editor_decisions = @('editor-confirmations-live.spec.ts', 'editor-confirmation-evidence.json')
    }
    $specs = @($journeys.Values | ForEach-Object { $_[0] })
    $output = Invoke-ReefVisionInstalledPlaywrightSuite -NodePath $NodePath -RepositoryRoot $RepositoryRoot `
        -EvidenceRoot $EvidenceRoot -Api $Api -DebugPort $DebugPort -DesktopProcessId $DesktopProcessId `
        -ExpectedBrowserSid $ExpectedBrowserSid -BrowserArtifactsDirectory $BrowserArtifactsDirectory `
        -Suite 'workspace' -Specs $specs -AdditionalEnvironment @{
            REEFVISION_RESEARCH_TEST_PROFILE=$Profile
            REEFVISION_RESEARCH_TEST_VERSION=$Version
            REEFVISION_RESEARCH_TEST_SCHEMA=$Revision
        }
    $result = [ordered]@{surface = 'tauri-webview2'; completed_journeys = $specs.Count}
    foreach ($key in $journeys.Keys) {
        $files = @(Get-ChildItem -LiteralPath $output -Recurse -File -Filter $journeys[$key][1])
        if ($files.Count -ne 1) { throw "Expected a single installed workspace receipt for $key." }
        $receipt = Get-Content -LiteralPath $files[0].FullName -Raw | ConvertFrom-Json
        if ($receipt.surface -ne $result.surface) { throw "The $key receipt was not produced by installed ReefVision WebView2." }
        $result[$key] = $receipt
    }
    $help = $result.help_handoff
    if ($help.application_version -cne $Version -or $help.schema_revision -cne $Revision -or
        [IO.Path]::GetFullPath($help.profile) -ine [IO.Path]::GetFullPath($Profile) -or
        ($help.selected_tabs -join ',') -cne 'Classes,Review queue,Workflow builder' -or
        !$help.system_keyboard_handoff -or !$help.collapsed_rail_focus -or $help.device_scale_factor -ne 1.5) {
        throw 'The installed keyboard Help journey did not reopen each workspace in the requested disposable profile.'
    }
    $sha = '^[a-f0-9]{64}$'
    $classes = $result.class_lifecycle
    if ($classes.explicit_confirmation -ne $true -or $classes.frozen.archive_sha256 -notmatch $sha -or
        $classes.frozen.manifest_sha256 -notmatch $sha -or
        $classes.original_sha256 -notmatch $sha -or $classes.reassign.final_revision -le $classes.reassign.original_revision) {
        throw 'Class lifecycle receipt lacks the verified original, revised annotation or frozen export.'
    }
    $qc = $result.quality_control
    if ($qc.explicit_completion_confirmed -ne $true -or
        $qc.dataset_manifest_sha256 -notmatch $sha -or $qc.graph_sha256 -notmatch $sha -or
        @($qc.runs).Count -ne 2 -or $qc.runs[0].id -eq $qc.runs[1].id -or
        $qc.runs[0].payload_sha256 -notmatch $sha -or $qc.runs[1].payload_sha256 -notmatch $sha) {
        throw 'QC receipt lacks the frozen dataset or both saved ranked review runs.'
    }
    $dense = $result.dense_image
    if ($dense.original_sha256 -notmatch $sha -or $dense.persisted_box_count -ne 1500 -or
        $dense.hidden_unchanged_count -ne 750 -or $dense.object_page_size -ne 200 -or $dense.last_object_position -ne 1500 -or
        $dense.rendered_at_zoom -lt 1 -or $dense.rendered_at_zoom -ge 750 -or
        $dense.editor_reopened -ne $true -or $dense.pointer_undo_redo_verified -ne $true) {
        throw 'Dense image receipt lacks bounded display, real pointer and undo/redo evidence or persisted source coordinates.'
    }
    $video = $result.manual_video
    if ($video.video.sha256 -notmatch $sha -or $video.video.frames -lt 2 -or $video.export_sha256 -notmatch $sha -or
        $video.track.reopened_rev -le $video.track.saved_rev -or $video.track.saved_rev -le $video.track.from_rev -or
        $video.stale_http_status -ne 409 -or @($video.hidden_track.keyframes).Count -lt 1) {
        throw 'Manual video receipt lacks playable-source identity, saved revisions, stale rejection or hidden geometry.'
    }
    $editor = $result.editor_decisions
    $uuid = '^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
    if ($editor.image_id -notmatch $uuid -or $editor.persisted_mask_id -notmatch $uuid -or
        $editor.persisted_revision -ne 3 -or $editor.box_after_confirmed_reload -ne 9 -or
        @($editor.conflicts).Count -ne 2 -or @($editor.conflicts | Where-Object { $_ -ne 409 }).Count -ne 0 -or
        $editor.canceled_preserved_drafts_and_undo -ne $true) {
        throw 'Editor decisions receipt lacks both real revision conflicts, the approved reload, or the unchanged saved mask and cancelled drafts.'
    }
    return [pscustomobject]$result
}

function Invoke-ReefVisionSpatialWebView2Acceptance {
    param(
        [Parameter(Mandatory = $true)][string]$NodePath,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$EvidenceRoot,
        [Parameter(Mandatory = $true)][string]$Api,
        [Parameter(Mandatory = $true)][int]$DebugPort,
        [Parameter(Mandatory = $true)][int]$DesktopProcessId,
        [string]$ExpectedBrowserSid,
        [string]$BrowserArtifactsDirectory
    )

    $endpoint = Wait-ReefVisionWebView2DebugEndpoint -Port $DebugPort -DesktopProcessId $DesktopProcessId `
        -FailureEvidencePath (Join-Path $EvidenceRoot 'spatial-webview2-startup.log') `
        -AttachmentEvidencePath (Join-Path $EvidenceRoot 'spatial-webview2-attached.log') -ExpectedBrowserSid $ExpectedBrowserSid
    $playwrightRoot = Join-Path $RepositoryRoot 'apps\web'
    $playwrightCli = Join-Path $playwrightRoot 'node_modules\@playwright\test\cli.js'
    $output = Join-Path $EvidenceRoot 'spatial-playwright'
    $log = Join-Path $EvidenceRoot 'spatial-playwright.log'
    $report = Join-Path $EvidenceRoot 'spatial-playwright.json'
    $variables = @{
        REEFVISION_GUIDED_TEST_API = $Api
        REEFVISION_SPATIAL_WEBVIEW2_ENDPOINT = $endpoint
        # Share only CDP browser artifacts. Keep the driver's temporary files private.
        REEFVISION_SPATIAL_WEBVIEW2_ARTIFACTS_DIR = $BrowserArtifactsDirectory
        REEFVISION_ORDINARY_DETECTOR_ACCEPTANCE = '1'
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
            'ordinary-project-live.spec.ts',
            'ordinary-detector-live.spec.ts',
            'backup-restore-live.spec.ts'
        )
        $studyDesign = [regex]::Escape((Get-ReefVisionStudyDesignJourneyTitle)) + '$'
        & $NodePath $playwrightCli test @specs --grep-invert $studyDesign --workers=1 --retries=0 --reporter=list,json --output=$output *> $log
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
    $detectorFiles = @(Get-ChildItem -LiteralPath $output -Recurse -File -Filter 'ordinary-detector-evidence.json')
    if ($detectorFiles.Count -ne 1) { throw 'Expected one completed ordinary detector report.' }
    $detector = Get-Content -LiteralPath $detectorFiles[0].FullName -Raw | ConvertFrom-Json
    if ($detector.surface -ne 'tauri-webview2' -or $detector.device -ne 'cpu' -or $detector.initializer -ne 'scratch' -or $detector.checkpoint_sha256 -notmatch '^[a-f0-9]{64}$') {
        throw 'The installed detector report lacks verified CPU scratch-training evidence.'
    }
    $backupFiles = @(Get-ChildItem -LiteralPath $output -Recurse -File -Filter 'backup-restore-evidence.json')
    if ($backupFiles.Count -ne 1) { throw 'Expected one completed managed backup and restore report.' }
    $backup = Get-Content -LiteralPath $backupFiles[0].FullName -Raw | ConvertFrom-Json
    if ($backup.surface -ne 'tauri-webview2' -or $backup.restore_status -ne 'succeeded' -or
        $backup.verified_files -lt 2 -or $backup.restored_files -ne $backup.verified_files -or
        $backup.backup_database_sha256 -notmatch '^[a-f0-9]{64}$' -or $backup.original_sha256 -notmatch '^[a-f0-9]{64}$' -or
        $backup.independent_recovery -ne $true -or $backup.live_original_unchanged -ne $true) {
        throw 'The installed backup report lacks a verified independent recovery with an unchanged original.'
    }
    $result | Add-Member -NotePropertyName ordinary_detector -NotePropertyValue $detector
    $result | Add-Member -NotePropertyName backup_restore -NotePropertyValue $backup
    $result | Add-Member -NotePropertyName completed_journeys -NotePropertyValue $stats.expected
    return $result
}
