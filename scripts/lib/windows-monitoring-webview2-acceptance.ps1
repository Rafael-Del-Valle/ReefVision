Set-StrictMode -Version Latest

function Assert-ReefVisionInstalledMonitoringResults {
    param($Acquisition, $Monitoring, [string]$Version, [string]$Revision)

    foreach ($receipt in @($Acquisition, $Monitoring)) {
        if ($receipt.surface -cne 'tauri-webview2' -or $receipt.version -cne $Version -or $receipt.schema -cne $Revision) {
            throw 'The acquisition or monitoring receipt is from a different desktop runtime.'
        }
    }

    $digest = '^[0-9a-f]{64}$'
    $recorded = @($Acquisition.recorded)
    if ($recorded.Count -ne 2 -or $Acquisition.disconnected_cursor -ne 1) {
        throw 'The recorded source must recover the same pending slot after disconnection.'
    }
    $original = $recorded[0].receipt
    $recovered = $recorded[1].receipt
    for ($i = 0; $i -lt 2; $i++) {
        $capture = $recorded[$i]
        if ($capture.content_sha256 -cnotmatch $digest -or $capture.receipt.source_kind -cne 'recorded' -or
            $capture.receipt.project_id -ne $Acquisition.project_id -or $capture.receipt.ordinal -ne $i -or
            $capture.receipt.source_id -ne $original.source_id -or $capture.receipt.media.sha256 -cnotmatch $digest -or
            $capture.receipt.media.field_batch_sha256 -cnotmatch $digest -or
            $capture.receipt.media.field_batch_id -ne $original.media.field_batch_id -or
            $capture.receipt.media.field_batch_sha256 -cne $original.media.field_batch_sha256) {
            throw 'Recorded source receipts must identify the same sealed project batch, with both original byte digests.'
        }
    }
    if (-not $original.source_id -or -not $original.media.field_batch_id -or
        $recorded[0].content_sha256 -ceq $recorded[1].content_sha256 -or $original.media.sha256 -ceq $recovered.media.sha256 -or
        [datetimeoffset]$original.time.captured_at_utc -ne [datetimeoffset]'2025-08-02T22:05:06Z' -or
        $null -ne $original.time.uncertainty_seconds -or $null -ne $recovered.time.captured_at_utc -or
        $null -ne $recovered.time.uncertainty_seconds -or $recovered.time.clock.state -cne 'unknown') {
        throw 'Recorded evidence must preserve the known UTC clock and the explicitly unknown reconnect clock.'
    }

    $artifact = $Acquisition.capture_artifact
    $simulated = $artifact.payload_json.receipt
    $acquisitionReplays = @($Acquisition.replay_digests)
    if ($artifact.data_type -cne 'acquisition_capture_receipt' -or $artifact.payload_sha256 -cnotmatch $digest -or
        $simulated.source_kind -cne 'simulated' -or $simulated.project_id -ne $Acquisition.project_id -or
        -not $Acquisition.simulated_source_id -or $simulated.source_id -ne $Acquisition.simulated_source_id -or
        -not $Acquisition.occurrence_id -or $simulated.dispatch.workflow_run_id -ne $artifact.workflow_run_id -or
        $simulated.dispatch.kind -cne 'schedule' -or $simulated.dispatch.occurrence_id -ne $Acquisition.occurrence_id -or
        $simulated.synthetic_reading.unit -cne 'synthetic arbitrary units' -or
        $acquisitionReplays.Count -ne 2 -or $acquisitionReplays[0] -cnotmatch $digest -or
        $acquisitionReplays[0] -cne $acquisitionReplays[1] -or $Acquisition.camera_consent_cancelled_without_capture -ne $true) {
        throw 'The simulated schedule, saved receipt replays or cancelled camera consent did not verify.'
    }

    $assessments = @($Monitoring.assessments)
    if ($Monitoring.generated_fixture -ne $true -or $assessments.Count -ne 3 -or
        @($assessments.project_id | Sort-Object -Unique).Count -ne 3) {
        throw 'Three separately scoped generated project assessments are required.'
    }
    $slots = @(4, 5, 4)
    $expectedSlots = @(5, 5, 4)
    for ($i = 0; $i -lt 3; $i++) {
        $assessment = $assessments[$i]
        if (-not $assessment.id -or $assessment.evidence_sha256 -cnotmatch $digest -or $assessment.result_sha256 -cnotmatch $digest -or
            $assessment.effort.observed_slots -ne $slots[$i] -or $assessment.effort.accepted_observations -ne $slots[$i] -or
            $assessment.effort.expected_slots -ne $expectedSlots[$i]) {
            throw 'A project-local assessment lost its original identity or generated effort counts.'
        }
    }
    $rows = @($Monitoring.summary.project_rows)
    if (-not $Monitoring.summary.id -or $Monitoring.summary.content_sha256 -cnotmatch $digest -or $rows.Count -ne 3 -or
        $rows[0].project_id -ne $assessments[0].project_id -or $rows[1].project_id -ne $assessments[1].project_id -or
        $rows[2].project_id -ne $assessments[2].project_id -or $rows[0].status -cne 'included' -or
        $rows[1].status -cne 'included' -or $rows[2].status -cne 'excluded' -or
        $rows[2].reasons -cnotcontains 'The UTC observation windows differ.') {
        throw 'The project summary must keep two compatible results separate and explain the incompatible UTC window.'
    }

    $findings = @($Monitoring.findings)
    $reviews = @($Monitoring.reviews)
    if ($findings.Count -ne 4 -or $reviews.Count -ne 4 -or @($findings.id | Sort-Object -Unique).Count -ne 4 -or
        (Compare-Object -ReferenceObject @('delay','drift','drop','upper_limit') -DifferenceObject @($findings.kind) -CaseSensitive)) {
        throw 'The assessment must expose all four planned findings and their review decisions.'
    }
    foreach ($finding in $findings) {
        $byFinding = @($reviews | Where-Object alert_id -ceq $finding.id)
        $decision = if ($finding.kind -ceq 'drop') { 'confirmed' } else { 'dismissed' }
        if ($finding.proposal_sha256 -cnotmatch $digest -or $byFinding.Count -ne 1 -or
            $byFinding[0].project_id -ne $assessments[0].project_id -or $byFinding[0].decision -cne $decision -or
            -not $byFinding[0].reviewer -or -not $byFinding[0].reason -or $byFinding[0].revision -ne 1) {
            throw 'Each monitoring finding must retain its attributed project-bound decision and reason.'
        }
    }
    foreach ($field in @('assessment_replays','summary_replays')) {
        $runs = @($Monitoring.$field)
        if ($runs.Count -ne 2 -or -not $runs[0].id -or -not $runs[1].id -or $runs[0].id -eq $runs[1].id -or
            $runs[0].payloadSha256 -cnotmatch $digest -or $runs[0].payloadSha256 -cne $runs[1].payloadSha256) {
            throw "The installed $field must contain two separate runs with matching output digests."
        }
    }
    if ($Monitoring.export_sha256 -cnotmatch $digest -or
        $Monitoring.export_sha256 -cne $Monitoring.summary_replays[0].payloadSha256) {
        throw 'The downloaded project summary must match the replayed payload.'
    }
}

