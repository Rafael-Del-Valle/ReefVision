[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$RepositoryRoot,
    [Parameter(Mandatory)][string]$Profile,
    [Parameter(Mandatory)][string]$ProfileMarker,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter(Mandatory)][string]$NodePath,
    [Parameter(Mandatory)][string]$PythonPath,
    [Parameter(Mandatory)][string]$BackendExecutable,
    [Parameter(Mandatory)][int]$BackendPort,
    [Parameter(Mandatory)][int]$DesktopProcessId,
    [Parameter(Mandatory)][int]$DebugPort,
    [Parameter(Mandatory)][string]$BrowserSid,
    [Parameter(Mandatory)][string]$BrowserArtifactsDirectory,
    [Parameter(Mandatory)][string]$Version,
    [Parameter(Mandatory)][string]$Revision,
    [Parameter(Mandatory)][ValidatePattern('^[a-f0-9]{40}$')][string]$SourceCommit,
    [Parameter(Mandatory)][ValidatePattern('^[a-f0-9]{64}$')][string]$InstallerSha256
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $RepositoryRoot 'scripts/lib/windows-standard-user-webview2.ps1')
. (Join-Path $RepositoryRoot 'scripts/lib/windows-spatial-webview2-acceptance.ps1')
. (Join-Path $RepositoryRoot 'scripts/lib/windows-scheduler-webview2-acceptance.ps1')
Assert-ReefVisionHostedStandardUserMode

$receipt = Join-Path $EvidenceRoot 'guided-pose-evidence.json'
$state = [ordered]@{status='FAIL'; source_commit=$SourceCommit; original_msi_sha256=$InstallerSha256}
try {
    $Profile = (Resolve-Path -LiteralPath $Profile).Path
    $BackendExecutable = (Resolve-Path -LiteralPath $BackendExecutable).Path
    $state.backend = Get-ReefVisionInstalledScheduleBackend -Port $BackendPort -DesktopProcessId $DesktopProcessId `
        -BrowserSid $BrowserSid -BackendExecutable $BackendExecutable -Profile $Profile -Version $Version -Revision $Revision
    $state.desktop_pid = $DesktopProcessId
    $state.cdp_port = $DebugPort
    $state.browser_sid = $BrowserSid
    $endpoint = Wait-ReefVisionWebView2DebugEndpoint -Port $DebugPort -DesktopProcessId $DesktopProcessId `
        -ExpectedBrowserSid $BrowserSid -AttachmentEvidencePath (Join-Path $EvidenceRoot 'guided-pose-webview2-attached.log') `
        -FailureEvidencePath (Join-Path $EvidenceRoot 'guided-pose-webview2-startup.log')

    $private = Join-Path (Split-Path -Parent $Profile) 'guided-fixture'
    $generated = Join-Path $private 'inputs'
    $browser = Join-Path $private 'outputs'
    $null = New-Item -ItemType Directory -Path $private,$browser
    $api = "http://127.0.0.1:$BackendPort/api/v1"
    & $PythonPath (Join-Path $PSScriptRoot 'prepare-fixture.py') --api $api --profile $Profile --marker $ProfileMarker `
        --version $Version --schema $Revision --source $SourceCommit --output $generated *> (Join-Path $EvidenceRoot 'guided-pose-seed.log')
    if ($LASTEXITCODE -ne 0) { throw "Generated guided pose fixture API setup failed (exit $LASTEXITCODE)." }

    $variables = @{
        NODE_PATH = (Join-Path $RepositoryRoot 'apps/web/node_modules')
        REEFVISION_GUIDED_TEST_API = $api
        REEFVISION_RESEARCH_TEST_PROFILE = $Profile
        REEFVISION_RESEARCH_TEST_VERSION = $Version
        REEFVISION_RESEARCH_TEST_SCHEMA = $Revision
        REEFVISION_SPATIAL_WEBVIEW2_ENDPOINT = $endpoint
        REEFVISION_SPATIAL_WEBVIEW2_ARTIFACTS_DIR = $BrowserArtifactsDirectory
        REEFVISION_POSE_EXPECTED_DEVICE = 'cpu'
    }
    $previous = @{}
    $fixture = Join-Path $generated 'fixture.json'
    $oracle = Join-Path $generated 'oracle.json'
    $baseline = Join-Path $browser 'pose-predecessor-proof.json'
    $replay = Join-Path $browser 'review-and-replay.json'
    try {
        foreach ($name in $variables.Keys) {
            $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
            [Environment]::SetEnvironmentVariable($name, $variables[$name], 'Process')
        }
        & $NodePath (Join-Path $PSScriptRoot 'browser-pose.cjs') $fixture $browser *> (Join-Path $EvidenceRoot 'guided-pose-save.log')
        if ($LASTEXITCODE -ne 0) { throw "Guided pose save or first review gate failed (exit $LASTEXITCODE)." }
        & $NodePath (Join-Path $PSScriptRoot 'review-pose.cjs') $baseline $fixture $browser $oracle *> (Join-Path $EvidenceRoot 'guided-pose-review.log')
        if ($LASTEXITCODE -ne 0) { throw "Guided pose review or replay failed (exit $LASTEXITCODE)." }
    } finally {
        foreach ($name in $variables.Keys) {
            [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
        }
    }
    $after = Get-ReefVisionInstalledScheduleBackend -Port $BackendPort -DesktopProcessId $DesktopProcessId `
        -BrowserSid $BrowserSid -BackendExecutable $BackendExecutable -Profile $Profile -Version $Version -Revision $Revision
    if ($after.pid -ne $state.backend.pid -or $after.sha256 -cne $state.backend.sha256) {
        throw 'The saved guided workflow changed its bound installed API process.'
    }
    $compact = Join-Path $EvidenceRoot 'guided-pose-workflow.json'
    & $PythonPath (Join-Path $PSScriptRoot 'verify-guided-pose.py') --fixture $fixture --oracle $oracle --browser $browser `
        --source $SourceCommit --surface tauri-webview2 --version $Version --schema $Revision --output $compact
    if ($LASTEXITCODE -ne 0) { throw "Independent guided pose receipt verification failed (exit $LASTEXITCODE)." }
    $state.workflow_receipt_sha256 = (Get-FileHash -LiteralPath $compact -Algorithm SHA256).Hash.ToLowerInvariant()
    $state.drivers = [ordered]@{}
    foreach ($driver in 'prepare-fixture.py','browser-pose.cjs','review-pose.cjs','verify-guided-pose.py','run-guided-pose.ps1') {
        $state.drivers[$driver] = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $driver) -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $state.status = 'PASS'
    $state.completed_workflow_runs = 2
    $state.completed_human_gates = 4
} catch {
    $state.error = $_.Exception.Message
    throw
} finally {
    $state | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $receipt -Encoding utf8
}
