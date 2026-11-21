Set-StrictMode -Version Latest

function Get-ReefVisionResearchToolsArtifact([string]$Root, [string]$Name) {
    $files = @(Get-ChildItem -LiteralPath $Root -Filter $Name -File -Recurse)
    if ($files.Count -ne 1) { throw "Expected one installed research-tools artifact: $Name." }
    return $files[0]
}

function Assert-ReefVisionResearchToolsReplays($Runs, [string]$IdField, [string]$DigestField, [string]$Label) {
    $digest = '^[0-9a-f]{64}$'
    $runs = @($Runs)
    if ($runs.Count -ne 2 -or -not $runs[0].$IdField -or -not $runs[1].$IdField -or
        $runs[0].$IdField -ceq $runs[1].$IdField -or $runs[0].$DigestField -cnotmatch $digest -or
        $runs[0].$DigestField -cne $runs[1].$DigestField) {
        throw "Installed $Label requires two distinct runs with matching typed payload checksums."
    }
}

function Assert-ReefVisionResearchToolsRuntime($Receipt, [string]$Version, [string]$Revision) {
    if ($Receipt.surface -cne 'tauri-webview2' -or
        $Receipt.application_version -cne $Version -or $Receipt.schema_revision -cne $Revision) {
        throw 'The research tools receipt is from a different desktop runtime.'
    }
}

