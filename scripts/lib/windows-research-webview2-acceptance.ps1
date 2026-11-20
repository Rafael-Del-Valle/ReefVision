Set-StrictMode -Version Latest

function Get-ReefVisionResearchJourneyEvidence {
    param([Parameter(Mandatory = $true)][scriptblock]$RunJourney)

    try {
        $result = & $RunJourney
        return New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Installed WebView2 passed $($result.completed_journeys) research journeys. Study SHA-256 $($result.study.study_sha256), reviewer agreement SHA-256 $($result.reviewer.report.content_sha256), field reconciliation SHA-256 $($result.field.report_sha256), reviewed model configuration SHA-256 $($result.model.reviewed_runtime.selection.content_sha256), paired comparison SHA-256 $($result.comparison.report_sha256), and independently restored package proof SHA-256 $($result.package.proof_sha256)."
    } catch {
        return New-ReefVisionEvidenceResult -Status 'FAIL' -Detail $_.Exception.Message
    }
}

function Invoke-ReefVisionResearchJourneyAcceptance {
    [CmdletBinding(DefaultParameterSetName = 'Installed')]
    param(
        [Parameter(Mandatory = $true)][string]$NodePath,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$EvidenceRoot,
        [Parameter(Mandatory = $true)][string]$Api,
        [Parameter(Mandatory = $true, ParameterSetName = 'Installed')][int]$DebugPort,
        [Parameter(Mandatory = $true, ParameterSetName = 'Installed')][int]$DesktopProcessId,
        [Parameter(ParameterSetName = 'Installed')][string]$ExpectedBrowserSid,
        [Parameter(ParameterSetName = 'Installed')][string]$BrowserArtifactsDirectory,
        [Parameter(Mandatory = $true, ParameterSetName = 'Source')][string]$SourceWeb
    )

    if ($Api -notmatch '^http://127[.]0[.]0[.]1:[1-9][0-9]{0,4}/api/v1$') {
        throw 'Research acceptance requires an isolated loopback API.'
    }
    $runtime = Invoke-RestMethod -Uri "$Api/system/version" -NoProxy -TimeoutSec 5
    if ($runtime.safe_mode -or -not $runtime.data_dir -or
        -not (Test-Path -LiteralPath (Join-Path $runtime.data_dir '.reefvision-clean-install-acceptance') -PathType Leaf)) {
        throw 'Research acceptance requires a writable disposable profile marked by its launcher.'
    }
    $endpoint = $null
    $surface = 'source-browser'
    if ($PSCmdlet.ParameterSetName -eq 'Installed') {
        $endpoint = Wait-ReefVisionWebView2DebugEndpoint -Port $DebugPort -DesktopProcessId $DesktopProcessId `
            -FailureEvidencePath (Join-Path $EvidenceRoot 'research-webview2-startup.log') `
            -AttachmentEvidencePath (Join-Path $EvidenceRoot 'research-webview2-attached.log') -ExpectedBrowserSid $ExpectedBrowserSid
        $surface = 'tauri-webview2'
    } elseif ($SourceWeb -notmatch '^http://127[.]0[.]0[.]1:[1-9][0-9]{0,4}/?$') {
        throw 'Research source acceptance requires an isolated loopback frontend.'
    }

    $playwrightRoot = Join-Path $RepositoryRoot 'apps\web'
    $playwrightCli = Join-Path $playwrightRoot 'node_modules\@playwright\test\cli.js'
    $output = Join-Path $EvidenceRoot 'research-playwright'
    $log = Join-Path $EvidenceRoot 'research-playwright.log'
    $report = Join-Path $EvidenceRoot 'research-playwright.json'
    if (@($output, $log, $report | Where-Object { Test-Path -LiteralPath $_ }).Count -gt 0) {
        throw 'Research acceptance requires a new evidence location for each run.'
    }
    $journeys = [ordered]@{
        study = @('paired-growth-contrast-live.spec.ts', (Get-ReefVisionStudyDesignJourneyTitle), 'study-design-evidence.json')
        reviewer = @('reviewer-lab-live.spec.ts', 'assigns blinded reviews, adjudicates, and replays the sealed agreement', 'reviewer-lab-evidence.json')
        field = @('field-capture-live.spec.ts', 'captures local field originals and replays a transferred batch', 'field-capture-evidence.json')
        model = @('ordinary-detector-live.spec.ts', 'runs the ordinary local detector from grouped stills through reviewed results and exports', 'ordinary-detector-evidence.json')
        comparison = @('paired-model-comparison-live.spec.ts', 'compares two local detectors on held-out originals and replays the saved comparison', 'paired-model-comparison-evidence.json')
        package = @('reproducibility-package-live.spec.ts', 'exports and restores a reproducibility package with replayable study, review and model proof', 'reproducibility-package-evidence.json')
    }
    $specs = @($journeys.Values | ForEach-Object { $_[0] })
    $titles = '(?:' + (($journeys.Values | ForEach-Object { [regex]::Escape($_[1]) }) -join '|') + ')$'
    $variables = @{
        REEFVISION_GUIDED_TEST_API = $Api
        REEFVISION_GUIDED_TEST_WEB = $SourceWeb
        REEFVISION_SPATIAL_WEBVIEW2_ENDPOINT = $endpoint
        REEFVISION_SPATIAL_WEBVIEW2_ARTIFACTS_DIR = $BrowserArtifactsDirectory
        REEFVISION_ORDINARY_DETECTOR_ACCEPTANCE = '1'
        REEFVISION_REVIEWED_RUNTIME_DEVICE = 'cpu'
        PLAYWRIGHT_JSON_OUTPUT_FILE = $report
    }
    $previous = @{}
    foreach ($name in $variables.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $variables[$name], 'Process')
    }
    Push-Location -LiteralPath $playwrightRoot
    try {
        # Keep reviewer access keys out of traces, including on fixture failures.
        & $NodePath $playwrightCli test @specs --grep $titles --trace=off --workers=1 --retries=0 --reporter=list,json --output=$output *> $log
        if ($LASTEXITCODE -ne 0) {
            $tail = Get-Content -LiteralPath $log -Tail 25 | Out-String
            throw "Research workflow acceptance failed with exit code $LASTEXITCODE. $tail"
        }
    } finally {
        Pop-Location
        foreach ($name in $variables.Keys) {
            [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
        }
    }

    $stats = (Get-Content -LiteralPath $report -Raw | ConvertFrom-Json).stats
    if ($stats.expected -ne $journeys.Count -or $stats.skipped -ne 0 -or $stats.unexpected -ne 0 -or $stats.flaky -ne 0) {
        throw 'Every requested research journey must execute successfully.'
    }
    $result = [ordered]@{ surface = $surface; completed_journeys = $stats.expected }
    foreach ($name in $journeys.Keys) {
        $files = @(Get-ChildItem -LiteralPath $output -Recurse -File -Filter $journeys[$name][2])
        if ($files.Count -ne 1) { throw "Expected one research acceptance receipt for $name." }
        $receipt = Get-Content -LiteralPath $files[0].FullName -Raw | ConvertFrom-Json
        if ($receipt.surface -ne $surface) { throw "The $name journey reported a different surface." }
        $result[$name] = $receipt
    }
    $hash = '^[a-f0-9]{64}$'
    if ($result.study.prospective_sha256 -notmatch $hash -or $result.study.study_sha256 -notmatch $hash -or
        @($result.study.runs).Count -ne 2 -or $result.study.runs[0].id -eq $result.study.runs[1].id -or
        $result.study.runs[0].payload_sha256 -notmatch $hash -or $result.study.runs[0].payload_sha256 -ne $result.study.runs[1].payload_sha256) {
        throw 'Study acceptance lacks sealed prospective and retrospective evidence and two matching replays.'
    }
    if ($result.reviewer.report.authority -ne 'local_attribution' -or $result.reviewer.report.content_sha256 -notmatch $hash -or
        @($result.reviewer.replays).Count -ne 2 -or $result.reviewer.replays[0].id -eq $result.reviewer.replays[1].id -or
        $result.reviewer.replays[0].hash -notmatch $hash -or $result.reviewer.replays[0].hash -ne $result.reviewer.replays[1].hash) {
        throw 'Reviewer acceptance lacks local attribution and two matching agreement replays.'
    }
    if ($result.field.generated_fixture -ne $true -or $result.field.source_sha256 -notmatch $hash -or
        $result.field.video_sha256 -notmatch $hash -or $result.field.archive_sha256 -notmatch $hash -or
        $result.field.report_sha256 -notmatch $hash -or @($result.field.replay_ids).Count -ne 2 -or
        $result.field.replay_ids[0] -eq $result.field.replay_ids[1] -or $result.field.persisted_conflict_decision -ne 'retain_both') {
        throw 'Field acceptance lacks exact original files, transferred reconciliation and a persistent conflict decision.'
    }
    $model = $result.model.reviewed_runtime
    if ($result.model.device -ne 'cpu' -or $result.model.initializer -ne 'scratch' -or
        $result.model.checkpoint_sha256 -notmatch $hash -or $model.selection.content_sha256 -notmatch $hash -or
        $model.selection.snapshot.settings.device -ne 'cpu' -or @($model.runs).Count -ne 2 -or
        $model.runs[0].id -eq $model.runs[1].id -or $model.runs[0].digest -notmatch $hash -or
        $model.runs[0].digest -ne $model.runs[1].digest -or $model.runs[0].matched_proposals -lt 1 -or
        $model.runs[0].matched_proposals -ne $model.runs[1].matched_proposals) {
        throw 'Model Hub acceptance lacks a confirmed local CPU runtime and two matching inference replays.'
    }
    $comparison = $result.comparison
    if (($surface -eq 'tauri-webview2' -and $comparison.fixture_source -ne 'local_cpu_training') -or
        @($comparison.training_runs).Count -ne 2 -or $comparison.training_runs[0] -eq $comparison.training_runs[1] -or
        @($comparison.checkpoint_sha256).Count -ne 2 -or $comparison.checkpoint_sha256[0] -notmatch $hash -or
        $comparison.checkpoint_sha256[1] -notmatch $hash -or $comparison.checkpoint_sha256[0] -eq $comparison.checkpoint_sha256[1] -or
        @($comparison.groups).Count -ne 2 -or @($comparison.original_images).Count -ne 3 -or
        $comparison.report_sha256 -notmatch $hash -or $comparison.reference_sha256 -notmatch $hash -or
        $comparison.json_sha256 -notmatch $hash -or $comparison.csv_sha256 -notmatch $hash -or
        @($comparison.replays).Count -ne 2 -or $comparison.replays[0].id -eq $comparison.replays[1].id -or
        $comparison.replays[0].payload_sha256 -notmatch $hash -or $comparison.replays[0].payload_sha256 -ne $comparison.replays[1].payload_sha256) {
        throw 'Comparison acceptance lacks two distinct CPU checkpoints, held-out originals, verified exports or graph replay.'
    }
    $package = $result.package
    if (($surface -eq 'tauri-webview2' -and $package.fixture_source -ne 'local_cpu_training') -or
        $package.archive_sha256 -notmatch $hash -or $package.manifest_sha256 -notmatch $hash -or
        $package.proof_sha256 -notmatch $hash -or $package.original_sha256 -notmatch $hash -or
        $package.original_archive_member_count -ne 1 -or $package.restored_field_manifest_sha256 -notmatch $hash -or
        $package.restored_field_original_sha256 -ne $package.original_sha256 -or
        @($package.omitted_checkpoint_sha256).Count -ne 2 -or $package.reviewer_credential_restored -ne $false -or
        -not $package.restored_package_id -or $package.restored_package_id -eq $package.package_id -or
        -not $package.restored_project_id -or $package.restored_project_id -eq $package.project_id -or
        @($package.runs).Count -ne 2 -or $package.runs[0].id -eq $package.runs[1].id -or
        $package.runs[0].sha256 -notmatch $hash -or $package.runs[0].sha256 -ne $package.runs[1].sha256 -or
        $package.restored_proof_replay.sha256 -ne $package.runs[0].sha256) {
        throw 'Package acceptance lacks a verified archive, distinct restored project, omitted checkpoint proof, or matching portable replays.'
    }
    return [pscustomobject]$result
}