function Invoke-ReefVisionInstalledMonitoringAcceptance {
    param(
        [string]$NodePath, [string]$RepositoryRoot, [string]$EvidenceRoot, [string]$Profile,
        [int]$BackendPort, [int]$DebugPort, [int]$DesktopProcessId, [string]$BrowserSid,
        [string]$BrowserArtifactsDirectory, [string]$BackendExecutable, [string]$Version, [string]$Revision
    )
    Assert-ReefVisionHostedStandardUserMode
    if (-not (Test-Path -LiteralPath (Join-Path $Profile '.reefvision-clean-install-acceptance') -PathType Leaf)) {
        throw 'The installed acquisition and monitoring journeys require the marked disposable desktop profile.'
    }
    $backend = Get-ReefVisionInstalledScheduleBackend -Port $BackendPort -DesktopProcessId $DesktopProcessId `
        -BrowserSid $BrowserSid -BackendExecutable $BackendExecutable -Profile $Profile -Version $Version -Revision $Revision
    $output = Invoke-ReefVisionInstalledPlaywrightSuite -NodePath $NodePath -RepositoryRoot $RepositoryRoot `
        -EvidenceRoot $EvidenceRoot -Api "http://127.0.0.1:$BackendPort/api/v1" -DebugPort $DebugPort `
        -DesktopProcessId $DesktopProcessId -ExpectedBrowserSid $BrowserSid -BrowserArtifactsDirectory $BrowserArtifactsDirectory `
        -Suite 'monitoring' -Specs @('acquisition-sources-live.spec.ts','monitoring-live.spec.ts') -AdditionalEnvironment @{
            REEFVISION_ACQUISITION_TEST_PROFILE=$Profile
            REEFVISION_ACQUISITION_TEST_VERSION=$Version
            REEFVISION_ACQUISITION_TEST_SCHEMA=$Revision
            REEFVISION_MONITORING_EXPECTED_DATA_DIR=$Profile
            REEFVISION_MONITORING_EXPECTED_SCHEMA=$Revision
            REEFVISION_MONITORING_BIO_FIXTURE=''
        }
    $files = @{}
    $hashes = [ordered]@{}
    foreach ($name in @('acquisition-source-evidence.json','monitoring-proof.json')) {
        $matches = @(Get-ChildItem -LiteralPath $output -Filter $name -File -Recurse)
        if ($matches.Count -ne 1) { throw "Expected exactly one installed $name receipt." }
        $files[$name] = Get-Content -LiteralPath $matches[0].FullName -Raw | ConvertFrom-Json
        $hashes[$name] = (Get-FileHash -LiteralPath $matches[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $acquisition = $files['acquisition-source-evidence.json']
    $monitoring = $files['monitoring-proof.json']
    Assert-ReefVisionInstalledMonitoringResults -Acquisition $acquisition -Monitoring $monitoring -Version $Version -Revision $Revision
    return [ordered]@{
        surface='tauri-webview2'; completed_journeys=2; desktop_pid=$DesktopProcessId; debug_port=$DebugPort
        backend=$backend; generated_fixture=$true; evidence_sha256=$hashes; acquisition=$acquisition; monitoring=$monitoring
    }
}
