param(
    [Parameter(Mandatory)][string]$RepositoryRoot,
    [Parameter(Mandatory)][ValidatePattern('^[a-f0-9]{40}$')][string]$SourceCommit,
    [Parameter(Mandatory)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version,
    [Parameter(Mandatory)][ValidatePattern('^[a-zA-Z0-9_]+$')][string]$Schema,
    [Parameter(Mandatory)][string]$Root
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_ENVIRONMENT -cne 'github-hosted' -or
    $env:RUNNER_OS -cne 'Windows' -or $env:GITHUB_REPOSITORY -cne 'Rafael-Del-Valle/ReefVision' -or
    $env:GITHUB_WORKFLOW -cne 'Windows Offline Original MSI Proof' -or $env:RV_HOSTED_OFFLINE_PROOF -cne 'original-msi' -or
    $env:GITHUB_RUN_ID -notmatch '^\d+$' -or $env:GITHUB_RUN_ATTEMPT -notmatch '^\d+$' -or
    $Root -ine "${env:SystemDrive}/rv-offline-$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT") {
    throw 'Network and MSI operations are reserved for the dedicated disposable GitHub-hosted Windows proof job.'
}

$Root = [IO.Path]::GetFullPath($Root)
$source = (Resolve-Path -LiteralPath $RepositoryRoot).Path
if ((git -C $source rev-parse HEAD).Trim() -cne $SourceCommit) { throw 'First-use source checkout differs from the original build source.' }
$harnessSha = (git -C $PSScriptRoot rev-parse HEAD).Trim()
. (Join-Path $source 'scripts/lib/windows-clean-acceptance.ps1')
. (Join-Path $source 'scripts/lib/windows-standard-user-webview2.ps1')
. (Join-Path $source 'scripts/lib/windows-spatial-webview2-acceptance.ps1')
. (Join-Path $PSScriptRoot 'firewall-scope.ps1')
Assert-ReefVisionNoReparseAncestors -Path $Root
if (-not (Test-ReefVisionAdministrator)) { throw 'The hosted proof needs an elevated runner and a separate ordinary GUI account.' }

$evidence = Join-Path $Root 'evidence'
$payload = Get-Content -LiteralPath (Join-Path $evidence 'verified-payload.json') -Raw | ConvertFrom-Json
$transport = Get-Content -LiteralPath (Join-Path $evidence 'verified-transport.json') -Raw | ConvertFrom-Json
$msi = Join-Path $Root "payload/ReefVision_${Version}_x64_en-US.msi"
$installed = Join-Path $Root 'installed'
$profile = Join-Path $Root 'profile'
$shell = Join-Path $installed 'ReefVision.exe'
$sidecar = Join-Path $installed 'backend/reefvision-api/reefvision-api.exe'
$portFile = Join-Path $profile 'runtime/backend-port.txt'
$product = $payload.identity.ProductCode
$msiHash = (Get-FileHash -LiteralPath $msi).Hash.ToLowerInvariant()
if ($transport.source_commit -cne $SourceCommit -or $transport.version -cne $Version -or
    $transport.original_msi_sha256 -cne $msiHash -or $payload.identity.ProductVersion -cne $Version) {
    throw 'Original MSI identity changed after online verification.'
}
if (@(Get-ReefVisionInstalledRegistrations).Count -ne 0 -or (Test-Path -LiteralPath $installed) -or
    (Test-Path -LiteralPath $profile)) { throw 'Offline qualification requires a fresh session and install/profile location.' }
$node = (Get-Command node.exe -ErrorAction Stop).Source
New-Item -ItemType Directory -Path $profile | Out-Null
$token = [guid]::NewGuid().ToString('N')
Set-Content -LiteralPath (Join-Path $Root '.reefvision-acceptance-run') -Value $token
Set-Content -LiteralPath (Join-Path $profile '.reefvision-clean-install-acceptance') -Value $token

function Test-ExternalTcp([Net.IPAddress]$Address) {
    $client = [Net.Sockets.TcpClient]::new($Address.AddressFamily)
    try {
        return $client.ConnectAsync($Address, 443, [Threading.CancellationToken]::None).AsTask().Wait(1400) -and $client.Connected
    } catch { return $false } finally { $client.Dispose() }
}

function Read-PackagedSession($Account, $Desktop) {
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(35)
    $port = ''
    do {
        if ($Desktop.HasExited) { throw 'The installed desktop exited before the packaged sidecar opened.' }
        if (Test-Path -LiteralPath $portFile -PathType Leaf) {
            $port = (Get-Content -LiteralPath $portFile -Raw).Trim()
            if ($port -match '^\d+$') { break }
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    if ($port -notmatch '^\d+$') { throw 'The packaged sidecar did not publish a loopback port.' }
    $api = "http://127.0.0.1:$port/api/v1"
    $actualVersion = Invoke-RestMethod "$api/system/version" -TimeoutSec 8
    $database = Invoke-RestMethod "$api/system/migrations/status" -TimeoutSec 8
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen)
    if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1') { throw 'The packaged API is not bound exclusively to loopback.' }
    $backend = Get-CimInstance Win32_Process -Filter "ProcessId = $($listeners[0].OwningProcess)"
    if ($backend.ExecutablePath -ine $sidecar -or $backend.ParentProcessId -ne $Desktop.Id -or
        (Invoke-CimMethod -InputObject $backend -MethodName GetOwnerSid).Sid -ne $Account.sid.Value) {
        throw 'The loopback listener is not the installed sidecar of the verified ordinary desktop.'
    }
    if ($actualVersion.application_version -cne $Version -or $database.schema_status -cne 'up_to_date' -or
        -not $database.database_exists -or $database.current_schema_revision -cne $Schema) {
        throw 'The actual installed sidecar version/schema differs from the original candidate.'
    }
    return [ordered]@{api=$api; backend_pid=$backend.ProcessId; desktop_pid=$Desktop.Id; schema=$Schema; version=$Version}
}

function Read-PersistedReview([string]$Api, $FirstUse) {
    $images = Invoke-RestMethod "$Api/projects/$($FirstUse.project_id)/images?annotation_status=reviewed" -TimeoutSec 8
    $image = @($images.items)
    if ($image.Count -ne 1) { throw 'Could not find the original first-use image after reopening.' }
    $review = Invoke-RestMethod "$Api/images/$($image[0].id)/annotations" -TimeoutSec 8
    if ($review.image.sha256 -cne $FirstUse.image_sha256 -or $review.image.annotation_status -cne 'reviewed' -or
        @($review.annotations).Count -ne 1) {
        throw 'The persisted reviewed annotation is missing.'
    }
    return [ordered]@{image_id=$image[0].id; sha256=$review.image.sha256; status=$review.image.annotation_status; annotations=$review.annotations}
}

$controls = @([Net.Dns]::GetHostAddresses('api.github.com') | Where-Object { Test-ExternalTcp $_ })
if (-not @($controls | Where-Object AddressFamily -eq 'InterNetwork').Count) { throw 'External TCP positive control failed before isolation.' }
$runnerPrograms = @(Get-HostedRunnerPrograms)
$policyGroup = "ReefVisionOfflineProof-$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT"
$record = [ordered]@{
    status='INCOMPLETE'; source_commit=$SourceCommit; expected_version=$Version; expected_schema=$Schema; msi_sha256=$msiHash
    original_build_run_id=$transport.build_run_id; proof_run_id=$env:GITHUB_RUN_ID; test_harness_sha=$harnessSha
    surface='installed-tauri-webview2'; operating_system='Windows hosted runner'; topology='deny outbound for all programs except authenticated Actions executables TCP 443'
    before=[ordered]@{utc=[DateTimeOffset]::UtcNow.ToString('o'); reachable_control_addresses=@($controls | ForEach-Object IPAddressToString); preexisting_product_registrations=0}
    permitted_control_plane=@($runnerPrograms | Select-Object Name,ProcessId,ExecutablePath)
    offline=[ordered]@{}; cleanup=[ordered]@{}
}
$report = Join-Path $evidence 'offline-install-report.json'
$task = "ReefVisionOfflineRestore-$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT"
$taskRegistered = $false
$armed = Join-Path $Root 'network-armed'
$systemProbeTask = "$task-TcpProbe"
$systemProbeRegistered = $false
$ordinaryProbe = $null
$account = $null
$debugPort = 0
$oldPath = $env:PATH

function Wait-TcpControls([bool]$ExpectedOnline) {
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(14)
    $started = [DateTimeOffset]::UtcNow
    do {
        $last = [ordered]@{}
        foreach ($role in 'ordinary','system') {
            $probeLog = Join-Path $Root "probe-$role/tcp.jsonl"
            if (-not (Test-Path -LiteralPath $probeLog -PathType Leaf)) { continue }
            $sample = Get-Content -LiteralPath $probeLog -Tail 1 | ConvertFrom-Json -ErrorAction SilentlyContinue
            if ($sample -and [DateTimeOffset]$sample.utc -ge $started -and
                (($ExpectedOnline -and $sample.reachable.Count -eq $controls.Count) -or
                 (-not $ExpectedOnline -and $sample.reachable.Count -eq 0))) {
                $last[$role] = $sample
            }
        }
        if ($last.Count -eq 2) { return $last }
        Start-Sleep -Milliseconds 250
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw "The real ordinary-account and SYSTEM TCP control did not establish expected online=$ExpectedOnline."
}

function Assert-OfflinePhase([string]$Phase) {
    $policy = Assert-ProofFirewall $runnerPrograms $policyGroup
    $reachable = @($controls | Where-Object { Test-ExternalTcp $_ })
    if ($reachable.Count) { throw "External networking is operational during $Phase." }
    $probe = Wait-TcpControls $false
    $record.offline[$Phase] = [ordered]@{utc=[DateTimeOffset]::UtcNow.ToString('o'); host_tcp_reachable=0; effective_policy=$policy; control=$probe}
    Write-ReefVisionEvidenceReport -Report $record -Path $report
}

try {
    $recoveryScript = Join-Path $Root 'restore-hosted-network.ps1'
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'restore-hosted-network.ps1') -Destination $recoveryScript
    $state = Join-Path $Root 'network-restore-state.json'
    $restoreAt = (Get-Date).AddMinutes(12)
    $record.original_policy = Save-OriginalFirewallAndHosts $Root
    [ordered]@{
        computer=$env:COMPUTERNAME; expires_utc=[DateTimeOffset]::UtcNow.AddMinutes(15).ToString('o')
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $state
    $action = New-ScheduledTaskAction -Execute (Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe') `
        -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -State "{1}"' -f $recoveryScript,$state)
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $task -Action $action -Trigger (New-ScheduledTaskTrigger -Once -At $restoreAt) `
        -Principal $principal -Settings $settings | Out-Null
    $taskRegistered = $true
    Start-ScheduledTask -TaskName $task
    $watchdogLog = Join-Path $evidence 'watchdog.jsonl'
    $readyBy = [DateTimeOffset]::UtcNow.AddSeconds(18)
    do {
        if ((Test-Path -LiteralPath $watchdogLog) -and (Get-ScheduledTask -TaskName $task).State -eq 'Ready') { break }
        Start-Sleep -Milliseconds 200
    } while ([DateTimeOffset]::UtcNow -lt $readyBy)
    if (-not (Test-Path -LiteralPath $watchdogLog) -or (Get-ScheduledTask -TaskName $task).State -ne 'Ready' -or
        (Get-ScheduledTaskInfo -TaskName $task).LastTaskResult -ne 0) { throw 'The independent network restoration watchdog did not execute its online preflight.' }
    $record.watchdog_due_utc = $restoreAt.ToUniversalTime().ToString('o')

    $account = New-ReefVisionHostedGuiAccount -RunRoot $Root
    Grant-ReefVisionHostedGuiAccess -Path $Root -Sid $account.sid -Rights 'RX'
    $ordinaryControl = Join-Path $Root 'probe-ordinary'
    New-Item -ItemType Directory -Path $ordinaryControl,(Join-Path $Root 'probe-system') | Out-Null
    Grant-ReefVisionHostedGuiAccess -Path $ordinaryControl -Sid $account.sid -Rights 'M'
    $probeScript = Join-Path $Root 'firewall-control.ps1'
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'firewall-control.ps1') -Destination $probeScript
    $probePlan = Join-Path $Root 'firewall-probes.json'
    @{ordinary_sid=$account.sid.Value; addresses=@($controls | ForEach-Object IPAddressToString); expires_utc=$restoreAt.AddMinutes(1).ToUniversalTime().ToString('o')} |
        ConvertTo-Json | Set-Content -LiteralPath $probePlan
    $probeArgs = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -Plan "{1}" -Role' -f $probeScript,$probePlan
    $systemAction = New-ScheduledTaskAction -Execute $action.Execute -Argument "$probeArgs system"
    $probeSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
    Register-ScheduledTask -TaskName $systemProbeTask -Action $systemAction -Principal $principal -Settings $probeSettings | Out-Null
    $systemProbeRegistered = $true
    Start-ScheduledTask -TaskName $systemProbeTask
    $ordinaryProbe = Start-Process -FilePath $action.Execute -ArgumentList "$probeArgs ordinary" -Credential $account.credential `
        -LoadUserProfile -UseNewEnvironment -PassThru -WindowStyle Hidden
    $record.before.controls = Wait-TcpControls $true

    $env:PATH = @((Join-Path $env:SystemRoot 'System32'), $env:SystemRoot, (Join-Path $env:SystemRoot 'System32/Wbem'),
        (Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0'), (Join-Path $env:ProgramFiles 'PowerShell/7')) -join ';'
    foreach ($runtime in 'node','npm','python','python3','rustc','cargo') {
        if (Get-Command $runtime -ErrorAction SilentlyContinue) { throw "Developer runtime on measured PATH: $runtime" }
    }

    Set-Content -LiteralPath $armed -Value $token
    $record.control_names = @(Add-RunnerControlNameResolution)
    Set-ProofFirewall $runnerPrograms $policyGroup
    Assert-OfflinePhase 'before_install'

    $msiexec = Join-Path $env:SystemRoot 'System32/msiexec.exe'
    $installLog = Join-Path $evidence 'msi-install.log'
    $args = New-ReefVisionMsiArguments -Action Install -PackageOrProduct $msi -InstallRoot $installed -LogPath $installLog
    $installer = Start-Process -FilePath $msiexec -ArgumentList $args -Wait -PassThru -WindowStyle Hidden
    Assert-OfflinePhase 'after_install'
    $record.install_exit_code = $installer.ExitCode
    $registration = @(Get-ReefVisionInstalledRegistrations | Where-Object PSChildName -eq $product)
    if ($installer.ExitCode -ne 0 -or $registration.Count -ne 1 -or $registration[0].DisplayVersion -ne $Version -or
        -not (Test-Path -LiteralPath $shell -PathType Leaf) -or -not (Test-Path -LiteralPath $sidecar -PathType Leaf)) {
        throw 'Original offline MSI installation did not produce the exact registered shell and sidecar.'
    }
    $record.installed = [ordered]@{
        product_code=$product; shell_sha256=(Get-FileHash -LiteralPath $shell).Hash.ToLowerInvariant()
        sidecar_sha256=(Get-FileHash -LiteralPath $sidecar).Hash.ToLowerInvariant()
    }

    $debugPort = Get-ReefVisionLoopbackDebugPort
    $desktop = Start-ReefVisionHostedGui -Account $account -Executable $shell -Profile $profile -DebugPort $debugPort -EvidenceRoot $evidence
    $session = Read-PackagedSession $account $desktop
    Assert-OfflinePhase 'after_ordinary_native_launch'
    $first = Invoke-ReefVisionFirstUseAcceptance -NodePath $node -RepositoryRoot $source -EvidenceRoot $evidence -Api $session.api `
        -DebugPort $debugPort -DesktopProcessId $desktop.Id -ExpectedVersion $Version -ExpectedBrowserSid $account.sid.Value `
        -BrowserArtifactsDirectory $account.browser_artifacts
    $review = Read-PersistedReview $session.api $first
    $record.first_launch = $session
    $record.first_use = $first
    $identity = Join-Path $evidence 'spatial-standard-user-identity.log'
    Copy-Item -LiteralPath $identity -Destination (Join-Path $evidence 'first-ordinary-user-identity.json')
    Assert-OfflinePhase 'after_reviewed_geometry_export_and_reopen'

    $null = $desktop.CloseMainWindow()
    if (-not $desktop.WaitForExit(10000) -or -not $account.launcher.WaitForExit(8000)) { throw 'The first native session did not close for a persistence check.' }
    Wait-ReefVisionWebView2DebugClosure -Port $debugPort
    Remove-Item -LiteralPath $portFile -Force -ErrorAction SilentlyContinue
    Move-Item -LiteralPath (Join-Path $Root 'ordinary-user-launch') -Destination (Join-Path $Root 'first-ordinary-user-launch')
    Move-Item -LiteralPath (Join-Path $Root 'profile-webview2') -Destination (Join-Path $Root 'first-profile-webview2')
    $debugPort = Get-ReefVisionLoopbackDebugPort
    $desktop = Start-ReefVisionHostedGui -Account $account -Executable $shell -Profile $profile -DebugPort $debugPort -EvidenceRoot $evidence
    $restarted = Read-PackagedSession $account $desktop
    $null = Wait-ReefVisionWebView2DebugEndpoint -Port $debugPort -DesktopProcessId $desktop.Id -ExpectedBrowserSid $account.sid.Value `
        -FailureEvidencePath (Join-Path $evidence 'relaunch-webview2-startup.log')
    $restored = Read-PersistedReview $restarted.api $first
    if ($restarted.desktop_pid -eq $session.desktop_pid -or $restarted.backend_pid -eq $session.backend_pid -or
        ($restored | ConvertTo-Json -Depth 10 -Compress) -cne ($review | ConvertTo-Json -Depth 10 -Compress)) {
        throw 'A second native process did not reopen the exact persisted reviewed work.'
    }
    $record.second_launch = $restarted
    $record.persisted_review = $restored
    Assert-OfflinePhase 'after_shell_and_sidecar_restart'
    $end = [DateTimeOffset]::Parse($record.offline.after_shell_and_sidecar_restart.utc)
    $start = [DateTimeOffset]::Parse($record.offline.before_install.utc)
    if ($end.LocalDateTime -ge $restoreAt) { throw 'The isolated operations exceeded the scheduled recovery deadline.' }
    $record.offline_control_counts = [ordered]@{}
    foreach ($role in 'ordinary','system') {
        $interval = @(Get-Content -LiteralPath (Join-Path $Root "probe-$role/tcp.jsonl") | ForEach-Object {
            $_ | ConvertFrom-Json -ErrorAction SilentlyContinue
        } | Where-Object { [DateTimeOffset]$_.utc -ge $start -and [DateTimeOffset]$_.utc -le $end })
        if (-not $interval.Count -or @($interval | Where-Object { $_.reachable.Count }).Count) {
            throw "The $role control established external TCP reachability or no samples during the proof."
        }
        $last = $start
        foreach ($sample in ($interval + @(@{utc=$end.ToString('o')}))) {
            $time = [DateTimeOffset]$sample.utc
            if (($time - $last).TotalSeconds -gt 5) { throw "The $role control has an unobserved gap." }
            $last = $time
        }
        $record.offline_control_counts[$role] = $interval.Count
    }
    $record.offline_seconds = ($end - $start).TotalSeconds
    $record.status = 'OFFLINE_OPERATIONS_PASSED'
} catch {
    $record.status = 'FAIL'
    $record.error = $_.Exception.Message
    throw
} finally {
    try {
        if ($taskRegistered -and (Test-Path -LiteralPath $armed)) {
            Start-ScheduledTask -TaskName $task
            $onlineBy = [DateTimeOffset]::UtcNow.AddSeconds(40)
            do {
                $online = @($controls | Where-Object { Test-ExternalTcp $_ })
                if ($online.Count -eq $controls.Count -and (Get-ScheduledTask -TaskName $task).State -eq 'Ready') { break }
                Start-Sleep -Milliseconds 500
            } while ([DateTimeOffset]::UtcNow -lt $onlineBy)
            $record.cleanup.reachable_control_addresses = @($online | ForEach-Object IPAddressToString)
            $after = Get-Content -LiteralPath $watchdogLog -Tail 1 | ConvertFrom-Json
            $record.cleanup.network_restored = $online.Count -eq $controls.Count -and $after.PSObject.Properties['restored'] -and $after.restored
            if (-not $record.cleanup.network_restored) { throw 'The planned watchdog remains registered because the online control has not recovered.' }
            $hosts = Join-Path $env:SystemRoot 'System32/drivers/etc/hosts'
            if ((Get-FileHash -LiteralPath $hosts).Hash -cne $record.original_policy.hosts_sha256) { throw 'Original Windows hosts bytes were not restored.' }
            $record.cleanup.controls = Wait-TcpControls $true
        }
        if ($taskRegistered) { Unregister-ScheduledTask -TaskName $task -Confirm:$false }
        Set-Content -LiteralPath (Join-Path $Root 'stop-probes') -Value $token
        if ($ordinaryProbe -and -not $ordinaryProbe.WaitForExit(8000)) { $ordinaryProbe.Kill(); $null=$ordinaryProbe.WaitForExit(8000) }
        if ($systemProbeRegistered) { Stop-ScheduledTask -TaskName $systemProbeTask; Unregister-ScheduledTask -TaskName $systemProbeTask -Confirm:$false }
        if ($account) { Remove-ReefVisionHostedGuiAccount -Account $account -EvidenceRoot $evidence }
        if ($debugPort) { Wait-ReefVisionWebView2DebugClosure -Port $debugPort }
        if (@(Get-ReefVisionInstalledRegistrations | Where-Object PSChildName -eq $product).Count) {
            $args = New-ReefVisionMsiArguments -Action Uninstall -PackageOrProduct $product -LogPath (Join-Path $evidence 'msi-uninstall.log')
            $uninstall = Start-Process -FilePath $msiexec -ArgumentList $args -Wait -PassThru -WindowStyle Hidden
            if ($uninstall.ExitCode -ne 0 -or @(Get-ReefVisionInstalledRegistrations).Count) { throw 'Could not remove the disposable registered installation after reconnection.' }
            $record.cleanup.uninstall_exit_code = $uninstall.ExitCode
        }
        if ($record.status -eq 'OFFLINE_OPERATIONS_PASSED') { $record.status = 'PASS' }
    } catch {
        $record.status = 'FAIL'
        $record.cleanup.error = $_.Exception.Message
        throw
    } finally {
        $env:PATH = $oldPath
        foreach ($role in 'ordinary','system') {
            $log = Join-Path $Root "probe-$role/tcp.jsonl"
            if (Test-Path -LiteralPath $log -PathType Leaf) { Copy-Item -LiteralPath $log -Destination (Join-Path $evidence "$role-tcp-control.jsonl") }
        }
        Write-ReefVisionEvidenceReport -Report $record -Path $report
    }
}
