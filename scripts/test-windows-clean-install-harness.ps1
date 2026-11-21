$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'lib\windows-clean-acceptance.ps1')
. (Join-Path $PSScriptRoot 'lib\windows-spatial-webview2-acceptance.ps1')
. (Join-Path $PSScriptRoot 'lib\windows-standard-user-webview2.ps1')
. (Join-Path $PSScriptRoot 'lib\windows-scheduler-webview2-acceptance.ps1')
. (Join-Path $PSScriptRoot 'lib\windows-monitoring-webview2-acceptance.ps1')
. (Join-Path $PSScriptRoot 'lib\windows-research-tools-webview2-acceptance.ps1')

$passed = 0
function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    $script:passed++
}
function Assert-Throws([scriptblock]$Action, [string]$Message) {
    try { & $Action; throw "Expected failure: $Message" } catch {
        if ($_.Exception.Message -like 'Expected failure:*') { throw }
    }
    $script:passed++
}

& {
    $sha = 'a' * 64
    $capture = @{
        surface='tauri-webview2'; version='1.7.0'; schema='b17_monitor_0003'; project_id='fixture-a'
        disconnected_cursor=1; simulated_source_id='sim-fixture'; occurrence_id='slot-fixture'
        camera_consent_cancelled_without_capture=$true; replay_digests=@($sha,$sha)
        recorded=@(
            @{content_sha256=$sha;receipt=@{project_id='fixture-a';source_kind='recorded';source_id='recorded';ordinal=0
                media=@{sha256=$sha;field_batch_id='batch';field_batch_sha256=$sha}
                time=@{captured_at_utc='2025-08-02T22:05:06Z';uncertainty_seconds=$null}}}
            @{content_sha256=('b' * 64);receipt=@{project_id='fixture-a';source_kind='recorded';source_id='recorded';ordinal=1
                media=@{sha256=('d' * 64);field_batch_id='batch';field_batch_sha256=$sha}
                time=@{captured_at_utc=$null;uncertainty_seconds=$null;clock=@{state='unknown'}}}}
        )
        capture_artifact=@{data_type='acquisition_capture_receipt';payload_sha256=$sha;workflow_run_id='worker-run';payload_json=@{receipt=@{
            project_id='fixture-a';source_id='sim-fixture';source_kind='simulated'
            dispatch=@{kind='schedule';occurrence_id='slot-fixture';workflow_run_id='worker-run'}
            synthetic_reading=@{unit='synthetic arbitrary units'}
        }}}
    }
    $monitoring = @{
        surface='tauri-webview2';version='1.7.0';schema='b17_monitor_0003';generated_fixture=$true
        export_sha256=$sha
        assessments=@(
            @{project_id='study-a';id='assessment-a';evidence_sha256=$sha;result_sha256=$sha
              effort=@{accepted_observations=4;observed_slots=4;expected_slots=5}}
            @{project_id='study-b';id='assessment-b';evidence_sha256=$sha;result_sha256=$sha
              effort=@{accepted_observations=5;observed_slots=5;expected_slots=5}}
            @{project_id='study-c';id='assessment-c';evidence_sha256=$sha;result_sha256=$sha
              effort=@{accepted_observations=4;observed_slots=4;expected_slots=4}}
        )
        findings=@(
            @{id='drop';kind='drop';proposal_sha256=$sha}
            @{id='delay';kind='delay';proposal_sha256=$sha}
            @{id='drift';kind='drift';proposal_sha256=$sha}
            @{id='upper';kind='upper_limit';proposal_sha256=$sha}
        )
        reviews=@(
            @{alert_id='drop';project_id='study-a';decision='confirmed';reviewer='fixture';reason='Fixture reviewed';revision=1}
            @{alert_id='delay';project_id='study-a';decision='dismissed';reviewer='fixture';reason='Fixture reviewed';revision=1}
            @{alert_id='drift';project_id='study-a';decision='dismissed';reviewer='fixture';reason='Fixture reviewed';revision=1}
            @{alert_id='upper';project_id='study-a';decision='dismissed';reviewer='fixture';reason='Fixture reviewed';revision=1}
        )
        summary=@{id='summary';content_sha256=$sha;project_rows=@(
            @{project_id='study-a';status='included';reasons=@()}
            @{project_id='study-b';status='included';reasons=@()}
            @{project_id='study-c';status='excluded';reasons=@('The UTC observation windows differ.')}
        )}
        assessment_replays=@(@{id='run-1';payloadSha256=$sha},@{id='run-2';payloadSha256=$sha})
        summary_replays=@(@{id='run-3';payloadSha256=$sha},@{id='run-4';payloadSha256=$sha})
    }
    Assert-ReefVisionInstalledMonitoringResults -Acquisition $capture -Monitoring $monitoring -Version '1.7.0' -Revision 'b17_monitor_0003'
    Assert-True $true 'Generated recorded, simulated and monitoring receipts should validate together.'
    $capture.recorded[1].receipt.time.captured_at_utc = '2025-08-02T22:05:07Z'
    Assert-Throws { Assert-ReefVisionInstalledMonitoringResults $capture $monitoring '1.7.0' 'b17_monitor_0003' } 'An invented reconnect clock must not qualify.'
    $capture.recorded[1].receipt.time.captured_at_utc = $null
    $capture.capture_artifact.payload_json.receipt.dispatch.workflow_run_id = 'unrelated-run'
    Assert-Throws { Assert-ReefVisionInstalledMonitoringResults $capture $monitoring '1.7.0' 'b17_monitor_0003' } 'The scheduled simulator must name the artifact parent run.'
    $capture.capture_artifact.payload_json.receipt.dispatch.workflow_run_id = 'worker-run'
    $monitoring.summary.project_rows[2].status = 'included'
    Assert-Throws { Assert-ReefVisionInstalledMonitoringResults $capture $monitoring '1.7.0' 'b17_monitor_0003' } 'An incompatible project must stay excluded.'
    $monitoring.summary.project_rows[2].status = 'excluded'
    $monitoring.summary_replays[1].payloadSha256 = 'c' * 64
    Assert-Throws { Assert-ReefVisionInstalledMonitoringResults $capture $monitoring '1.7.0' 'b17_monitor_0003' } 'A differing replay must not qualify.'
}

