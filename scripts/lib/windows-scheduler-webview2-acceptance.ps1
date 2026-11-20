Set-StrictMode -Version Latest

function Get-ReefVisionScheduleRestartTime($Witness, [datetimeoffset]$ClosedAt) {
    $due = [datetimeoffset]$Witness.schedule.next_due_at
    $interval = [int]$Witness.schedule.interval_seconds
    if ($interval -lt 1 -or $interval -gt 60 -or $ClosedAt -ge $due -or $due -gt $ClosedAt.AddSeconds($interval)) {
        throw 'The first desktop must close before its next due UTC slot; restart proof cannot credit a run made while still open.'
    }
    return $due.AddSeconds($interval).AddMilliseconds(1500)
}

function Get-ReefVisionInstalledScheduleBackend {
    param(
        [int]$Port, [int]$DesktopProcessId, [string]$BrowserSid,
        [string]$BackendExecutable, [string]$Profile, [string]$Version, [string]$Revision
    )
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -cne '127.0.0.1') {
        throw 'The schedule backend must have one IPv4 loopback listener.'
    }
    $processId = [int]$listeners[0].OwningProcess
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
    if (-not $owner -or $owner.ExecutablePath -ine $BackendExecutable) {
        throw 'The schedule listener does not belong to the exact installed sidecar.'
    }
    $identity = Invoke-CimMethod -InputObject $owner -MethodName GetOwnerSid
    $parent = [int]$owner.ParentProcessId
    if ($parent -ne $DesktopProcessId) {
        # PyInstaller may place the listening process under its original sidecar launcher.
        $sidecarLauncher = Get-CimInstance Win32_Process -Filter "ProcessId = $parent"
        if (-not $sidecarLauncher -or $sidecarLauncher.ExecutablePath -ine $BackendExecutable -or
            $sidecarLauncher.ParentProcessId -ne $DesktopProcessId) {
            throw 'The installed sidecar listener is unrelated to the tested desktop.'
        }
    }
    if ($identity.ReturnValue -ne 0 -or $identity.Sid -ne $BrowserSid -or
        (Get-ReefVisionProcessIntegrity (Get-Process -Id $processId -ErrorAction Stop)) -ne 8192) {
        throw 'The schedule sidecar must run under the same medium-integrity Windows account as WebView2.'
    }
    $api = "http://127.0.0.1:$Port/api/v1"
    $system = Invoke-RestMethod "$api/system/version" -NoProxy -TimeoutSec 5
    $migration = Invoke-RestMethod "$api/system/migrations/status" -NoProxy -TimeoutSec 5
    if ($system.application_version -cne $Version -or $system.current_schema_revision -cne $Revision -or
        $migration.schema_status -cne 'up_to_date' -or $migration.current_schema_revision -cne $Revision -or
        [IO.Path]::GetFullPath($system.data_dir) -ine $Profile -or
        [IO.Path]::GetFullPath($system.database_path) -ine (Join-Path $Profile 'reefvision.db')) {
        throw 'Schedule backend version, schema or isolated profile failed its pre-write identity check.'
    }
    return [ordered]@{
        pid=$processId; port=$Port; integrity=8192; application_version=$Version; schema_revision=$Revision
        exact_profile_verified=$true
        sha256=(Get-FileHash -LiteralPath $BackendExecutable -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Stop-ReefVisionInstalledSchedulePhase($Account, [int]$DebugPort, $Backend) {
    Stop-AcceptanceDesktop $Account.desktop
    if (-not $Account.launcher.WaitForExit(10000)) { throw 'The scheduler desktop launcher was still running after close.' }
    Wait-ReefVisionWebView2DebugClosure -Port $DebugPort
    $deadline = [datetimeoffset]::UtcNow.AddSeconds(8)
    do {
        if (-not (Get-Process -Id $Backend.pid -ErrorAction SilentlyContinue) -and
            -not (Get-NetTCPConnection -LocalPort $Backend.port -State Listen -ErrorAction SilentlyContinue)) {
            return [datetimeoffset]::UtcNow
        }
        Start-Sleep -Milliseconds 250
    } while ([datetimeoffset]::UtcNow -lt $deadline)
    throw 'The exact scheduler sidecar or its listener survived desktop closure.'
}

function Invoke-ReefVisionInstalledScheduleAcceptance {
    param(
        [string]$NodePath, [string]$RepositoryRoot, [string]$EvidenceRoot,
        [string]$RunRoot, [string]$Executable, [string]$Profile, [string]$Marker,
        [string]$Version, [string]$Revision, [string]$InstallerSha256
    )
    Assert-ReefVisionHostedStandardUserMode
    if (-not (Test-ReefVisionPathWithin -Path $Profile -Parent $RunRoot)) {
        throw 'The scheduler acceptance profile must be inside the marked disposable run.'
    }
    New-Item -ItemType Directory -Path $Profile | Out-Null
    Set-Content -LiteralPath (Join-Path $Profile '.reefvision-clean-install-acceptance') -Value $Marker
    $witnessPath = Join-Path $EvidenceRoot 'schedule-restart-witness.json'
    $portPath = Join-Path $Profile 'runtime\backend-port.txt'
    $sidecar = Join-Path (Split-Path -Parent $Executable) 'backend\reefvision-api\reefvision-api.exe'
    $proof = [ordered]@{
        installer_sha256=$InstallerSha256; phases=[ordered]@{}
        desktop_sha256=(Get-FileHash -LiteralPath $Executable -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $debugPort = 0
    $account = New-ReefVisionHostedGuiAccount -RunRoot $RunRoot
    try {
        foreach ($phase in @('before', 'after')) {
            if ($phase -eq 'after') {
                $restartAt = Get-ReefVisionScheduleRestartTime $witness $closedAt
                $proof.before_next_due_at_utc = ([datetimeoffset]$witness.schedule.next_due_at).ToUniversalTime().ToString('o')
                $proof.earliest_allowed_restart_utc = $restartAt.ToUniversalTime().ToString('o')
                while ([datetimeoffset]::UtcNow -lt $restartAt) { Start-Sleep -Milliseconds 250 }
                # The old listener is closed. Remove only its stale port marker before a fresh launch.
                Remove-Item -LiteralPath $portPath -ErrorAction SilentlyContinue
            }
            $debugPort = Get-ReefVisionLoopbackDebugPort
            $launchedAt = [datetimeoffset]::UtcNow
            $desktop = Start-ReefVisionHostedGui -Account $account -Executable $Executable -Profile $Profile `
                -DebugPort $debugPort -EvidenceRoot $EvidenceRoot -LaunchLabel "schedule-$phase"
            $port = Wait-BackendPort -Path $portPath -DesktopProcess $desktop -BackendLogPath (Join-Path $Profile 'logs\backend.log')
            $backend = Get-ReefVisionInstalledScheduleBackend -Port $port -DesktopProcessId $desktop.Id `
                -BrowserSid $account.sid.Value -BackendExecutable $sidecar -Profile $Profile -Version $Version -Revision $Revision
            if ($phase -eq 'after' -and ($desktop.Id -eq $proof.phases.before.desktop_pid -or
                    $backend.pid -eq $proof.phases.before.backend.pid -or $backend.sha256 -cne $proof.phases.before.backend.sha256)) {
                throw 'Schedule restart did not bind a new process tree running the same exact installed sidecar.'
            }
            $proof.phases[$phase] = [ordered]@{
                desktop_pid=$desktop.Id; debug_port=$debugPort; backend=$backend; launched_at_utc=$launchedAt.ToString('o')
                closed_at_utc=$null
            }
            $output = Invoke-ReefVisionInstalledPlaywrightSuite -NodePath $NodePath -RepositoryRoot $RepositoryRoot `
                -EvidenceRoot $EvidenceRoot -Api "http://127.0.0.1:$port/api/v1" -DebugPort $debugPort -DesktopProcessId $desktop.Id `
                -ExpectedBrowserSid $account.sid.Value -BrowserArtifactsDirectory $account.browser_artifacts -Suite "schedule-$phase" `
                -Specs @('workflow-schedules-live.spec.ts') -AdditionalEnvironment @{
                    REEFVISION_SCHEDULE_TEST_PHASE = "$phase-restart"
                    REEFVISION_SCHEDULE_TEST_RESTART_WITNESS = $witnessPath
                    REEFVISION_SCHEDULE_TEST_EXPECTED_DATA_DIR = $Profile
                    REEFVISION_SCHEDULE_TEST_EXPECTED_VERSION = $Version
                    REEFVISION_SCHEDULE_TEST_EXPECTED_SCHEMA = $Revision
                    REEFVISION_SCHEDULE_TEST_FIXTURE = ''
                }
            $closedAt = Stop-ReefVisionInstalledSchedulePhase $account $debugPort $backend
            $proof.phases[$phase].closed_at_utc = $closedAt.ToString('o')
            $files = @(Get-ChildItem -LiteralPath $output -Recurse -File -Filter 'schedule-proof.json')
            if ($files.Count -ne 1) { throw 'Each installed scheduler phase must produce one native receipt.' }
            $phaseProof = Get-Content -LiteralPath $files[0].FullName -Raw | ConvertFrom-Json
            if ($phaseProof.surface -cne 'tauri-webview2' -or $phaseProof.phase -cne "$phase-restart" -or
                $phaseProof.version -cne $Version -or $phaseProof.schema -cne $Revision -or
                $phaseProof.occurrence.status -cne 'succeeded' -or
                $phaseProof.artifactSha256 -cnotmatch '^[a-f0-9]{64}$') {
                throw 'The installed scheduler phase did not prove its real completed workflow and receipt.'
            }
            $proof.phases[$phase].result = $phaseProof
            if ($phase -eq 'before') {
                $witness = Get-Content -LiteralPath $witnessPath -Raw | ConvertFrom-Json
                if ($witness.first.workflow_run_id -ne $phaseProof.occurrence.workflow_run_id -or
                    $witness.first.id -ne $phaseProof.occurrence.id -or $witness.schedule.id -ne $phaseProof.schedule.id) {
                    throw 'The cold restart witness differs from the verified before-restart result.'
                }
            } elseif ($phaseProof.schedule.id -ne $witness.schedule.id -or
                $phaseProof.occurrence.workflow_run_id -eq $witness.first.workflow_run_id -or
                $phaseProof.occurrence.missed_intervals -lt 1 -or
                $phaseProof.graphSha256 -cne $proof.phases.before.result.graphSha256 -or
                $phaseProof.schedule.enabled -ne $false -or
                $phaseProof.receiptProof.receiptSha256 -cnotmatch '^[a-f0-9]{64}$' -or
                $phaseProof.receiptProof.downloadedFileSha256 -cnotmatch '^[a-f0-9]{64}$' -or
                @($phaseProof.receiptProof.replays).Count -ne 2) {
                throw 'The reopened scheduler did not prove a distinct catch-up run on the same frozen graph.'
            }
            if ($phase -eq 'after') {
                $firstReplay, $secondReplay = $phaseProof.receiptProof.replays
                if ($firstReplay.id -eq $secondReplay.id -or
                    $firstReplay.payloadSha256 -cnotmatch '^[a-f0-9]{64}$' -or
                    $firstReplay.payloadSha256 -cne $secondReplay.payloadSha256) {
                    throw 'The scheduled receipt must replay in distinct runs with the same payload bytes.'
                }
            }
        }
    } finally {
        try {
            Remove-ReefVisionHostedGuiAccount -Account $account -EvidenceRoot $EvidenceRoot -Label 'schedule'
            if ($debugPort) { Wait-ReefVisionWebView2DebugClosure -Port $debugPort }
        } finally {
            $proof | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $EvidenceRoot 'schedule-restart-evidence.json')
        }
    }
    return $proof
}