function Assert-ReefVisionInstalledResearchToolsResults {
    param($Taxonomy, $Audio, $Spectral, $Underwater, $Exports, [string]$Version, [string]$Revision)

    foreach ($receipt in @($Taxonomy, $Spectral, $Underwater)) {
        Assert-ReefVisionResearchToolsRuntime $receipt $Version $Revision
    }
    if ($Audio.surface -cne 'tauri-webview2' -or $Audio.version -cne $Version -or
        $Audio.schema -cne $Revision -or $Audio.generated_fixture -ne $true) {
        throw 'The audio receipt must come from the selected installed runtime and generated WAV.'
    }
    $digest = '^[0-9a-f]{64}$'
    $groups = @($Taxonomy.grouped_result)
    $originals = @($Taxonomy.originals)
    $roles = @($Taxonomy.two_fixture_role_revisions)
    if ($Taxonomy.generated_fixture -ne $true -or -not $Taxonomy.project_id -or
        -not $Taxonomy.proposal_id -or $Taxonomy.proposal_sha256 -cnotmatch $digest -or
        -not $Taxonomy.assessment_id -or $Taxonomy.result_sha256 -cnotmatch $digest -or
        $Taxonomy.graph_sha256 -cnotmatch $digest -or $roles.Count -ne 2 -or
        @($roles | Sort-Object -Unique).Count -ne 2 -or @($roles | Where-Object { -not $_ }).Count -ne 0 -or
        $groups.Count -ne 5 -or @($groups.unit_id | Sort-Object -Unique).Count -ne 5 -or
        @($groups | Where-Object { $_.eligible_visits -ne 2 -or $_.detections -ne 1 -or
            $_.nondetections -ne 1 -or $_.effort_seconds -ne 60 }).Count -ne 0 -or
        $originals.Count -ne 25 -or @($originals.id | Sort-Object -Unique).Count -ne 25 -or
        @($originals.sha256 | Sort-Object -Unique).Count -ne 25 -or
        @($originals | Where-Object { $_.sha256 -cnotmatch $digest -or $_.kind -cne 'image' }).Count -ne 0 -or
        $Taxonomy.exported_file_sha256 -cnotmatch $digest -or
        $Taxonomy.exported_file_sha256 -cne $Exports.taxonomy -or -not $Taxonomy.graph_id) {
        throw 'Taxonomy lost its local reviewer roles, repeated units, original bytes, or assessment export.'
    }
    Assert-ReefVisionResearchToolsReplays $Taxonomy.runs 'run_id' 'payload_sha256' 'detectability'
    if ($Taxonomy.runs[0].payload_sha256 -cne $Taxonomy.exported_file_sha256) {
        throw 'The detectability download must match its two workflow payloads.'
    }

    Assert-ReefVisionResearchToolsReplays $Audio.replays 'run_id' 'payload_sha256' 'reviewed audio'
    if (-not $Audio.recording_id -or -not $Audio.review_id -or -not $Audio.anchor_id -or
        $Audio.fixture -notlike '*.wav' -or $Audio.source_sha256 -cnotmatch $digest -or
        $Audio.report_sha256 -cnotmatch $digest -or $Audio.export_sha256 -cnotmatch $digest -or
        $Audio.export_sha256 -cne $Exports.audio -or $Audio.export_sha256 -cne $Audio.replays[0].payload_sha256) {
        throw 'The reviewed audio receipt lost its recording, clock, local review, or verified JSON download.'
    }

    $bands = @($Spectral.record.snapshot.acquisition.bands)
    Assert-ReefVisionResearchToolsReplays $Spectral.runs 'id' 'sha256' 'spectral index'
    if ($Spectral.generated_fixture -ne $true -or $Spectral.project_id -ne $Spectral.record.project_id -or
        -not $Spectral.record.id -or $Spectral.acquisition_sha256 -cnotmatch $digest -or
        $Spectral.record.snapshot.selection.acquisition_sha256 -cne $Spectral.acquisition_sha256 -or
        $Spectral.record.content_sha256 -cnotmatch $digest -or $Spectral.graph_sha256 -cnotmatch $digest -or
        $bands.Count -ne 2 -or @($bands.original_sha256 | Sort-Object -Unique).Count -ne 2 -or
        @($bands | Where-Object { $_.original_sha256 -cnotmatch $digest -or -not $_.image_id -or
            $null -eq $_.calibration }).Count -ne 0 -or
        $Spectral.record.snapshot.result.status -cne 'available' -or
        $Spectral.record.snapshot.result.valid_pixels -lt 1 -or
        $Spectral.export_sha256 -cnotmatch $digest -or $Spectral.export_sha256 -cne $Exports.spectral_json -or
        $Spectral.tiff_sha256 -cnotmatch $digest -or $Spectral.tiff_sha256 -cne $Exports.spectral_tiff) {
        throw 'Multispectral lost its calibrated bands, supported pixels, or exact JSON and TIFF exports.'
    }

    Assert-ReefVisionResearchToolsReplays $Underwater.saved_graph_runs 'id' 'payload_sha256' 'underwater adjustment'
    $correction = $Underwater.recipe
    if ($Underwater.fixture_source -cne 'installed_scratch_detector' -or -not $Underwater.source_training_run_id -or
        -not $Underwater.image_id -or -not $Underwater.job -or $Underwater.original_sha256 -cnotmatch $digest -or
        $Underwater.model_sha256 -cnotmatch $digest -or $correction.content_sha256 -cnotmatch $digest -or
        $correction.receipt.original_sha256 -cne $Underwater.original_sha256 -or
        $correction.receipt.image_id -cne $Underwater.image_id -or
        $Underwater.saved_graph_runs[0].graph_sha256 -cnotmatch $digest -or
        $Underwater.saved_graph_runs[0].graph_sha256 -cne $Underwater.saved_graph_runs[1].graph_sha256 -or
        $Underwater.raw_axes_reopened -ne $true -or $Underwater.polygon_and_raster_reused_rendition -ne $true -or
        $Underwater.original_bytes_match -ne $true -or @($Underwater.source_pixel_predictions).Count -lt 1) {
        throw 'Underwater lost its installed scratch checkpoint, original axes/bytes, or corrected inference and replay.'
    }
}