& {
    $hash = 'a' * 64
    $second = 'b' * 64
    $version = '1.8.0'
    $schema = 'b18_spectral_0002'
    $owned = @{surface='tauri-webview2'; application_version=$version; schema_revision=$schema; generated_fixture=$true}
    $typed = @(@{id='run-a';sha256=$hash}, @{id='run-b';sha256=$hash})
    $reported = @(@{run_id='run-c';payload_sha256=$hash}, @{run_id='run-d';payload_sha256=$hash})
    $groups = @(1..5 | ForEach-Object { @{
        unit_id="unit-$_"; eligible_visits=2; detections=1; nondetections=1; effort_seconds=60
    } })
    $originals = @(1..25 | ForEach-Object { @{
        id="original-$_"; kind='image'; sha256=('{0:x64}' -f $_)
    } })
    $taxonomy = $owned + @{
        project_id='source-project'; proposal_id='taxon-proposal'; proposal_sha256=$hash; assessment_id='assessment-id'
        result_sha256=$hash; graph_id='graph-id'; graph_sha256=$hash; exported_file_sha256=$hash
        two_fixture_role_revisions=@('author-role', 'reviewer-role'); originals=$originals; grouped_result=$groups
        runs=$reported
    }
    $audio = @{surface='tauri-webview2'; version=$version; schema=$schema; generated_fixture=$true;
        recording_id='original.wav'; review_id='audio-review'; anchor_id='clock';
        fixture='generated.wav'; source_sha256=$hash; report_sha256=$hash; export_sha256=$hash; replays=$reported }
    $spectral = $owned + @{
        project_id='spectral-project'; acquisition_sha256=$hash; graph_sha256=$hash; runs=$typed
        export_sha256=$hash; tiff_sha256=$second
        record=@{id='spectral';project_id='spectral-project';content_sha256=$hash;snapshot=@{
            selection=@{acquisition_sha256=$hash}
            acquisition=@{bands=@(
                @{original_sha256=$hash;image_id='red';calibration=@{white_dn=40}},
                @{original_sha256=$second;image_id='nir';calibration=@{white_dn=40}}
            )}
            result=@{status='available';valid_pixels=6}
        }}
    }
    $correction = @{content_sha256=$hash; receipt=@{original_sha256=$hash; image_id='original-image'}}
    $underwater = $owned + @{
        fixture_source='installed_scratch_detector'; source_training_run_id='training-run';
        recipe=$correction; image_id='original-image'; job='inference-job'; original_sha256=$hash; model_sha256=$second
        saved_graph_runs=@(
            @{ id='underwater-run-a';graph_sha256=$hash;payload_sha256=$second },
            @{ id='underwater-run-b';graph_sha256=$hash;payload_sha256=$second }
        ); raw_axes_reopened=$true; polygon_and_raster_reused_rendition=$true; original_bytes_match=$true
        source_pixel_predictions=@(@{id='pending-prediction'})
    }
    $exports = @{taxonomy=$hash;audio=$hash;spectral_json=$hash;spectral_tiff=$second}
    Assert-ReefVisionInstalledResearchToolsResults $taxonomy $audio $spectral $underwater $exports $version $schema
    Assert-True $true 'Bound, independent generated research tools evidence qualifies.'
    $taxonomy.surface = 'source-browser'
    Assert-Throws { Assert-ReefVisionInstalledResearchToolsResults $taxonomy $audio $spectral $underwater $exports $version $schema } 'Source-browser proof cannot qualify as installed.'
    $taxonomy.surface = 'tauri-webview2'
    $taxonomy.two_fixture_role_revisions = @('author-role','author-role')
    Assert-Throws { Assert-ReefVisionInstalledResearchToolsResults $taxonomy $audio $spectral $underwater $exports $version $schema } 'A repeated role revision cannot qualify as independent.'
    $taxonomy.two_fixture_role_revisions = @('author-role','reviewer-role')
    $exports.audio = $second
    Assert-Throws { Assert-ReefVisionInstalledResearchToolsResults $taxonomy $audio $spectral $underwater $exports $version $schema } 'A substituted downloaded report cannot qualify.'
    $exports.audio = $hash
    $spectral.record.snapshot.acquisition.bands[1].original_sha256 = $hash
    Assert-Throws { Assert-ReefVisionInstalledResearchToolsResults $taxonomy $audio $spectral $underwater $exports $version $schema } 'Identical bytes cannot stand in for two spectral bands.'
    $spectral.record.snapshot.acquisition.bands[1].original_sha256 = $second
    $underwater.saved_graph_runs[1].id = $underwater.saved_graph_runs[0].id
    Assert-Throws { Assert-ReefVisionInstalledResearchToolsResults $taxonomy $audio $spectral $underwater $exports $version $schema } 'A duplicate workflow run cannot qualify for replay.'
}

$slot = [datetimeoffset]'2026-11-20T15:00:10Z'
$clockWitness = @{ schedule = @{ next_due_at = $slot.ToString('o'); interval_seconds = 20 } }
$restart = Get-ReefVisionScheduleRestartTime $clockWitness $slot.AddSeconds(-5)
Assert-True ($restart -eq $slot.AddMilliseconds(21500)) 'Scheduler restart must cross the next slot, its interval and a timing margin.'
Assert-Throws { Get-ReefVisionScheduleRestartTime $clockWitness $slot } 'A desktop that closes at its next due slot cannot prove a missed interval.'
Assert-Throws { Get-ReefVisionScheduleRestartTime $clockWitness $slot.AddSeconds(-60) } 'A witness for a different future interval cannot extend a stopped run indefinitely.'

& {
    function Get-NetTCPConnection {
        [CmdletBinding()]
        param($LocalPort, $State)
        [pscustomobject]@{ LocalAddress='127.0.0.1'; OwningProcess=4321 }
    }
    function Get-CimInstance($ClassName, $Filter) {
        if ($Filter -ne 'ProcessId = 4321') { throw 'Unexpected fixture process lookup.' }
        [pscustomobject]@{ ExecutablePath='C:\unexpected\reefvision-api.exe'; ParentProcessId=1200 }
    }
    function Invoke-RestMethod { $script:unexpectedScheduleApiCall = $true }
    $script:unexpectedScheduleApiCall = $false
    Assert-Throws {
        Get-ReefVisionInstalledScheduleBackend -Port 9876 -DesktopProcessId 1200 `
            -BrowserSid 'fixture-sid' -BackendExecutable 'C:\installed\reefvision-api.exe' `
            -Profile 'C:\isolated\scheduled' -Version '1.7.0' -Revision 'b17_monitor_0003'
    } 'An unrelated loopback listener cannot enter the scheduler fixture.'
    Assert-True (-not $script:unexpectedScheduleApiCall) 'The unrelated scheduler listener received a probe before being bound to the MSI.'
}

& {
    $expectedExe = 'C:\installed\reefvision-api.exe'
    $expectedProfile = 'C:\isolated\scheduled'
    $observedProfile = $expectedProfile
    $expectedVersion = '1.7.0'
    function Get-NetTCPConnection {
        [CmdletBinding()]
        param($LocalPort, $State)
        [pscustomobject]@{ LocalAddress='127.0.0.1'; OwningProcess=4321 }
    }
    function Get-CimInstance($ClassName, $Filter) {
        if ($Filter -ne 'ProcessId = 4321') { throw 'Unexpected fixture process lookup.' }
        [pscustomobject]@{ ExecutablePath=$expectedExe; ParentProcessId=1200 }
    }
    function Invoke-CimMethod { [pscustomobject]@{ ReturnValue=0; Sid='fixture-sid' } }
    function Get-ReefVisionProcessIntegrity { 8192 }
    function Get-Process { [pscustomobject]@{ Id=4321 } }
    function Get-FileHash { [pscustomobject]@{ Hash=('a' * 64) } }
    function Invoke-RestMethod($Uri, [switch]$NoProxy, $TimeoutSec) {
        if ($Uri -like '*/system/version') {
            return [pscustomobject]@{
                application_version=$expectedVersion; current_schema_revision='b17_monitor_0003'
                data_dir=$observedProfile; database_path=(Join-Path $observedProfile 'reefvision.db')
            }
        }
        if ($Uri -like '*/system/migrations/status') {
            return [pscustomobject]@{ schema_status='up_to_date';current_schema_revision='b17_monitor_0003' }
        }
        throw 'Unexpected schedule identity probe.'
    }
    $pins = @{
        Port=9876; DesktopProcessId=1200; BrowserSid='fixture-sid'; BackendExecutable=$expectedExe
        Profile=$expectedProfile; Version='1.7.0'; Revision='b17_monitor_0003'
    }
    $observed = Get-ReefVisionInstalledScheduleBackend @pins
    Assert-True ($observed.exact_profile_verified -and $observed.pid -eq 4321) 'Schedule backend must verify both process and marked profile before use.'
    $observedProfile = 'C:\unrelated\scheduled'
    Assert-Throws { Get-ReefVisionInstalledScheduleBackend @pins } 'A scheduler profile mismatch must stop before Playwright seeds the project.'
    $observedProfile = $expectedProfile
    $expectedVersion = '1.6.0'
    Assert-Throws { Get-ReefVisionInstalledScheduleBackend @pins } 'A stale installed version must stop before Playwright seeds the project.'
}

& {
    $script:backupAttempts = 0
    $script:unrelatedConflict = $false
    function Invoke-RestMethod {
        param($Uri, $Method, $ContentType, $Body, [switch]$NoProxy, $TimeoutSec,
            [switch]$SkipHttpErrorCheck, $StatusCodeVariable)
        if ($Method -ne 'Post' -or $Uri -ne 'http://127.0.0.1:12345/api/v1/backups') {
            throw 'Unexpected fixture request.'
        }
        $script:backupAttempts++
        if ($script:backupAttempts -eq 1) {
            Set-Variable -Scope 1 -Name $StatusCodeVariable -Value 409
            $detail = if ($script:unrelatedConflict) { 'Different conflict' } else {
                'Backups require an idle background queue; wait for current jobs to finish first'
            }
            return [pscustomobject]@{detail=$detail}
        }
        Set-Variable -Scope 1 -Name $StatusCodeVariable -Value 201
        return [pscustomobject]@{job=[pscustomobject]@{id='only-created-job'}}
    }

    $created = New-ReefVisionAcceptanceBackup -Api 'http://127.0.0.1:12345/api/v1'
    Assert-True ($created.job.id -ceq 'only-created-job' -and $script:backupAttempts -eq 2) 'Upgrade must wait for the predecessor background queue before snapshotting it.'
    $script:backupAttempts = 0
    $script:unrelatedConflict = $true
    Assert-Throws { New-ReefVisionAcceptanceBackup -Api 'http://127.0.0.1:12345/api/v1' } 'Another backup conflict must be reported immediately.'
    Assert-True ($script:backupAttempts -eq 1) 'Only the explicit idle-queue conflict is retryable.'
}

