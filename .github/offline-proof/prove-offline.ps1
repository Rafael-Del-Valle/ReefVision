param(
    [Parameter(Mandatory)][string]$RepositoryRoot,
    [Parameter(Mandatory)][ValidatePattern('^[a-f0-9]{40}$')][string]$SourceCommit,
    [Parameter(Mandatory)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version,
    [Parameter(Mandatory)][ValidatePattern('^[a-zA-Z0-9_]+$')][string]$Schema,
    [Parameter(Mandatory)][string]$Root,
    [string]$PreviousRepositoryRoot
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
. (Join-Path $PSScriptRoot 'webview-handoff.ps1')
. (Join-Path $PSScriptRoot 'upgrade-recovery.ps1')
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
$upgrade = [bool]$PreviousRepositoryRoot
if (($upgrade -and $env:RV_PROOF_SCENARIO -cne 'cached-upgrade') -or
    (-not $upgrade -and $env:RV_PROOF_SCENARIO -cne 'fresh')) { throw 'Offline proof mode differs from its dedicated runner role.' }
$prior = if ($upgrade) { Get-OfflinePredecessor -Root $Root -PreviousSource (Resolve-Path -LiteralPath $PreviousRepositoryRoot).Path }
$msiexec = Join-Path $env:SystemRoot 'System32/msiexec.exe'
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

function Read-PackagedSession($Account, $Desktop, [string]$RuntimeProfile = $profile,
    [string]$RuntimeSidecar = $sidecar, [string]$ExpectedVersion = $Version, [string]$ExpectedSchema = $Schema) {
    # Match the installed clean acceptance allowance for frozen sidecar startup.
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(180)
    $port = ''
    $sessionPort = Join-Path $RuntimeProfile 'runtime/backend-port.txt'
    do {
        if ($Desktop.HasExited) { throw 'The installed desktop exited before the packaged sidecar opened.' }
        if (Test-Path -LiteralPath $sessionPort -PathType Leaf) {
            $port = (Get-Content -LiteralPath $sessionPort -Raw).Trim()
            if ($port -match '^[1-9][0-9]{0,4}$' -and [int]$port -lt 65536) { break }
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    if ($port -notmatch '^[1-9][0-9]{0,4}$' -or [int]$port -ge 65536) { throw 'The packaged sidecar did not publish a loopback port.' }
    $api = "http://127.0.0.1:$port/api/v1"
    $actualVersion = Invoke-RestMethod "$api/system/version" -NoProxy -TimeoutSec 8
    $database = Invoke-RestMethod "$api/system/migrations/status" -NoProxy -TimeoutSec 8
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen)
    if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1') { throw 'The packaged API is not bound exclusively to loopback.' }
    $backend = Get-CimInstance Win32_Process -Filter "ProcessId = $($listeners[0].OwningProcess)"
    if ($backend.ExecutablePath -ine $RuntimeSidecar -or $backend.ParentProcessId -ne $Desktop.Id -or
        (Invoke-CimMethod -InputObject $backend -MethodName GetOwnerSid).Sid -ne $Account.sid.Value) {
        throw 'The loopback listener is not the installed sidecar of the verified ordinary desktop.'
    }
    if ($actualVersion.application_version -cne $ExpectedVersion -or $database.schema_status -cne 'up_to_date' -or
        -not $database.database_exists -or $database.current_schema_revision -cne $ExpectedSchema -or $actualVersion.safe_mode -or
        (Resolve-ReefVisionAcceptancePath $actualVersion.data_dir) -ine (Resolve-ReefVisionAcceptancePath $RuntimeProfile) -or
        (Resolve-ReefVisionAcceptancePath $actualVersion.database_path) -ine (Join-Path $RuntimeProfile 'reefvision.db')) {
        throw 'The actual installed sidecar version/schema differs from the original candidate.'
    }
    return [ordered]@{api=$api; api_port=[int]$port; backend_pid=$backend.ProcessId; desktop_pid=$Desktop.Id
        schema=$ExpectedSchema; version=$ExpectedVersion; profile_verified=$true}
}

function Read-PersistedReview([string]$Api, $FirstUse) {
    $images = Invoke-RestMethod "$Api/projects/$($FirstUse.project_id)/images?annotation_status=reviewed" -TimeoutSec 8
    $image = @($images.items)
    if ($image.Count -ne 1) { throw 'Could not find the original first-use image after reopening.' }
    $review = Invoke-RestMethod "$Api/images/$($image[0].id)/annotations" -TimeoutSec 8
    $http = [Net.Http.HttpClient]::new()
    try {
        $bytes = $http.GetByteArrayAsync("$Api/images/$($image[0].id)/content").GetAwaiter().GetResult()
        $rawSha = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([byte[]]$bytes)).ToLowerInvariant()
    } finally { $http.Dispose() }
    if ($rawSha -cne $FirstUse.image_sha256 -or $review.image.sha256 -cne $FirstUse.image_sha256 -or $review.image.annotation_status -cne 'reviewed' -or
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
$record.mode = if ($upgrade) { 'cached-upgrade' } else { 'fresh' }
$report = Join-Path $evidence $(if ($upgrade) { 'offline-upgrade-report.json' } else { 'offline-install-report.json' })
$task = "ReefVisionOfflineRestore-$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT"
$taskRegistered = $false
$armed = Join-Path $Root 'network-armed'
$systemProbeTask = "$task-TcpProbe"
$systemReconnectTask = "$task-ReconnectProbe"
$systemProbeRegistered = $false
$systemReconnectRegistered = $false
$ordinaryProbe = $null
$ordinaryReconnect = $null
$account = $null
$debugPort = 0
$oldPath = $env:PATH

function Wait-TcpControls([bool]$ExpectedOnline, [string]$ProbeFile='tcp.jsonl', [int]$Timeout=14) {
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($Timeout)
    $started = [DateTimeOffset]::UtcNow
    do {
        $last = [ordered]@{}
        foreach ($role in 'ordinary','system') {
            $probeLog = Join-Path $Root "probe-$role/$ProbeFile"
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
    throw "The real ordinary-account and SYSTEM TCP control did not establish expected online=$ExpectedOnline in $ProbeFile."
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
    if ($upgrade) {
        $oldAdmin = Join-Path $Root 'previous-admin'
        $extract = @('/a',('"' + $prior.msi + '"'),'/qn','/norestart',('TARGETDIR="' + $oldAdmin + '"'),
            '/l*v',('"' + (Join-Path $evidence 'previous-admin.log') + '"'))
        $prepared = Start-Process -FilePath $msiexec -ArgumentList $extract -Wait -PassThru -WindowStyle Hidden
        if ($prepared.ExitCode -ne 0 -or @(Get-ReefVisionInstalledRegistrations).Count) {
            throw 'Administrative extraction of the exact predecessor must preserve the fresh registrations.'
        }
        $rollbackShell = Join-Path $oldAdmin 'PFiles/ReefVision/ReefVision.exe'
        $rollbackSidecar = Join-Path $oldAdmin 'PFiles/ReefVision/backend/reefvision-api/reefvision-api.exe'
        Assert-OfflinePredecessorBinary $prior $rollbackShell $rollbackSidecar
    }
    $recoveryScript = Join-Path $Root 'restore-hosted-network.ps1'
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'restore-hosted-network.ps1') -Destination $recoveryScript
    $state = Join-Path $Root 'network-restore-state.json'
    $watchdogMinutes = if ($upgrade) { 16 } else { 12 }
    $restoreAt = (Get-Date).AddMinutes($watchdogMinutes)
    $record.original_policy = Save-OriginalFirewallAndHosts $Root
    [ordered]@{
        computer=$env:COMPUTERNAME; expires_utc=[DateTimeOffset]::UtcNow.AddMinutes($watchdogMinutes + 3).ToString('o')
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
    $probeSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes ($watchdogMinutes + 3))
    Register-ScheduledTask -TaskName $systemProbeTask -Action $systemAction -Principal $principal -Settings $probeSettings | Out-Null
    $systemProbeRegistered = $true
    Start-ScheduledTask -TaskName $systemProbeTask
    $ordinaryProbe = Start-Process -FilePath $action.Execute -ArgumentList "$probeArgs ordinary" -Credential $account.credential `
        -LoadUserProfile -UseNewEnvironment -PassThru -WindowStyle Hidden
    $record.before.controls = Wait-TcpControls $true

    if ($upgrade) {
        $install = New-ReefVisionMsiArguments -Action Install -PackageOrProduct $prior.msi -InstallRoot $installed -LogPath (Join-Path $evidence 'previous-msi-install.log')
        $previousInstaller = Start-Process -FilePath $msiexec -ArgumentList $install -Wait -PassThru -WindowStyle Hidden
        $oldRegistration = @(Get-ReefVisionInstalledRegistrations)
        if ($previousInstaller.ExitCode -ne 0 -or $oldRegistration.Count -ne 1 -or
            $oldRegistration[0].PSChildName -cne $prior.product_code -or $oldRegistration[0].DisplayVersion -cne $prior.version) {
            throw 'The exact historical MSI did not create the expected registered predecessor.'
        }
        Assert-OfflinePredecessorBinary $prior $shell $sidecar
        $debugPort = Get-ReefVisionLoopbackDebugPort
        $desktop = Start-ReefVisionHostedGui -Account $account -Executable $shell -Profile $profile -DebugPort $debugPort -EvidenceRoot $evidence -LaunchLabel 'previous'
        $preceding = Read-PackagedSession $account $desktop $profile $sidecar $prior.version $prior.schema
        $first = Invoke-ReefVisionFirstUseAcceptance -NodePath $node -RepositoryRoot $PreviousRepositoryRoot `
            -EvidenceRoot (Join-Path $evidence 'previous') -Api $preceding.api -DebugPort $debugPort -DesktopProcessId $desktop.Id `
            -ExpectedVersion $prior.version -ExpectedBrowserSid $account.sid.Value -BrowserArtifactsDirectory $account.browser_artifacts
        $oldReview = Read-PersistedReview $preceding.api $first
        $previousBackup = New-OfflinePreUpgradeBackup $preceding.api $profile $prior.schema
        Close-OfflineUpgradeDesktop $account $desktop $debugPort $preceding $profile
        $record.predecessor = [ordered]@{source_commit=$prior.source_commit; msi_sha256=$prior.msi_sha256; build_run_id=$prior.build_run_id
            build_job_id=$prior.build_job_id; registration=$prior.product_code; session=$preceding; offline_backup_input=$previousBackup
            saved_review=$oldReview; original_ordinary_authoring=$first}
        Write-ReefVisionEvidenceReport -Report $record -Path $report
    }

    $env:PATH = @((Join-Path $env:SystemRoot 'System32'), $env:SystemRoot, (Join-Path $env:SystemRoot 'System32/Wbem'),
        (Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0'), (Join-Path $env:ProgramFiles 'PowerShell/7')) -join ';'
    foreach ($runtime in 'node','npm','python','python3','rustc','cargo') {
        if (Get-Command $runtime -ErrorAction SilentlyContinue) { throw "Developer runtime on measured PATH: $runtime" }
    }

    Set-Content -LiteralPath $armed -Value $token
    $record.control_names = @(Add-RunnerControlNameResolution)
    $firewallChannel = 'Microsoft-Windows-Windows Firewall With Advanced Security/Firewall'
    if (-not (Get-WinEvent -ListLog $firewallChannel).IsEnabled) { throw 'The Windows Firewall policy-change journal is disabled.' }
    $setupStart = [DateTimeOffset]::UtcNow
    Set-ProofFirewall $runnerPrograms $policyGroup
    $setupEvents = @(Test-FirewallJournalSetup $firewallChannel $setupStart $policyGroup)
    Assert-OfflinePhase 'before_install'

    $installLog = Join-Path $evidence 'msi-install.log'
    $args = New-ReefVisionMsiArguments -Action Install -PackageOrProduct $msi -InstallRoot $installed -LogPath $installLog
    $installer = Start-Process -FilePath $msiexec -ArgumentList $args -Wait -PassThru -WindowStyle Hidden
    Assert-OfflinePhase 'after_install'
    $record.install_exit_code = $installer.ExitCode
    $registration = @(Get-ReefVisionInstalledRegistrations | Where-Object PSChildName -eq $product)
    if ($installer.ExitCode -ne 0 -or $registration.Count -ne 1 -or $registration[0].DisplayVersion -ne $Version -or
        ($upgrade -and (@(Get-ReefVisionInstalledRegistrations).Count -ne 1 -or $product -ceq $prior.product_code)) -or
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
    if ($upgrade) {
        $null = Wait-ReefVisionWebView2DebugEndpoint -Port $debugPort -DesktopProcessId $desktop.Id -ExpectedBrowserSid $account.sid.Value `
            -FailureEvidencePath (Join-Path $evidence 'upgrade-webview2-startup.log') -AttachmentEvidencePath (Join-Path $evidence 'upgrade-webview2-attached.log')
    } else {
        $first = Invoke-ReefVisionFirstUseAcceptance -NodePath $node -RepositoryRoot $source -EvidenceRoot $evidence -Api $session.api `
            -DebugPort $debugPort -DesktopProcessId $desktop.Id -ExpectedVersion $Version -ExpectedBrowserSid $account.sid.Value `
            -BrowserArtifactsDirectory $account.browser_artifacts
    }
    $review = Read-PersistedReview $session.api $first
    if ($upgrade -and ($review | ConvertTo-Json -Depth 10 -Compress) -cne ($oldReview | ConvertTo-Json -Depth 10 -Compress)) {
        throw 'The ordinary offline upgrade changed the saved reviewed record.'
    }
    $record.first_launch = $session
    $record.first_use = $first
    $identity = Join-Path $evidence 'spatial-standard-user-identity.log'
    Copy-Item -LiteralPath $identity -Destination (Join-Path $evidence 'first-ordinary-user-identity.json')
    Assert-OfflinePhase 'after_reviewed_geometry_export_and_reopen'

    $webViewScope = New-OfflineWebViewScope -Port $debugPort -DesktopProcessId $desktop.Id -Sid $account.sid.Value -Root $Root
    $firstBrowserProcesses = @(Get-OfflineWebViewProcesses $webViewScope)
    if ($webViewScope.BrowserPid -notin $firstBrowserProcesses) { throw 'The first-launch browser exited before restart measurement.' }
    $null = $desktop.CloseMainWindow()
    if (-not $desktop.WaitForExit(10000) -or -not $account.launcher.WaitForExit(8000)) { throw 'The first native session did not close for a persistence check.' }
    Wait-ReefVisionWebView2DebugClosure -Port $debugPort
    Remove-Item -LiteralPath $portFile -Force -ErrorAction SilentlyContinue
    Move-Item -LiteralPath (Join-Path $Root 'ordinary-user-launch') -Destination (Join-Path $Root 'first-ordinary-user-launch')
    $record.webview_handoff = Move-OfflineWebViewCache -Root $Root -GetLivePids { Get-OfflineWebViewProcesses $webViewScope }
    $record.webview_handoff.first_browser_pid = $webViewScope.BrowserPid
    $record.webview_handoff.first_observed_owned_pids = $firstBrowserProcesses
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
    $lastPhase = 'after_shell_and_sidecar_restart'
    if ($upgrade) {
        $recovery = Restore-OfflinePreUpgradeBackup $restarted.api $profile $previousBackup
        $recovered = $recovery.path
        Set-Content -LiteralPath (Join-Path $recovered '.reefvision-clean-install-acceptance') -Value $token
        Assert-OfflinePhase 'after_verified_previous_backup_restore'
        Close-OfflineUpgradeDesktop $account $desktop $debugPort $restarted $profile
        $debugPort = Get-ReefVisionLoopbackDebugPort
        $desktop = Start-ReefVisionHostedGui -Account $account -Executable $rollbackShell -Profile $recovered `
            -DebugPort $debugPort -EvidenceRoot $evidence -LaunchLabel 'rollback'
        $rollback = Read-PackagedSession $account $desktop $recovered $rollbackSidecar $prior.version $prior.schema
        $null = Wait-ReefVisionWebView2DebugEndpoint -Port $debugPort -DesktopProcessId $desktop.Id -ExpectedBrowserSid $account.sid.Value `
            -FailureEvidencePath (Join-Path $evidence 'rollback-webview2-startup.log') -AttachmentEvidencePath (Join-Path $evidence 'rollback-webview2-attached.log')
        if (((Read-PersistedReview $rollback.api $first) | ConvertTo-Json -Depth 10 -Compress) -cne ($oldReview | ConvertTo-Json -Depth 10 -Compress)) {
            throw 'The older package could not reopen the independently restored original reviewed work offline.'
        }
        Close-OfflineUpgradeDesktop $account $desktop $debugPort $rollback $recovered
        Assert-ReefVisionLineageHash -Path (Join-Path $recovered 'reefvision.db') -ExpectedSha256 $recovery.recovered_db_sha256 -Label 'Closed recovered database'
        $record.recovery = [ordered]@{backup_id=$previousBackup.id; manifest_sha256=$previousBackup.manifest_sha256; restored=$recovery
            previous_ordinary_reopen=$rollback; original_review_unchanged=$true; independent_destination=$true}
        $lastPhase = 'after_previous_ordinary_recovery_reopen'
        Assert-OfflinePhase $lastPhase
    }
    $end = [DateTimeOffset]::Parse($record.offline[$lastPhase].utc)
    $start = [DateTimeOffset]::Parse($record.offline.before_install.utc)
    if ($end.LocalDateTime -ge $restoreAt) { throw 'The isolated operations exceeded the scheduled recovery deadline.' }
    $logConfig = Get-WinEvent -ListLog $firewallChannel
    $firstSetupRecord = ($setupEvents | Measure-Object RecordId -Minimum).Minimum
    if (-not $logConfig.IsEnabled -or $logConfig.OldestRecordNumber -gt $firstSetupRecord) { throw 'The firewall journal lost its setup records.' }
    $policyEvents = @(Get-ProofFirewallEvents $firewallChannel $start $end | Select-Object Id,RecordId,TimeCreated,Message)
    $record.firewall_event_journal = [ordered]@{
        channel=$firewallChannel; setup_control_records=@($setupEvents.RecordId); oldest_retained_record=$logConfig.OldestRecordNumber
        policy_changes_during_measurement=$policyEvents
    }
    if ($policyEvents.Count) { throw 'Windows logged a firewall policy change during the measured product operations.' }
    $record.offline_control_counts = [ordered]@{}
    $record.offline_control_max_gap_seconds = [ordered]@{}
    foreach ($role in 'ordinary','system') {
        $interval = @(Get-Content -LiteralPath (Join-Path $Root "probe-$role/tcp.jsonl") | ForEach-Object {
            $_ | ConvertFrom-Json -ErrorAction SilentlyContinue
        } | Where-Object { [DateTimeOffset]$_.utc -ge $start -and [DateTimeOffset]$_.utc -le $end })
        if (-not $interval.Count -or @($interval | Where-Object { $_.reachable.Count }).Count) {
            throw "The $role control established external TCP reachability or no samples during the proof."
        }
        $last = $start
        $gap = 0.0
        foreach ($sample in ($interval + @(@{utc=$end.ToString('o')}))) {
            $time = [DateTimeOffset]$sample.utc
            $gap = [Math]::Max($gap, ($time - $last).TotalSeconds)
            $last = $time
        }
        $record.offline_control_counts[$role] = $interval.Count
        $record.offline_control_max_gap_seconds[$role] = $gap
        if ($gap -gt 10) { throw "The $role control has an unobserved gap greater than 10 seconds." }
    }
    $record.offline_seconds = ($end - $start).TotalSeconds
    $record.status = 'OFFLINE_OPERATIONS_PASSED'
} catch {
    $record.status = 'FAIL'
    $record.error = $_.Exception.Message
    throw
} finally {
    try {
        $reconnectFailure = $null
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
            try {
                $oldSystemTask = Get-ScheduledTask -TaskName $systemProbeTask
                $oldSystemInfo = Get-ScheduledTaskInfo -TaskName $systemProbeTask
                $record.cleanup.measurement_system_task = [ordered]@{
                    state=[string]$oldSystemTask.State; last_result=$oldSystemInfo.LastTaskResult
                }
                # Preserve the measurement logs and require separate real TCP observations
                # from the same two Windows principals after policy restoration.
                $systemReconnectAction = New-ScheduledTaskAction -Execute $action.Execute -Argument "$probeArgs system -Phase reconnect"
                Register-ScheduledTask -TaskName $systemReconnectTask -Action $systemReconnectAction `
                    -Principal $principal -Settings $probeSettings | Out-Null
                $systemReconnectRegistered = $true
                Start-ScheduledTask -TaskName $systemReconnectTask
                $ordinaryReconnect = Start-Process -FilePath $action.Execute -ArgumentList "$probeArgs ordinary -Phase reconnect" `
                    -Credential $account.credential -LoadUserProfile -UseNewEnvironment -PassThru -WindowStyle Hidden
                $record.cleanup.controls = Wait-TcpControls $true -ProbeFile 'reconnect-tcp.jsonl' -Timeout 25
                if ($record.cleanup.controls.ordinary.sid -cne $record.before.controls.ordinary.sid -or
                    $record.cleanup.controls.system.sid -cne $record.before.controls.system.sid -or
                    $record.cleanup.controls.ordinary.pid -eq $record.before.controls.ordinary.pid -or
                    $record.cleanup.controls.system.pid -eq $record.before.controls.system.pid) {
                    throw 'Reconnect probes must run in new processes under the original proof principals.'
                }
            } catch { $reconnectFailure = $_.Exception.Message }
        }
        if ($taskRegistered) { Unregister-ScheduledTask -TaskName $task -Confirm:$false }
        Set-Content -LiteralPath (Join-Path $Root 'stop-probes') -Value $token
        if ($ordinaryProbe -and -not $ordinaryProbe.WaitForExit(8000)) { $ordinaryProbe.Kill(); $null=$ordinaryProbe.WaitForExit(8000) }
        if ($ordinaryReconnect -and -not $ordinaryReconnect.WaitForExit(8000)) { $ordinaryReconnect.Kill(); $null=$ordinaryReconnect.WaitForExit(8000) }
        if ($systemProbeRegistered) { Stop-ScheduledTask -TaskName $systemProbeTask; Unregister-ScheduledTask -TaskName $systemProbeTask -Confirm:$false }
        if ($systemReconnectRegistered) { Stop-ScheduledTask -TaskName $systemReconnectTask; Unregister-ScheduledTask -TaskName $systemReconnectTask -Confirm:$false }
        if ($account) { Remove-ReefVisionHostedGuiAccount -Account $account -EvidenceRoot $evidence }
        if ($debugPort) { Wait-ReefVisionWebView2DebugClosure -Port $debugPort }
        $disposable = @(Get-ReefVisionInstalledRegistrations | Where-Object { $_.PSChildName -ceq $product -or ($upgrade -and $_.PSChildName -ceq $prior.product_code) })
        foreach ($entry in $disposable) {
            $args = New-ReefVisionMsiArguments -Action Uninstall -PackageOrProduct $entry.PSChildName -LogPath (Join-Path $evidence 'msi-uninstall.log')
            $uninstall = Start-Process -FilePath $msiexec -ArgumentList $args -Wait -PassThru -WindowStyle Hidden
            if ($uninstall.ExitCode -ne 0) { throw 'Could not remove the disposable registered installation after reconnection.' }
            $record.cleanup.uninstall_exit_code = $uninstall.ExitCode
        }
        if (@(Get-ReefVisionInstalledRegistrations).Count) { throw 'Unexpected registration survives offline qualification.' }
        if ($record.status -eq 'OFFLINE_OPERATIONS_PASSED') {
            if ($record.cleanup.uninstall_exit_code -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $profile 'reefvision.db') -PathType Leaf)) {
                throw 'The uninstall did not retain the tested live data.'
            }
            $record.cleanup.live_data_retained = $true
            if ($upgrade) {
                Assert-ReefVisionLineageHash -Path (Join-Path $recovered 'reefvision.db') -ExpectedSha256 $recovery.recovered_db_sha256 -Label 'Recovered old snapshot after uninstall'
                $record.cleanup.recovered_data_retained = $true
            }
        }
        if ($reconnectFailure) { throw $reconnectFailure }
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
            $reconnectLog = Join-Path $Root "probe-$role/reconnect-tcp.jsonl"
            if (Test-Path -LiteralPath $reconnectLog -PathType Leaf) {
                Copy-Item -LiteralPath $reconnectLog -Destination (Join-Path $evidence "$role-reconnect-tcp-control.jsonl")
            }
        }
        Write-ReefVisionEvidenceReport -Report $record -Path $report
    }
}