function Invoke-ReefVisionInstalledResearchToolsAcceptance {
    param(
        [string]$NodePath, [string]$RepositoryRoot, [string]$EvidenceRoot, [string]$Profile,
        [int]$BackendPort, [int]$DebugPort, [int]$DesktopProcessId, [string]$BrowserSid,
        [string]$BrowserArtifactsDirectory, [string]$BackendExecutable, [string]$Version, [string]$Revision
    )
    Assert-ReefVisionHostedStandardUserMode
    if (-not (Test-Path -LiteralPath (Join-Path $Profile '.reefvision-clean-install-acceptance') -PathType Leaf)) {
        throw 'Installed research tools require the marked disposable WebView2 profile.'
    }
    $backendPins = @{
        Port=$BackendPort; DesktopProcessId=$DesktopProcessId; BrowserSid=$BrowserSid
        BackendExecutable=$BackendExecutable; Profile=$Profile; Version=$Version; Revision=$Revision
    }
    $backend = Get-ReefVisionInstalledScheduleBackend @backendPins
    $prior = Get-ReefVisionResearchToolsArtifact (Join-Path $EvidenceRoot 'research-playwright') 'ordinary-detector-evidence.json'
    $specs = @('taxonomy-detectability-live.spec.ts','bioacoustics-live.spec.ts','multispectral-live.spec.ts',
        'underwater-adjustment-live.spec.ts')
    $driver = @{
        NodePath=$NodePath; RepositoryRoot=$RepositoryRoot; EvidenceRoot=$EvidenceRoot
        Api="http://127.0.0.1:$BackendPort/api/v1"; DebugPort=$DebugPort; DesktopProcessId=$DesktopProcessId
        ExpectedBrowserSid=$BrowserSid; BrowserArtifactsDirectory=$BrowserArtifactsDirectory
        Suite='research-tools'; Specs=$specs; AdditionalEnvironment=@{
            REEFVISION_GUIDED_TEST_WEB=''
            REEFVISION_RESEARCH_TEST_PROFILE=$Profile
            REEFVISION_RESEARCH_TEST_VERSION=$Version
            REEFVISION_RESEARCH_TEST_SCHEMA=$Revision
            REEFVISION_UNDERWATER_TEST_FIXTURE=''
            REEFVISION_RESEARCH_TOOLS_DETECTOR_RECEIPT=$prior.FullName
        }
    }
    $output = Invoke-ReefVisionInstalledPlaywrightSuite @driver
    $names = [ordered]@{
        taxonomy='taxonomy-detectability-proof.json'
        audio='bioacoustics-evidence.json'
        spectral='multispectral-evidence.json'
        underwater='underwater-adjustment-evidence.json'
    }
    $receipts = [ordered]@{}
    $hashes = [ordered]@{}
    foreach ($key in $names.Keys) {
        $file = Get-ReefVisionResearchToolsArtifact $output $names[$key]
        $receipts[$key] = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
        $hashes[$names[$key]] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $exports = [ordered]@{}
    $exportNames = [ordered]@{
        taxonomy='detectability-assessment.json'
        audio='reviewed-bioacoustic-report.json'
        spectral_json='spectral-index.json'
        spectral_tiff='spectral-index.tif'
    }
    foreach ($key in $exportNames.Keys) {
        $file = Get-ReefVisionResearchToolsArtifact $output $exportNames[$key]
        $exports[$key] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $hashes[$exportNames[$key]] = $exports[$key]
    }
    $arguments = @{
        Taxonomy=$receipts.taxonomy; Audio=$receipts.audio; Spectral=$receipts.spectral; Underwater=$receipts.underwater
        Exports=$exports; Version=$Version; Revision=$Revision
    }
    Assert-ReefVisionInstalledResearchToolsResults @arguments
    return [ordered]@{
        surface='tauri-webview2'; completed_journeys=$specs.Length; desktop_pid=$DesktopProcessId; debug_port=$DebugPort
        backend=$backend; generated_fixtures=$true; evidence_sha256=$hashes; journeys=$receipts
    }
}