$journeyFailure = Get-ReefVisionInstalledJourneyEvidence { throw 'Fixture WebView2 attach timeout.' }
Assert-True ($journeyFailure.status -eq 'FAIL') 'A failed installed journey must remain failed while the independent MSI lifecycle checks run.'
Assert-True ($journeyFailure.detail -eq 'Fixture WebView2 attach timeout.') 'The retained journey failure must identify the original error.'
$journeySuccess = Get-ReefVisionInstalledJourneyEvidence {
    [pscustomobject]@{
        completed_journeys = 10; graph_record_id = 'graph-id'; first_run_id = 'first'; replay_run_id = 'second'
        artifact = [pscustomobject]@{ payload_sha256 = 'comparison-digest' }
        ordinary_detector = [pscustomobject]@{ model_id = 'detector-id'; checkpoint_sha256 = 'checkpoint-digest' }
        backup_restore = [pscustomobject]@{ restore_job_id = 'restore-id'; restored_files = 3 }
    }
}
Assert-True ($journeySuccess.status -eq 'PASS' -and $journeySuccess.detail.Contains('comparison-digest') -and $journeySuccess.detail.Contains('checkpoint-digest')) 'Successful journeys must retain the spatial export and the trained detector identities.'
Assert-True ($journeySuccess.detail.Contains('restore-id') -and $journeySuccess.detail.Contains('3 verified files')) 'Successful journeys must retain the managed restore job and recovered file count.'

$oldActions = $env:GITHUB_ACTIONS
$oldRunner = $env:RUNNER_ENVIRONMENT
try {
    $env:GITHUB_ACTIONS = 'true'
    $env:RUNNER_ENVIRONMENT = 'self-hosted'
    Assert-Throws { Assert-ReefVisionHostedStandardUserMode } 'A self-hosted or physical Windows machine must never enter temporary account provisioning.'
    $env:RUNNER_ENVIRONMENT = 'github-hosted'
    Assert-ReefVisionHostedStandardUserMode
    $unmarked = Join-Path $env:TEMP ('reefvision-unmarked-' + [guid]::NewGuid().ToString('N'))
    Assert-Throws { New-ReefVisionHostedGuiAccount -RunRoot $unmarked } 'Temporary account provisioning must require the disposable acceptance marker.'
    Assert-True ((Get-ReefVisionProcessIntegrity (Get-Process -Id $PID)) -ge 8192) 'The Windows integrity reader did not identify the current token.'
} finally {
    $env:GITHUB_ACTIONS = $oldActions
    $env:RUNNER_ENVIRONMENT = $oldRunner
}

$defaultData = Join-Path $env:APPDATA 'org.reefvision.desktop'
$OldConfig = $env:REEFVISION_CONFIG_DIR
$HadConfig = Test-Path Env:REEFVISION_CONFIG_DIR
try {
    $env:REEFVISION_CONFIG_DIR = 'C:\developer-config-must-not-leak'
    Invoke-ReefVisionIsolatedEnvironment -DataRoot 'C:\isolated-acceptance' -Action {
        Assert-True (-not (Test-Path Env:REEFVISION_CONFIG_DIR)) 'Developer config leaked into acceptance.'
        Assert-True ($env:HF_HOME -eq 'C:\isolated-acceptance\cache\huggingface') 'Hugging Face cache was not isolated.'
        Assert-True ($env:HF_HUB_OFFLINE -eq '1') 'Offline policy was not enforced.'
    }
    Assert-True ($env:REEFVISION_CONFIG_DIR -eq 'C:\developer-config-must-not-leak') 'Caller configuration was not restored.'
} finally {
    if ($HadConfig) { $env:REEFVISION_CONFIG_DIR = $OldConfig } else { Remove-Item Env:REEFVISION_CONFIG_DIR -ErrorAction SilentlyContinue }
}
$browserArgumentsName = 'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'
$originalBrowserArguments = [Environment]::GetEnvironmentVariable($browserArgumentsName, 'Process')
try {
    [Environment]::SetEnvironmentVariable($browserArgumentsName, '--remote-debugging-port=9222', 'Process')
    Invoke-ReefVisionIsolatedEnvironment -DataRoot 'C:\isolated-acceptance' -Action {
        Assert-True (-not (Test-Path Env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS)) 'Inherited WebView2 debugging leaked into ordinary acceptance.'
    }
    Assert-True ($env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS -eq '--remote-debugging-port=9222') 'Caller WebView2 arguments were not restored.'
} finally {
    [Environment]::SetEnvironmentVariable($browserArgumentsName, $originalBrowserArguments, 'Process')
}

$foreignListener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$debugEvidence = Join-Path $env:TEMP ('reefvision-webview2-' + [guid]::NewGuid().ToString('N') + '.log')
try {
    $foreignListener.Start()
    Assert-Throws { Wait-ReefVisionWebView2DebugEndpoint -Port $foreignListener.LocalEndpoint.Port -DesktopProcessId $PID -FailureEvidencePath $debugEvidence } 'An unrelated loopback listener was accepted as WebView2.'
    Assert-True (Test-Path -LiteralPath $debugEvidence) 'A failed WebView2 attach did not record diagnostics.'
    $diagnostic = Get-Content -LiteralPath $debugEvidence -Raw | ConvertFrom-Json
    Assert-True ($diagnostic.expected_port -eq $foreignListener.LocalEndpoint.Port) 'WebView2 diagnostics lost the requested port.'
    Assert-True ($diagnostic.listeners[0].pid -eq $PID -and $diagnostic.listeners[0].expected_owner -eq $false) 'WebView2 diagnostics lost unexpected listener ownership.'
    Assert-True ($diagnostic.version_probe.attempt_count -eq 0) 'An unrelated listener received an unsafe CDP probe.'
} finally {
    $foreignListener.Stop()
    Remove-Item -LiteralPath $debugEvidence -ErrorAction SilentlyContinue
}
$browserArguments = Get-ReefVisionWebView2DiagnosticArguments '"C:\Edge\msedgewebview2.exe" --remote-debugging-address=127.0.0.1 --remote-debugging-port=39513 "--user-data-dir=C:\private-profile" --unrelated=secret-value'
Assert-True ($browserArguments.remote_debugging_port -eq 39513 -and $browserArguments.remote_debugging_address -eq '127.0.0.1' -and $browserArguments.user_data_dir_arg_present) 'WebView2 diagnostics lost accepted browser launch flags.'
Assert-True (($browserArguments | ConvertTo-Json) -notmatch 'secret-value|private-profile') 'WebView2 diagnostics exposed a raw command line argument.'

& {
    function Get-NetTCPConnection {
        [CmdletBinding()]
        param($LocalPort, $State)
        [pscustomobject]@{ LocalAddress = '127.0.0.1'; OwningProcess = 4321 }
    }
    function Get-CimInstance {
        [CmdletBinding()]
        param($ClassName, $Filter)
        if ($Filter -eq 'ProcessId = 4321') {
            [pscustomobject]@{ Name = 'msedgewebview2.exe'; ParentProcessId = $PID }
        }
    }
    function Invoke-RestMethod($Uri, [switch]$NoProxy, $TimeoutSec, $StatusCodeVariable) {
        $script:fixtureRequests++
        Set-Variable -Name $StatusCodeVariable -Value 200 -Scope 1
        [pscustomobject]@{ webSocketDebuggerUrl = $script:debugFixtureEndpoint }
    }
    function Invoke-CimMethod($InputObject, $MethodName) {
        [pscustomobject]@{ Sid = 'S-1-5-21-100-200-300-1002'; ReturnValue = 0 }
    }
    try {
        $script:debugFixtureEndpoint = 'ws://127.0.0.1:39513/devtools/browser/abcdef-1234'
        $script:fixtureRequests = 0
        Assert-Throws { Wait-ReefVisionWebView2DebugEndpoint -Port 39513 -DesktopProcessId $PID -ExpectedBrowserSid 'S-1-5-21-100-200-300-1001' } 'A browser launched by another Windows user was accepted.'
        Assert-True ($script:fixtureRequests -eq 0) 'A browser with the wrong Windows account received a CDP probe.'
        $attachment = Wait-ReefVisionWebView2DebugEndpoint -Port 39513 -DesktopProcessId $PID -ExpectedBrowserSid 'S-1-5-21-100-200-300-1002' -AttachmentEvidencePath $debugEvidence
        Assert-True ($attachment -eq $script:debugFixtureEndpoint) 'The owned WebView2 endpoint for the ordinary account was rejected.'
        $receipt = Get-Content -LiteralPath $debugEvidence -Raw
        Assert-True (($receipt | ConvertFrom-Json).listeners[0].owner_sid -eq 'S-1-5-21-100-200-300-1002' -and $receipt -notmatch 'abcdef-1234') 'The attach report must record the validated Windows owner without publishing the WebSocket token.'
        Remove-Item -LiteralPath $debugEvidence
        $attached = Wait-ReefVisionWebView2DebugEndpoint -Port 39513 -DesktopProcessId $PID -FailureEvidencePath $debugEvidence
        Assert-True ($attached -eq $script:debugFixtureEndpoint) 'Owned loopback WebView2 endpoint was not accepted.'
        Assert-True (-not (Test-Path -LiteralPath $debugEvidence)) 'A successful WebView2 attach wrote failure evidence.'

        $script:debugFixtureEndpoint = 'ws://127.0.0.1:39513/unexpected/private-endpoint-value'
        Assert-Throws { Wait-ReefVisionWebView2DebugEndpoint -Port 39513 -DesktopProcessId $PID -FailureEvidencePath $debugEvidence } 'An unexpected CDP route was accepted.'
        $raw = Get-Content -LiteralPath $debugEvidence -Raw
        $diagnostic = $raw | ConvertFrom-Json
        Assert-True ($diagnostic.version_probe.result -eq 'unexpected_endpoint' -and $diagnostic.version_probe.status -eq 200) 'WebView2 diagnostics lost the version probe outcome.'
        Assert-True ($raw -notmatch 'private-endpoint-value') 'WebView2 diagnostics exposed an untrusted version response.'
    } finally {
        Remove-Item -LiteralPath $debugEvidence -ErrorAction SilentlyContinue
        Remove-Variable -Name debugFixtureEndpoint,fixtureRequests -Scope Script -ErrorAction SilentlyContinue
    }
}

$safeRoot = Join-Path $env:SystemDrive 'reefvision-clean-acceptance-tests'
Assert-True ((Assert-ReefVisionSafeAcceptanceRoot -Path $safeRoot -RepositoryRoot $Root -DefaultDataRoot $defaultData) -eq (Resolve-ReefVisionAcceptancePath $safeRoot)) 'Safe temp root was rejected.'
# A disposable directory under C:\ must be allowed, but C:\ itself and
# Windows/Program Files/repository/user-data directories must stay protected.
$driveRoot = [System.IO.Path]::GetPathRoot($safeRoot)
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path $driveRoot -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Drive root must be rejected.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path (Join-Path $env:windir 'reefvision-unsafe-test') -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Windows directory descendants must be rejected.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path (Join-Path $env:ProgramFiles 'reefvision-unsafe-test') -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Program Files descendants must be rejected.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path (Join-Path $Root 'reefvision-unsafe-test') -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Repository descendants must be rejected.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path $Root -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Repository root must be rejected.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path $defaultData -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Normal app-data root must be rejected.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path (Split-Path -Parent $defaultData) -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Parent of normal app-data root must be rejected.'

# Lexical containment is insufficient: a junction beneath a disposable path
# could redirect MSI install/cleanup operations into non-disposable user data.
$junctionRoot = Join-Path $env:TEMP ('reefvision-reparse-' + [guid]::NewGuid().ToString('N'))
$junctionTarget = Join-Path $junctionRoot 'target'
$junctionPath = Join-Path $junctionRoot 'junction'
New-Item -ItemType Directory -Path $junctionTarget -Force | Out-Null
try {
    New-Item -ItemType Junction -Path $junctionPath -Target $junctionTarget -ErrorAction Stop | Out-Null
    Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path $junctionPath -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Junction acceptance root must be rejected.'
    Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path (Join-Path $junctionPath 'nested') -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Nested path through junction must be rejected.'
    Assert-True (Test-Path -LiteralPath $junctionTarget -PathType Container) 'Junction safety check modified its target.'
} finally {
    # Directory.Delete on a junction removes the link itself, never the target.
    if ([System.IO.Directory]::Exists($junctionPath)) { [System.IO.Directory]::Delete($junctionPath) }
    if ([System.IO.Directory]::Exists($junctionRoot)) { [System.IO.Directory]::Delete($junctionRoot, $true) }
}

$arguments = New-ReefVisionMsiArguments -Action Install -PackageOrProduct 'C:\build\ReefVision.msi' -InstallRoot 'C:\rv-test\install' -LogPath 'C:\rv-test\install.log'
Assert-True ($arguments[0] -eq '/i') 'Install command does not use /i.'
Assert-True (($arguments -join ' ') -match 'INSTALLDIR=') 'Install command omitted isolated INSTALLDIR.'
$uninstall = New-ReefVisionMsiArguments -Action Uninstall -PackageOrProduct '{00000000-0000-0000-0000-000000000000}' -LogPath 'C:\rv-test\uninstall.log'
Assert-True ($uninstall[0] -eq '/x') 'Uninstall command does not use /x.'
Assert-True ((ConvertTo-ReefVisionVersionString ' 1.0.3 ') -eq '1.0.3') 'MSI version comparison did not normalize COM padding.'

function Get-ItemProperty {
    [CmdletBinding()]
    param([Parameter(Position = 0)]$Path)
    return $script:registrationFixtures
}

$registrationFixtures = @()
Assert-True (@(Get-ReefVisionInstalledRegistrations).Count -eq 0) 'Empty registration enumeration was not handled.'
$registrationFixtures = @(
    [pscustomobject]@{ UninstallString = 'missing display name' },
    [pscustomobject]@{ DisplayName = 'Unrelated Product' },
    [pscustomobject]@{ DisplayName = 'ReefVision' }
)
$registrations = @(Get-ReefVisionInstalledRegistrations)
Assert-True ($registrations.Count -eq 1) 'Registration filtering did not safely handle a missing DisplayName or a single match.'
Assert-True ($registrations[0].DisplayName -eq 'ReefVision') 'Registration filtering returned the wrong single match.'
$registrationFixtures += [pscustomobject]@{ DisplayName = 'ReefVision 1.0.0' }
Assert-True (@(Get-ReefVisionInstalledRegistrations).Count -eq 2) 'Multiple registration results were not preserved as an array.'

# Historical profiles must be verified and staged through real contained files.
# A source-text assertion would not catch copying a backup into the live profile,
# accepting a changed asset, or traversing outside the fixture root.
$lineageRoot = Join-Path $Root ('.artifacts\lineage-harness-' + [guid]::NewGuid().ToString('N'))
$lineageProfile = Join-Path $lineageRoot 'draft-1.4-0038'
$lineageAsset = Join-Path $lineageProfile 'projects\lineage-acceptance\assets\reef.obj'
$lineageDatabase = Join-Path $lineageProfile 'reefvision.db'
$lineageBackup = Join-Path $lineageRoot 'draft-1.4-0038.pre-upgrade.db'
$lineageManifest = Join-Path $lineageRoot 'manifest.json'
$lineageVerification = Join-Path $lineageRoot 'verification.json'
New-Item -ItemType Directory -Path (Split-Path -Parent $lineageAsset) -Force | Out-Null
[IO.File]::WriteAllBytes($lineageDatabase, [Text.Encoding]::UTF8.GetBytes('profile-database'))
[IO.File]::WriteAllBytes($lineageBackup, [Text.Encoding]::UTF8.GetBytes('verified-backup'))
[IO.File]::WriteAllBytes($lineageAsset, [Text.Encoding]::UTF8.GetBytes('v 0 0 0'))
$lineageRecordId = '04f9c44e-d30e-494f-ab1e-9aa3b4db02e9'
$lineageProjectId = '507af087-ff80-458f-9470-9b3bdc980a5b'
$lineageManifestValue = [ordered]@{
    schema_version = 'reefvision-windows-lineage-fixtures-1'
    fixture_kind = 'synthetic_engineering'
    profiles = @([ordered]@{
        name = 'draft-1.4-0038'
        revision = '0038'
        project_id = $lineageProjectId
        database = 'draft-1.4-0038/reefvision.db'
        database_sha256 = (Get-FileHash -LiteralPath $lineageDatabase -Algorithm SHA256).Hash.ToLowerInvariant()
        backup = 'draft-1.4-0038.pre-upgrade.db'
        backup_sha256 = (Get-FileHash -LiteralPath $lineageBackup -Algorithm SHA256).Hash.ToLowerInvariant()
        records = @([ordered]@{kind='spatial_source_asset';id=$lineageRecordId;sha256=(Get-FileHash -LiteralPath $lineageAsset -Algorithm SHA256).Hash.ToLowerInvariant()})
        source_files = @([ordered]@{path='draft-1.4-0038/projects/lineage-acceptance/assets/reef.obj';sha256=(Get-FileHash -LiteralPath $lineageAsset -Algorithm SHA256).Hash.ToLowerInvariant()})
    })
}
$lineageManifestValue | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $lineageManifest -Encoding utf8
[ordered]@{profile='draft-1.4-0038';status='verified';revision='0038';project_id=$lineageProjectId;record_ids=@($lineageRecordId)} |
    ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $lineageVerification -Encoding utf8
try {
    $fixture = Read-ReefVisionLineageFixture -ManifestPath $lineageManifest -ProfileName 'draft-1.4-0038' -VerificationPath $lineageVerification
    Assert-True ($fixture.revision -eq '0038') 'Lineage revision was not read from the verified manifest.'
    Assert-True ($fixture.project_id -eq $lineageProjectId) 'Lineage project ID changed during preflight.'
    Assert-True (@($fixture.record_ids).Count -eq 1 -and $fixture.record_ids[0] -eq $lineageRecordId) 'Lineage record IDs did not match independent verification.'

    $stagedRoot = Join-Path $lineageRoot 'staged-live'
    New-Item -ItemType Directory -Path $stagedRoot -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $stagedRoot '.reefvision-clean-install-acceptance') -Value 'owned'
    $staged = Copy-ReefVisionLineageProfile -Fixture $fixture -DataRoot $stagedRoot
    Assert-True ([Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($staged.database)) -eq 'profile-database') 'Live lineage staging did not use the declared profile database.'
    Assert-True (-not (Test-Path (Join-Path $stagedRoot 'draft-1.4-0038.pre-upgrade.db'))) 'Pre-upgrade backup was copied into the live data profile.'
    Assert-True ([Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes((Join-Path $stagedRoot 'projects\lineage-acceptance\assets\reef.obj'))) -eq 'v 0 0 0') 'Lineage source asset was not staged with its managed relative path.'
    Assert-Throws { Copy-ReefVisionLineageProfile -Fixture $fixture -DataRoot $stagedRoot | Out-Null } 'Lineage staging must not overwrite an existing live database.'

    $restoreRoot = Join-Path $lineageRoot 'staged-restore'
    New-Item -ItemType Directory -Path $restoreRoot -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $restoreRoot '.reefvision-clean-install-acceptance') -Value 'owned'
    $restored = Copy-ReefVisionLineageProfile -Fixture $fixture -DataRoot $restoreRoot -UseBackup
    Assert-True ([Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($restored.database)) -eq 'verified-backup') 'Separate restore profile did not use the verified pre-upgrade backup.'

    [IO.File]::WriteAllBytes($lineageDatabase, [Text.Encoding]::UTF8.GetBytes('tampered-database'))
    Assert-Throws { Read-ReefVisionLineageFixture -ManifestPath $lineageManifest -ProfileName 'draft-1.4-0038' -VerificationPath $lineageVerification | Out-Null } 'Changed lineage database bytes must fail before desktop launch.'
    [IO.File]::WriteAllBytes($lineageDatabase, [Text.Encoding]::UTF8.GetBytes('profile-database'))

    [ordered]@{profile='draft-1.4-0038';status='verified';revision='0038';project_id=$lineageProjectId;record_ids=@('different-record')} |
        ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $lineageVerification -Encoding utf8
    Assert-Throws { Read-ReefVisionLineageFixture -ManifestPath $lineageManifest -ProfileName 'draft-1.4-0038' -VerificationPath $lineageVerification | Out-Null } 'Verification record IDs must match the fixture manifest.'
    [ordered]@{profile='draft-1.4-0038';status='verified';revision='0038';project_id=$lineageProjectId;record_ids=@($lineageRecordId)} |
        ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $lineageVerification -Encoding utf8

    [IO.File]::WriteAllBytes($lineageAsset, [Text.Encoding]::UTF8.GetBytes('tampered'))
    Assert-Throws { Read-ReefVisionLineageFixture -ManifestPath $lineageManifest -ProfileName 'draft-1.4-0038' -VerificationPath $lineageVerification | Out-Null } 'Changed lineage source bytes must fail preflight.'
    [IO.File]::WriteAllBytes($lineageAsset, [Text.Encoding]::UTF8.GetBytes('v 0 0 0'))

    $unsafeManifest = Join-Path $lineageRoot 'unsafe-manifest.json'
    $unsafe = $lineageManifestValue | ConvertTo-Json -Depth 12 | ConvertFrom-Json
    $unsafe.profiles[0].database = '../outside.db'
    $unsafe | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $unsafeManifest -Encoding utf8
    Assert-Throws { Read-ReefVisionLineageFixture -ManifestPath $unsafeManifest -ProfileName 'draft-1.4-0038' -VerificationPath $lineageVerification | Out-Null } 'Lineage paths outside the fixture root must fail preflight.'
} finally {
    if (-not (Test-ReefVisionPathWithin -Path $lineageRoot -Parent (Join-Path $Root '.artifacts'))) { throw 'Unsafe lineage harness cleanup path.' }
    Remove-Item -LiteralPath $lineageRoot -Recurse -Force
}

# Real pixel decoding is required: HTTP success and byte length alone do not
# establish that an installed camera JPEG is viewable in the original frame.
Add-Type -AssemblyName System.Drawing
$cameraBitmap = [System.Drawing.Bitmap]::new(7, 5)
$cameraJpegStream = [System.IO.MemoryStream]::new()
$cameraPngStream = [System.IO.MemoryStream]::new()
try {
    $cameraBitmap.Save($cameraJpegStream, [System.Drawing.Imaging.ImageFormat]::Jpeg)
    $cameraBitmap.Save($cameraPngStream, [System.Drawing.Imaging.ImageFormat]::Png)
    $cameraJpegBytes = [byte[]]$cameraJpegStream.ToArray()
    $cameraPngBytes = [byte[]]$cameraPngStream.ToArray()
    $jpegRaster = Assert-ReefVisionCameraRaster -Bytes $cameraJpegBytes -ContentType 'image/jpeg' -ExpectedWidth 7 -ExpectedHeight 5
    Assert-True ($jpegRaster.width -eq 7 -and $jpegRaster.height -eq 5) 'JPEG source raster dimensions were not decoded.'
    $pngRaster = Assert-ReefVisionCameraRaster -Bytes $cameraPngBytes -ContentType 'image/png' -ExpectedWidth 7 -ExpectedHeight 5
    Assert-True ($pngRaster.media_type -eq 'image/png') 'PNG display raster was not decoded.'
    Assert-ReefVisionStableCameraDisplay -InitialBytes $cameraPngBytes -RestartBytes ([byte[]]$cameraPngBytes.Clone()) -InitialContentType 'image/png' -RestartContentType 'image/png'
    Assert-True $true 'Identical camera display bytes must remain valid after restart.'
    Assert-Throws { Assert-ReefVisionStableCameraDisplay -InitialBytes $cameraPngBytes -RestartBytes $cameraPngBytes -InitialContentType 'image/png' -RestartContentType 'image/jpeg' } 'Camera display media type changes must fail.'
    $changedPngStream = [System.IO.MemoryStream]::new()
    try {
        $cameraBitmap.SetPixel(0, 0, [System.Drawing.Color]::Red)
        $cameraBitmap.Save($changedPngStream, [System.Drawing.Imaging.ImageFormat]::Png)
        $changedPngBytes = [byte[]]$changedPngStream.ToArray()
        $null = Assert-ReefVisionCameraRaster -Bytes $changedPngBytes -ContentType 'image/png' -ExpectedWidth 7 -ExpectedHeight 5
        Assert-Throws { Assert-ReefVisionStableCameraDisplay -InitialBytes $cameraPngBytes -RestartBytes $changedPngBytes -InitialContentType 'image/png' -RestartContentType 'image/png' } 'Valid same-sized camera rasters with changed pixels must fail.'
    } finally { $changedPngStream.Dispose() }
    Assert-Throws { Assert-ReefVisionStableCameraDisplay -InitialBytes $cameraPngBytes -RestartBytes ([byte[]]@()) -InitialContentType 'image/png' -RestartContentType 'image/png' } 'Empty restarted display must fail.'
    Assert-Throws { Assert-ReefVisionCameraRaster -Bytes $cameraJpegBytes -ContentType 'image/png' -ExpectedWidth 7 -ExpectedHeight 5 | Out-Null } 'JPEG bytes must not pass as PNG.'
    Assert-Throws { Assert-ReefVisionCameraRaster -Bytes $cameraPngBytes -ContentType 'image/jpeg' -ExpectedWidth 7 -ExpectedHeight 5 | Out-Null } 'PNG bytes must not pass as JPEG.'
    Assert-Throws { Assert-ReefVisionCameraRaster -Bytes $cameraJpegBytes -ContentType 'image/jpeg' -ExpectedWidth 5 -ExpectedHeight 7 | Out-Null } 'Rotated or transposed scientific source dimensions must fail.'
    Assert-Throws { Assert-ReefVisionCameraRaster -Bytes ([byte[]](1, 2, 3)) -ContentType 'image/jpeg' -ExpectedWidth 7 -ExpectedHeight 5 | Out-Null } 'Nonimage bytes must not pass camera acceptance.'
    Assert-Throws { Assert-ReefVisionCameraRaster -Bytes $cameraJpegBytes -ContentType 'image/jpeg' -ExpectedWidth 0 -ExpectedHeight 5 | Out-Null } 'Invalid expected source dimensions must fail.'
} finally {
    $cameraPngStream.Dispose()
    $cameraJpegStream.Dispose()
    $cameraBitmap.Dispose()
}

$acceptancePath = Join-Path $PSScriptRoot 'acceptance-windows-clean-install.ps1'
$parseTokens = $null
$parseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    $acceptancePath,
    [ref]$parseTokens,
    [ref]$parseErrors
)
Assert-True (@($parseErrors).Count -eq 0) "Windows acceptance PowerShell syntax invalid: $($parseErrors -join '; ')"
$acceptanceParameterNames = @($parseTokens | Out-Null)
$acceptanceAst = [System.Management.Automation.Language.Parser]::ParseFile(
    $acceptancePath,
    [ref]$parseTokens,
    [ref]$parseErrors
)
$acceptanceParameterNames = @($acceptanceAst.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath })
foreach ($lineageParameter in @(
    'LineageManifestPath',
    'LineageProfile',
    'LineageVerificationPath',
    'ExpectedInitialSchemaRevision',
    'VerifyPreviousInstallerRejectsUpgradedProfile'
)) {
    Assert-True ($acceptanceParameterNames -contains $lineageParameter) "Installed lineage CLI is missing -$lineageParameter."
}
$acceptanceScript = Get-Content -LiteralPath $acceptancePath -Raw
$installedJourneys = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'lib\windows-spatial-webview2-acceptance.ps1') -Raw
Assert-True ($installedJourneys.Contains("'ordinary-detector-live.spec.ts'") -and $installedJourneys.Contains("REEFVISION_ORDINARY_DETECTOR_ACCEPTANCE = '1'")) 'The installed desktop must execute the opt-in ordinary detector training, review and export journey.'
Assert-True ($installedJourneys.Contains("'ordinary-detector-evidence.json'")) 'Installed acceptance must retain the actual software and checkpoint evidence for the detector journey.'
$retentionCheck = $acceptanceScript.IndexOf('Isolated project data remained after uninstall.')
$journeyFailureGate = $acceptanceScript.IndexOf('throw $report.spatial_workflow.detail')
Assert-True ($retentionCheck -ge 0 -and $journeyFailureGate -gt $retentionCheck) 'A failed installed journey must still fail acceptance after uninstall and data retention are recorded.'

# Exercise the actual rejection probe without starting or killing a desktop.
& {
    $definition = $acceptanceAst.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq 'Assert-HistoricalDesktopRejectsProfile'
    }, $false)
    . ([scriptblock]::Create($definition.Extent.Text))
    $fakeProcess = [pscustomobject]@{HasExited=$false;Killed=$false;GracefulClose=$false}
    $fakeProcess | Add-Member -MemberType ScriptMethod -Name Refresh -Value {}
    $fakeProcess | Add-Member -MemberType ScriptMethod -Name Kill -Value {
        $this.Killed = $true
        $this.HasExited = $true
    }
    $fakeProcess | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value { param($Milliseconds) return $this.HasExited }
    function Start-AcceptanceDesktop([string]$ProfileDataRoot) { return $fakeProcess }
    function Stop-AcceptanceDesktop($Process) { $Process.GracefulClose = $true }
    $probeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("reefvision-rejection-test-" + [guid]::NewGuid().ToString('N'))
    try {
        New-Item -ItemType Directory -Path (Join-Path $probeRoot 'logs'), (Join-Path $probeRoot 'runtime') -Force | Out-Null
        $log = Join-Path $probeRoot 'logs\backend.log'
        Set-Content -LiteralPath $log -Value "Can't locate revision identified by 'different_revision'"
        $fakeProcess.HasExited = $true
        Assert-Throws {
            Assert-HistoricalDesktopRejectsProfile -ProfileDataRoot $probeRoot -RejectedRevision 'b14_spatial_0040' | Out-Null
        } 'An unrelated rejection must not count as acceptance.'
        Assert-True (-not $fakeProcess.Killed) 'An unrelated failure must not use rejection-specific cleanup.'

        $fakeProcess.HasExited = $false
        Set-Content -LiteralPath $log -Value "Can't locate revision identified by 'b14_spatial_0040'"
        $port = Join-Path $probeRoot 'runtime\backend-port.txt'
        Set-Content -LiteralPath $port -Value '12345'
        Assert-Throws {
            Assert-HistoricalDesktopRejectsProfile -ProfileDataRoot $probeRoot -RejectedRevision 'b14_spatial_0040' | Out-Null
        } 'A published API port must fail despite a matching log.'
        Assert-True ($fakeProcess.GracefulClose -and -not $fakeProcess.Killed) 'An unexpected API startup must retain the normal cleanup path.'

        Remove-Item -LiteralPath $port
        $fakeProcess.GracefulClose = $false
        $result = Assert-HistoricalDesktopRejectsProfile -ProfileDataRoot $probeRoot -RejectedRevision 'b14_spatial_0040'
        Assert-True ($result -like '*b14_spatial_0040*' -and $fakeProcess.Killed -and -not $fakeProcess.GracefulClose) 'An explicit rejection must clean up only the disposable failed-start process.'
    } finally {
        Remove-Item -LiteralPath $probeRoot -Recurse -Force
    }
}
foreach ($lineageContract in @(
    'lineage_preflight',
    'lineage_initial_evidence',
    'lineage_final_evidence',
    'lineage_exchange_roundtrip',
    'lineage_restore',
    'historical_schema_rejection',
    'Assert-AcceptanceLineageEvidence',
    'Import-AcceptanceExchange',
    'Assert-HistoricalDesktopRejectsProfile',
    'Copy-ReefVisionLineageProfile -Fixture $LineageFixture -DataRoot $RestoreDataRoot -UseBackup'
)) {
    Assert-True ($acceptanceScript.Contains($lineageContract)) "Installed lineage acceptance is missing contract: $lineageContract"
}
Assert-True ($acceptanceScript.Contains('[void]$view.Execute()')) 'MSI ProductVersion extraction must suppress COM Execute output.'
Assert-True ($acceptanceScript.Contains('[void]$view.Close()')) 'MSI ProductVersion extraction must suppress COM Close output.'
# Guard the packaged acceptance request against retired project templates and
# legacy model catalog selectors. Production API supports blank projects only.
Assert-True ($acceptanceScript.Contains("template='blank'")) 'Acceptance project must use the supported blank template.'
Assert-True (-not $acceptanceScript.Contains("template='octocoral'")) 'Retired octocoral template must not be used.'
Assert-True ($acceptanceScript.Contains('"$api/projects/$projectId/classes"')) 'Blank acceptance project must seed a label class explicitly.'
Assert-True ($acceptanceScript.Contains("selection_kind -eq 'builtin_architecture'")) 'Catalog selection_kind must match the current API.'
Assert-True (-not $acceptanceScript.Contains("selection_kind -eq 'architecture'")) 'Legacy architecture selection kind must not be used.'
Assert-True ($acceptanceScript.Contains('external_annotation_imports = New-ReefVisionEvidenceResult')) 'Installed backend COCO/YOLO evidence must be reported.'
Assert-True ($acceptanceScript.Contains('provider_manifests = New-ReefVisionEvidenceResult')) 'Installed provider-manifest evidence must be reported.'
Assert-True ($acceptanceScript.Contains("'provider-manifests'")) 'Installed acceptance must seed the provider-manifest data directory.'
Assert-True ($acceptanceScript.Contains('advanced-providers/manifests')) 'Installed acceptance must inspect the packaged manifest catalog.'
Assert-True ($acceptanceScript.Contains('source_sha256 -cne $providerManifestHash')) 'Installed acceptance must bind discovery to the exact manifest bytes.'
Assert-True ($acceptanceScript.Contains('execution_surface -ne ''blocked''')) 'Installed acceptance must require a blocked local execution surface.'
Assert-True ($acceptanceScript.Contains('advanced-providers/local_acceptance/preflight')) 'Installed acceptance must exercise fail-closed local preflight.'
# The installed-MSI test can exercise a real camera file when supplied.
# It must remain optional and must verify immutable source bytes as well as
# the display endpoint; a synthetic PNG does not establish camera acceptance.
Assert-True ($acceptanceScript.Contains('[string]$CameraFixturePath')) 'Real camera fixture option is missing.'
Assert-True ($acceptanceScript.Contains('camera_jpeg = if ($CameraFixturePath)')) 'Missing camera fixture must be reported as SKIPPED, never PASS.'
Assert-True ($acceptanceScript.Contains("-ContentType 'image/jpeg'")) 'Camera acceptance must submit actual JPEG media type.'
Assert-True ($acceptanceScript.Contains('$api/images/$cameraId/content')) 'Camera acceptance must retrieve the persisted original bytes.'
Assert-True ($acceptanceScript.Contains('$api/images/$cameraId/display')) 'Camera acceptance must exercise the installed display endpoint.'
Assert-True (($acceptanceScript -split 'Assert-ReefVisionCameraRaster').Count -eq 4) 'Camera acceptance must decode the original, initial display, and restarted display rasters.'
Assert-True ($acceptanceScript.Contains('$persistedCamera = Invoke-RestMethod "$api/images/$cameraId"')) 'Camera metadata must be checked after desktop restart.'
Assert-True ($acceptanceScript.Contains('Camera JPEG original bytes changed or disappeared after desktop restart.')) 'Camera original SHA-256 must be rechecked after restart.'
Assert-True ($acceptanceScript.Contains('Camera JPEG display endpoint failed after desktop restart.')) 'Camera display must be fetched again after restart.'
Assert-True ($acceptanceScript.Contains('source SHA256 $cameraHashBefore unchanged') -or $acceptanceScript.Contains('original SHA256 $cameraHashBefore unchanged')) 'Camera source SHA-256 must be recorded.'
$cameraRestartIndex = $acceptanceScript.IndexOf('$persistedCamera = Invoke-RestMethod "$api/images/$cameraId"')
$cameraPassIndex = $acceptanceScript.IndexOf('$report.camera_jpeg = New-ReefVisionEvidenceResult -Status ''PASS''')
Assert-True ($cameraRestartIndex -ge 0 -and $cameraPassIndex -gt $cameraRestartIndex) 'Camera PASS must be deferred until after restart validation.'
$displayStableIndex = $acceptanceScript.IndexOf('Assert-ReefVisionStableCameraDisplay -InitialBytes')
Assert-True ($displayStableIndex -gt $cameraRestartIndex -and $cameraPassIndex -gt $displayStableIndex) 'Camera PASS must require stable display bytes after restart.'
Assert-True ($acceptanceScript.Contains('display SHA-256 unchanged across restart')) 'Camera evidence must record stable display integrity.'
Assert-True ($acceptanceScript.Contains('original SHA256 $cameraHashBefore unchanged')) 'Camera acceptance must record original SHA-256 integrity evidence.'

Assert-True ($acceptanceScript.Contains('function Import-AcceptanceAnnotations')) 'Windows acceptance must use a real multipart annotation import.'
Assert-True ($acceptanceScript.Contains('cocoResult.boxes_imported -ne 1')) 'COCO imported box acceptance is missing.'
Assert-True ($acceptanceScript.Contains('yoloResult.boxes_imported -ne 1')) 'YOLO imported box acceptance is missing.'
Assert-True ($acceptanceScript.Contains('LiveSam2Acceptance')) 'Live SAM mode must be declared.'
Assert-True ($acceptanceScript.Contains("HF_HUB_OFFLINE'] = '0'")) 'Opt-in live SAM must allow a real network download.'
Assert-True ($acceptanceScript.Contains('samAcceptedMaskId')) 'Live SAM acceptance must validate mask preservation.'
Assert-True ($acceptanceScript.Contains("'api.log', 'api.log.1'")) 'Failed SAM2 acceptance must archive API logs, not only startup backend.log.'
Assert-True ($acceptanceScript.Contains('api.log.tail.log') -or $acceptanceScript.Contains('$logName.tail.log')) 'SAM2 API log archive name must match the uploaded *.log evidence pattern.'
Assert-True ($acceptanceScript.Contains("prefix='live'") -and $acceptanceScript.Contains("prefix='restore'")) 'Installed lineage evidence must retain separate live and restored-profile log tails.'
$initialVersionCheck = '$initialVersion = Get-AcceptanceMsiProperty -Path $initialInstaller -Name ''ProductVersion'''
$initialBackendCheck = 'Assert-AcceptancePackagedBackend -Api $api -ExpectedAppVersion $initialVersion -ExpectedRevision $initialRevision'
$finalBackendCheck = 'Assert-AcceptancePackagedBackend -Api $api -ExpectedAppVersion $ProductVersion -ExpectedRevision $ExpectedSchemaRevision'
$upgradePass = '$report.upgrade = New-ReefVisionEvidenceResult -Status ''PASS'''
Assert-True ($acceptanceScript.Contains($initialVersionCheck) -and $acceptanceScript.Contains($initialBackendCheck)) 'Acceptance must verify which MSI version launched before upgrade.'
Assert-True ($acceptanceScript.Contains('if ($appVersion -ne $ExpectedAppVersion)')) 'The packaged backend version must match the MSI in both launch phases.'
Assert-True ($acceptanceScript.Contains('$migration.current_schema_revision -ne $ExpectedRevision')) 'The candidate backend must reach the configured migration revision.'
$finalCheckIndex = $acceptanceScript.IndexOf($finalBackendCheck)
Assert-True ($finalCheckIndex -ge 0 -and $finalCheckIndex -lt $acceptanceScript.IndexOf($upgradePass)) 'Upgrade PASS must follow candidate API version and migration validation.'
Assert-True ($acceptanceScript -match 'Stop-AcceptanceDesktop\s+\$desktop\s*\r?\n\s*\$projectChecksum\s*=\s*\(Get-FileHash\s+-LiteralPath\s+\(Join-Path\s+\$DataRoot\s+''reefvision\.db''\)') 'Desktop shutdown must occur before hashing reefvision.db.'
Assert-True ($acceptanceScript -match 'Where-Object\s+FullName\s+-eq\s+''reefvision-exchange-manifest\.json''') 'Project Exchange validation does not require the canonical manifest name.'
Assert-True ($acceptanceScript -notmatch 'Where-Object\s+FullName\s+-eq\s+''manifest\.json''') 'Project Exchange validation still accepts the incorrect manifest.json name.'

$desktopWorkflowPath = Join-Path $Root '.github\workflows\build-desktop.yml'
$desktopWorkflow = Get-Content -LiteralPath $desktopWorkflowPath -Raw
. (Join-Path $PSScriptRoot 'lib\node-tools.ps1')
$nodeDiscovery = '$playwrightNode = Find-ReefVisionExecutable -Names ''node.exe'''
$nodeDiscoveryIndex = $desktopWorkflow.IndexOf($nodeDiscovery)
Assert-True ($nodeDiscoveryIndex -ge 0) 'Packaged Playwright must discover a single executable through the Windows Node helper.'
$cleanInstallStep = $desktopWorkflow.Substring($nodeDiscoveryIndex)
Assert-True ($cleanInstallStep.IndexOf('$env:PATH = @(') -gt 0) 'Playwright must capture the absolute Node path before the application PATH is restricted.'
Assert-True ($cleanInstallStep.Contains('-ScheduleWorkflowAcceptance -MonitoringWorkflowAcceptance')) 'The clean role must run monitoring as well as the existing scheduler restart phases.'
foreach ($monitoringArtifact in @('monitoring-workflow-evidence.json','monitoring-playwright.json',
    'monitoring-playwright/**/acquisition-source-evidence.json','monitoring-playwright/**/monitoring-proof.json')) {
    Assert-True ($cleanInstallStep.Contains(".artifacts/windows-clean-acceptance-*/$monitoringArtifact")) "Missing installed evidence retention for $monitoringArtifact."
}

Assert-True ($cleanInstallStep.Contains('-ResearchToolsAcceptance')) 'The clean role must run the 1.8 research tools.'
foreach ($researchArtifact in @('research-tools-evidence.json','research-tools-playwright.json',
    'research-tools-playwright/**/taxonomy-detectability-proof.json','research-tools-playwright/**/bioacoustics-evidence.json',
    'research-tools-playwright/**/multispectral-evidence.json','research-tools-playwright/**/underwater-adjustment-evidence.json')) {
    Assert-True ($cleanInstallStep.Contains(".artifacts/windows-clean-acceptance-*/$researchArtifact")) "Missing installed evidence retention for $researchArtifact."
}

$nodeFixtureRoot = Join-Path $env:TEMP ('reefvision-node-selection-' + [guid]::NewGuid().ToString('N'))
$firstNodeFolder = Join-Path $nodeFixtureRoot 'first'
$secondNodeFolder = Join-Path $nodeFixtureRoot 'second'
$firstNodePath = Join-Path $firstNodeFolder 'node.exe'
$secondNodePath = Join-Path $secondNodeFolder 'node.exe'
$originalPath = $env:PATH
try {
    New-Item -ItemType Directory -Path $firstNodeFolder,$secondNodeFolder -Force | Out-Null
    # The fixture exercises executable discovery only, without launching these files.
    $stub = Join-Path $env:SystemRoot 'System32\cmd.exe'
    Copy-Item -LiteralPath $stub -Destination $firstNodePath
    Copy-Item -LiteralPath $stub -Destination $secondNodePath
    $env:PATH = "$firstNodeFolder;$secondNodeFolder"
    Assert-True (@(Get-Command node -CommandType Application).Count -eq 2) 'The fixture must expose both executable choices.'
    $selectedDriver = Find-ReefVisionExecutable -Names 'node.exe'
    $env:PATH = Join-Path $env:SystemRoot 'System32'
    Assert-True ($selectedDriver -is [string] -and $selectedDriver -ieq $firstNodePath) 'The first Node executable must remain one absolute path after restricting PATH.'
    Assert-True (-not (Get-Command node.exe -CommandType Application -ErrorAction SilentlyContinue)) 'The selected driver must stay off the application PATH.'
} finally {
    $env:PATH = $originalPath
    [IO.File]::Delete($firstNodePath)
    [IO.File]::Delete($secondNodePath)
    foreach ($folder in $firstNodeFolder,$secondNodeFolder,$nodeFixtureRoot) {
        if ([IO.Directory]::Exists($folder)) { [IO.Directory]::Delete($folder) }
    }
}
foreach ($profileName in @('validated-1.3', 'draft-1.4-0038', 'draft-1.4-0039')) {
    Assert-True ($desktopWorkflow.Contains("profile: $profileName")) "Windows lineage matrix is missing $profileName."
}
foreach ($workflowContract in @(
    'windows-lineage-acceptance:',
    'python scripts/create_windows_lineage_fixtures.py',
    'python scripts/verify_windows_lineage_fixture.py',
    "-SourceCommit `$env:SOURCE_COMMIT -RequireProvenance",
    'REEFVISION_1_3_RUN: "43767076956"',
    'f44053a90286ce57cc6f7356be922bcf8ba41e22',
    'gh run download $env:REEFVISION_1_3_RUN --repo Rafael-Del-Valle/ReefVision --name ReefVision-1.3.0-RC-Installer-Part-1',
    'gh run download $env:REEFVISION_1_3_RUN --repo Rafael-Del-Valle/ReefVision --name ReefVision-1.3.0-RC-Installer-Part-2',
    "-Version '1.3.0' -ExpectedFilename 'ReefVision_1.3.0_x64_en-US.msi'",
    'VerifyPreviousInstallerRejectsUpgradedProfile = $true'
)) {
    Assert-True ($desktopWorkflow.Contains($workflowContract)) "Windows lineage workflow is missing contract: $workflowContract"
}

$reportPath = Join-Path $Root ('.artifacts\reefvision-evidence-' + [guid]::NewGuid().ToString('N') + '.json')
$report = [ordered]@{ upgrade = New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'previous installer not supplied'; failure_reason = $null }
Write-ReefVisionEvidenceReport -Report $report -Path $reportPath
$roundTrip = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
Assert-True ($roundTrip.upgrade.status -eq 'SKIPPED') 'Report did not preserve skip semantics.'
Assert-True ($null -eq $roundTrip.failure_reason) 'Report did not preserve an empty failure reason.'
if (-not (Test-ReefVisionPathWithin -Path $reportPath -Parent (Join-Path $Root '.artifacts'))) { throw 'Unsafe harness report cleanup path.' }
Remove-Item -LiteralPath $reportPath -Force

$cleanupRoot = Join-Path $Root ('.artifacts\harness-cleanup-' + [guid]::NewGuid().ToString('N'))
$ownedRun = Join-Path $cleanupRoot 'owned-run'
$foreign = Join-Path $cleanupRoot 'foreign'
New-Item -ItemType Directory -Path $ownedRun,$foreign -Force | Out-Null
Set-Content -LiteralPath (Join-Path $ownedRun '.reefvision-acceptance-run') -Value 'owned'
if (-not (Test-ReefVisionPathWithin -Path $ownedRun -Parent (Join-Path $Root '.artifacts'))) { throw 'Unsafe harness test cleanup path.' }
Remove-Item -LiteralPath $ownedRun -Recurse -Force
Assert-True (-not (Test-Path $ownedRun)) 'Owned run was not removed.'
Assert-True (Test-Path $foreign) 'Cleanup crossed the owned-run boundary.'
if (-not (Test-ReefVisionPathWithin -Path $cleanupRoot -Parent (Join-Path $Root '.artifacts'))) { throw 'Unsafe harness test cleanup root.' }
Remove-Item -LiteralPath $cleanupRoot -Recurse -Force

Write-Host "Windows clean-install harness unit tests passed: $passed assertions." -ForegroundColor Green
