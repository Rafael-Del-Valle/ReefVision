param(
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [Parameter(Mandatory = $true)][string]$AcceptanceRoot,
    [string]$ExpectedVersion = '',
    [string]$ExpectedSchemaRevision = '',
    [string]$PreviousInstallerPath = '',
    [string]$CameraFixturePath = '',
    [string]$LineageManifestPath = '',
    [string]$LineageProfile = '',
    [string]$LineageVerificationPath = '',
    [string]$ExpectedInitialSchemaRevision = '',
    [string]$SpatialWorkflowNodePath = '',
    [switch]$FirstUseAcceptance,
    [switch]$ResearchWorkflowAcceptance,
    [switch]$WorkspaceWorkflowAcceptance,
    [switch]$HostedStandardUserWebView2,
    [switch]$VerifyPreviousInstallerRejectsUpgradedProfile,
    [switch]$PreviousInstallerSupportsIsolatedAcceptance,
    [switch]$DisposableTest,
    [switch]$PlanOnly,
    [switch]$KeepArtifacts,
    [switch]$SkipUpgrade,
    [switch]$SkipUninstall,
    [switch]$LiveSam2Acceptance
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'lib\windows-clean-acceptance.ps1')
. (Join-Path $PSScriptRoot 'lib\windows-spatial-webview2-acceptance.ps1')
. (Join-Path $PSScriptRoot 'lib\windows-research-webview2-acceptance.ps1')
. (Join-Path $PSScriptRoot 'lib\windows-standard-user-webview2.ps1')

if (-not $DisposableTest -and -not $PlanOnly) {
    throw 'Refusing destructive MSI acceptance. Supply -DisposableTest on a disposable Windows VM/machine, or use -PlanOnly.'
}
if ($DisposableTest -and $PlanOnly) { throw '-DisposableTest and -PlanOnly are mutually exclusive.' }
if ($ResearchWorkflowAcceptance -and -not $SpatialWorkflowNodePath) {
    throw 'Installed research journeys require -SpatialWorkflowNodePath for the packaged WebView2 driver.'
}
if ($FirstUseAcceptance -and (-not $SpatialWorkflowNodePath -or -not $SkipUpgrade)) {
    throw 'Installed first use requires the packaged WebView2 driver and a fresh candidate install.'
}
if ($WorkspaceWorkflowAcceptance -and (-not $SpatialWorkflowNodePath -or -not $SkipUpgrade)) {
    throw 'Installed workspace journeys require the packaged WebView2 driver and a fresh candidate install.'
}
if ($HostedStandardUserWebView2) {
    if (-not $DisposableTest -or -not $SpatialWorkflowNodePath) {
        throw 'A hosted standard WebView2 user requires disposable installed spatial acceptance.'
    }
    Assert-ReefVisionHostedStandardUserMode
}

$InstallerPath = (Resolve-Path -LiteralPath $InstallerPath).Path
if ([System.IO.Path]::GetExtension($InstallerPath) -ine '.msi') { throw 'InstallerPath must identify an MSI.' }
if ($PreviousInstallerPath) {
    $PreviousInstallerPath = (Resolve-Path -LiteralPath $PreviousInstallerPath).Path
    if ([System.IO.Path]::GetExtension($PreviousInstallerPath) -ine '.msi') { throw 'PreviousInstallerPath must identify an MSI.' }
}
$lineageArguments = @(@($LineageManifestPath, $LineageProfile, $LineageVerificationPath) | Where-Object { $_ })
if ($lineageArguments.Count -notin @(0, 3)) {
    throw 'Lineage acceptance requires -LineageManifestPath, -LineageProfile, and -LineageVerificationPath together.'
}
if ($VerifyPreviousInstallerRejectsUpgradedProfile -and (-not $PreviousInstallerPath -or $SkipUpgrade -or $SkipUninstall)) {
    throw '-VerifyPreviousInstallerRejectsUpgradedProfile requires an earlier MSI plus enabled upgrade and uninstall steps.'
}
$LineageFixture = $null
if ($lineageArguments.Count -eq 3) {
    $LineageManifestPath = (Resolve-Path -LiteralPath $LineageManifestPath).Path
    $LineageVerificationPath = (Resolve-Path -LiteralPath $LineageVerificationPath).Path
    $LineageFixture = Read-ReefVisionLineageFixture `
        -ManifestPath $LineageManifestPath `
        -ProfileName $LineageProfile `
        -VerificationPath $LineageVerificationPath
    if ($ExpectedInitialSchemaRevision -and $LineageFixture.revision -ne $ExpectedInitialSchemaRevision) {
        throw "Lineage revision $($LineageFixture.revision) does not match $ExpectedInitialSchemaRevision."
    }
}
if ($CameraFixturePath) {
    $CameraFixturePath = (Resolve-Path -LiteralPath $CameraFixturePath).Path
    if ([System.IO.Path]::GetExtension($CameraFixturePath) -notin @('.jpg', '.jpeg', '.jpe', '.jfif', '.jfi', '.jif')) {
        throw 'CameraFixturePath must identify a JPEG camera image (.jpg/.jpeg or a recognized JPEG alias).'
    }
    if (-not (Test-Path -LiteralPath $CameraFixturePath -PathType Leaf)) {
        throw 'CameraFixturePath must identify an existing file.'
    }
}
if ($SpatialWorkflowNodePath) {
    if ($PreviousInstallerPath) { throw 'Packaged spatial WebView2 acceptance requires a clean candidate installation.' }
    $SpatialWorkflowNodePath = (Resolve-Path -LiteralPath $SpatialWorkflowNodePath).Path
    if ((Split-Path -Leaf $SpatialWorkflowNodePath) -ine 'node.exe' -or
        -not (Test-Path -LiteralPath $SpatialWorkflowNodePath -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $RepositoryRoot 'apps\web\node_modules\@playwright\test\cli.js') -PathType Leaf)) {
        throw 'Spatial WebView2 acceptance requires the Node executable and repository Playwright dependencies.'
    }
}
if ($PreviousInstallerPath -and -not $PreviousInstallerSupportsIsolatedAcceptance) {
    throw 'A previous MSI may be exercised only when -PreviousInstallerSupportsIsolatedAcceptance confirms that it honors the marker-gated acceptance data root. This prevents an older desktop from touching normal ReefVision user data.'
}
$DefaultDataRoot = Join-Path $env:APPDATA 'org.reefvision.desktop'
$AcceptanceRoot = Assert-ReefVisionSafeAcceptanceRoot -Path $AcceptanceRoot -RepositoryRoot $RepositoryRoot -DefaultDataRoot $DefaultDataRoot
$Token = [guid]::NewGuid().ToString('N').Substring(0, 12)
$RunRoot = Join-Path $AcceptanceRoot "reefvision-clean-$Token"
$InstallRoot = Join-Path $RunRoot 'install'
$DataRoot = Join-Path $RunRoot 'data'
$RestoreDataRoot = Join-Path $RunRoot 'restore-data'
$SpatialDataRoot = Join-Path $RunRoot 'spatial-data'
$EvidenceRoot = Join-Path $RepositoryRoot ".artifacts\windows-clean-acceptance-$Token"
$ReportPath = Join-Path $EvidenceRoot 'report.json'
$InstallerHash = (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash
function Get-AcceptanceMsiProperty([string]$Path, [string]$Name) {
    $installer = New-Object -ComObject WindowsInstaller.Installer
    $database = $installer.OpenDatabase($Path, 0)
    $query = 'SELECT `Value` FROM `Property` WHERE `Property`=''{0}''' -f $Name
    $view = $database.OpenView($query)
    try {
        [void]$view.Execute()
        $record = $view.Fetch()
        if ($null -eq $record) { throw "MSI has no $Name." }
        $value = [string]$record.StringData(1)
        if ($Name -eq 'ProductVersion') { return ConvertTo-ReefVisionVersionString $value }
        return $value
    } finally {
        [void]$view.Close()
    }
}
$ProductVersion = Get-AcceptanceMsiProperty -Path $InstallerPath -Name 'ProductVersion'
if ($ExpectedVersion -and $ProductVersion -ne $ExpectedVersion) {
    throw "MSI ProductVersion $ProductVersion does not match $ExpectedVersion."
}
if ($PreviousInstallerPath -and -not $SkipUpgrade) {
    $previousProductVersion = Get-AcceptanceMsiProperty -Path $PreviousInstallerPath -Name 'ProductVersion'
    if ([version]$previousProductVersion -ge [version]$ProductVersion) { throw 'Upgrade requires an earlier MSI version.' }
    $upgradeCode = Get-AcceptanceMsiProperty -Path $InstallerPath -Name 'UpgradeCode'
    $previousUpgradeCode = Get-AcceptanceMsiProperty -Path $PreviousInstallerPath -Name 'UpgradeCode'
    if ($upgradeCode -ne $previousUpgradeCode) { throw 'Earlier and candidate MSI UpgradeCode values differ.' }
}

$report = [ordered]@{
    schema_version = 'reefvision-windows-clean-acceptance-1'
    started_at_utc = [DateTime]::UtcNow.ToString('o')
    completed_at_utc = $null
    reefvision_version = $ProductVersion
    installer_path = $InstallerPath
    installer_sha256 = $InstallerHash
    previous_installer_path = if ($PreviousInstallerPath) { $PreviousInstallerPath } else { $null }
    windows_version = [Environment]::OSVersion.VersionString
    architecture = $env:PROCESSOR_ARCHITECTURE
    acceptance_root = $AcceptanceRoot
    isolated_data_root = $DataRoot
    plan_only = [bool]$PlanOnly
    install = New-ReefVisionEvidenceResult
    shortcuts = New-ReefVisionEvidenceResult
    first_launch = New-ReefVisionEvidenceResult
    frontend_backend_connectivity = New-ReefVisionEvidenceResult
    webview2 = New-ReefVisionEvidenceResult
    first_use_workflow = if ($FirstUseAcceptance) { New-ReefVisionEvidenceResult } else { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'Installed first-use acceptance not requested' }
    workspace_workflow = if ($WorkspaceWorkflowAcceptance) { New-ReefVisionEvidenceResult } else { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'Installed workspace acceptance not requested' }
    spatial_workflow = if ($SpatialWorkflowNodePath) { New-ReefVisionEvidenceResult } else { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'Packaged spatial WebView2 acceptance not requested' }
    research_workflow = if ($ResearchWorkflowAcceptance) { New-ReefVisionEvidenceResult } else { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'Packaged research WebView2 acceptance not requested' }
    schema_migration = New-ReefVisionEvidenceResult
    model_policy = New-ReefVisionEvidenceResult
    provider_manifests = New-ReefVisionEvidenceResult
    sam2_live = if ($LiveSam2Acceptance) { New-ReefVisionEvidenceResult } else { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'Real SAM 2.1 packaged runtime acceptance not requested' }
    external_annotation_imports = New-ReefVisionEvidenceResult
    camera_jpeg = if ($CameraFixturePath) { New-ReefVisionEvidenceResult } else { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'Real camera JPEG fixture not supplied' }
    confidence_review = if ($LiveSam2Acceptance) { New-ReefVisionEvidenceResult } else { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'Real pending prediction review not requested' }
    project_persistence = New-ReefVisionEvidenceResult
    restart = New-ReefVisionEvidenceResult
    project_exchange = New-ReefVisionEvidenceResult
    lineage_preflight = if ($LineageFixture) { New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Verified $LineageProfile at revision $($LineageFixture.revision); manifest and source hashes matched; verification SHA-256 $($LineageFixture.verification_sha256)." } else { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'Lineage fixture not supplied' }
    lineage_initial_evidence = if ($LineageFixture) { New-ReefVisionEvidenceResult } else { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'Lineage fixture not supplied' }
    lineage_final_evidence = if ($LineageFixture) { New-ReefVisionEvidenceResult } else { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'Lineage fixture not supplied' }
    lineage_exchange_roundtrip = if ($LineageFixture) { New-ReefVisionEvidenceResult } else { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'Lineage fixture not supplied' }
    lineage_restore = if ($LineageFixture) { New-ReefVisionEvidenceResult } else { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'Lineage fixture not supplied' }
    historical_schema_rejection = if ($VerifyPreviousInstallerRejectsUpgradedProfile) { New-ReefVisionEvidenceResult } elseif ($LineageFixture -and -not $PreviousInstallerPath) { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'No historical installer supplied for this lineage profile' } else { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'Historical schema rejection not requested' }
    upgrade = if ($SkipUpgrade) { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'SkipUpgrade requested' } elseif (-not $PreviousInstallerPath) { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'previous installer not supplied' } else { New-ReefVisionEvidenceResult }
    uninstall = if ($SkipUninstall) { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'SkipUninstall requested' } else { New-ReefVisionEvidenceResult }
    data_retention = New-ReefVisionEvidenceResult
    failure_reason = $null
}

function Save-Report { Write-ReefVisionEvidenceReport -Report $report -Path $ReportPath }

function Assert-AcceptancePackagedBackend([string]$Api, [string]$ExpectedAppVersion, [string]$ExpectedRevision) {
    $versionPayload = Invoke-RestMethod "$Api/system/version"
    $appVersion = ConvertTo-ReefVisionVersionString ([string]$versionPayload.application_version)
    if ($appVersion -ne $ExpectedAppVersion) {
        throw "Packaged API version $($versionPayload.application_version) does not match $ExpectedAppVersion."
    }
    $migration = Invoke-RestMethod "$Api/system/migrations/status"
    if (-not $migration.database_exists -or $migration.schema_status -ne 'up_to_date' -or
        ($ExpectedRevision -and $migration.current_schema_revision -ne $ExpectedRevision)) {
        throw "Unexpected packaged database migration status: $($migration | ConvertTo-Json -Compress)"
    }
    return $migration
}

function Wait-AcceptanceWebView2([int]$DesktopProcessId) {
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        $webview = Get-CimInstance -ClassName Win32_Process -Filter "Name = 'msedgewebview2.exe' AND ParentProcessId = $DesktopProcessId" |
            Select-Object -First 1
        if ($webview) { return $webview.ProcessId }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'No WebView2 browser process was observed under the installed desktop.'
}

function Run-Msi([string]$Action, [string]$PackageOrProduct, [string]$LogName, [string]$TargetRoot = '') {
    $log = Join-Path $EvidenceRoot $LogName
    $arguments = New-ReefVisionMsiArguments -Action $Action -PackageOrProduct $PackageOrProduct -InstallRoot $TargetRoot -LogPath $log
    $process = Start-Process -FilePath 'msiexec.exe' -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -notin @(0, 3010)) { throw "msiexec $Action failed with exit code $($process.ExitCode). See $log" }
    return $process.ExitCode
}
function Wait-BackendPort(
    [string]$Path,
    [System.Diagnostics.Process]$DesktopProcess,
    [string]$BackendLogPath,
    [int]$Seconds = 180
) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-Path -LiteralPath $Path) {
            $value = (Get-Content -LiteralPath $Path -Raw).Trim()
            if ($value -match '^\d+$') { return [int]$value }
        }
        $DesktopProcess.Refresh()
        if ($DesktopProcess.HasExited) {
            $exitCode = try { $DesktopProcess.ExitCode } catch { 'unavailable' }
            $logTail = if (Test-Path -LiteralPath $BackendLogPath) {
                (Get-Content -LiteralPath $BackendLogPath -Tail 20 | Out-String).TrimEnd()
            } else {
                '(backend log unavailable)'
            }
            throw "ReefVision.exe exited before the backend published its port (exit code: $exitCode). Backend log tail:`n$logTail"
        }
        Start-Sleep -Milliseconds 250
    }
    throw "Backend did not publish its port within $Seconds seconds: $Path"
}
function Start-AcceptanceDesktop([string]$ProfileDataRoot = $DataRoot, [int]$WebViewDebugPort = 0) {
    $BackendPortPath = Join-Path $ProfileDataRoot 'runtime\backend-port.txt'
    Remove-Item -LiteralPath $BackendPortPath -Force -ErrorAction SilentlyContinue
    $isolatedOverrides = @{
        REEFVISION_WINDOWS_ACCEPTANCE = '1'
        REEFVISION_ACCEPTANCE_DATA_DIR = $ProfileDataRoot
        # Like the installed app, keep the browser's locked cache outside managed data.
        WEBVIEW2_USER_DATA_FOLDER = (Join-Path $RunRoot ((Split-Path -Leaf $ProfileDataRoot) + '-webview2'))
    }
    if ($WebViewDebugPort) {
        $isolatedOverrides['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = "--remote-debugging-address=127.0.0.1 --remote-debugging-port=$WebViewDebugPort"
        $isolatedOverrides['YOLO_OFFLINE'] = 'true'
    }
    if ($LiveSam2Acceptance) {
        # The default clean-install acceptance deliberately forbids network
        # model downloads. This opt-in, marker-gated test instead exercises
        # a real checkpoint download using the same isolated data/cache roots.
        $isolatedOverrides['HF_HUB_OFFLINE'] = '0'
        $isolatedOverrides['TRANSFORMERS_OFFLINE'] = '0'
        $isolatedOverrides['HF_HUB_DISABLE_TELEMETRY'] = '1'
        # Shared CI runners have only a few CPU cores. Avoid nested OpenMP,
        # BLAS and PyTorch oversubscription during real 1024px SAM2 inference.
        $isolatedOverrides['OMP_NUM_THREADS'] = '2'
        $isolatedOverrides['MKL_NUM_THREADS'] = '2'
        # Diagnose the frozen SciPy BLAS extension import without parallel
        # OpenBLAS initialization on resource-constrained Windows CI VMs.
        # This applies only to the disposable live-SAM acceptance process.
        $isolatedOverrides['OPENBLAS_NUM_THREADS'] = '1'
        $isolatedOverrides['TOKENIZERS_PARALLELISM'] = 'false'
    }
    return Invoke-ReefVisionIsolatedEnvironment -DataRoot $ProfileDataRoot -AdditionalEnvironment $isolatedOverrides -Action {
        Start-Process -FilePath (Join-Path $InstallRoot 'ReefVision.exe') -WorkingDirectory $InstallRoot -PassThru -WindowStyle Hidden
    }
}
function Stop-AcceptanceDesktop($Process) {
    if ($Process.HasExited) { return }
    $signature = '[DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);'
    if (-not ('ReefVisionAcceptanceNative' -as [type])) { Add-Type -MemberDefinition $signature -Name ReefVisionAcceptanceNative -Namespace ReefVision }
    if ($Process.MainWindowHandle -ne 0) { [ReefVision.ReefVisionAcceptanceNative]::PostMessage($Process.MainWindowHandle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null }
    $Process.WaitForExit(15000) | Out-Null
    if (-not $Process.HasExited) { throw 'ReefVision did not close cleanly within 15 seconds.' }
}

function Assert-HistoricalDesktopRejectsProfile(
    [string]$ProfileDataRoot,
    [string]$RejectedRevision,
    [int]$Seconds = 45
) {
    $portPath = Join-Path $ProfileDataRoot 'runtime\backend-port.txt'
    $backendLogPath = Join-Path $ProfileDataRoot 'logs\backend.log'
    $desktopProcess = Start-AcceptanceDesktop -ProfileDataRoot $ProfileDataRoot
    $explicitRejection = $false
    $revisionPattern = [regex]::Escape($RejectedRevision)
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    try {
        while ([DateTime]::UtcNow -lt $deadline) {
            if (Test-Path -LiteralPath $portPath) {
                $value = (Get-Content -LiteralPath $portPath -Raw).Trim()
                if ($value -match '^\d+$') {
                    throw "Historical desktop published backend port $value for a newer database."
                }
            }
            if (Test-Path -LiteralPath $backendLogPath) {
                $backendLog = Get-Content -LiteralPath $backendLogPath -Raw
                if ($backendLog -match "(?i)(can't locate revision|no such revision|not a valid upgrade target|database revision .* newer)[^\r\n]*$revisionPattern") {
                    $explicitRejection = $true
                    return "backend explicitly rejected migration revision $RejectedRevision"
                }
            }
            $desktopProcess.Refresh()
            if ($desktopProcess.HasExited) {
                throw 'Historical desktop exited without publishing a port or an explicit migration-revision rejection.'
            }
            Start-Sleep -Milliseconds 250
        }
        throw "Historical desktop published no backend port, but no explicit migration-revision rejection appeared within $Seconds seconds."
    } finally {
        $desktopProcess.Refresh()
        if (-not $desktopProcess.HasExited) {
            if ($explicitRejection) {
                # The failed startup has no usable application window. End only the
                # disposable process started for this negative test before restoring.
                $desktopProcess.Kill()
                if (-not $desktopProcess.WaitForExit(15000)) {
                    throw 'Rejected historical desktop remained running after cleanup.'
                }
            } else {
                try { Stop-AcceptanceDesktop $desktopProcess }
                catch { Write-Warning "Could not close failed historical probe: $($_.Exception.Message)" }
            }
        }
    }
}
function Import-AcceptanceImage(
    [string]$Url,
    [byte[]]$ImageBytes = $null,
    [string]$Filename = 'acceptance.png',
    [string]$RelativePath = 'synthetic/acceptance.png',
    [string]$ContentType = 'image/png'
) {
    Add-Type -AssemblyName System.Net.Http
    $png = if ($null -ne $ImageBytes) { $ImageBytes } else { [Convert]::FromBase64String('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=') }
    $client = New-Object System.Net.Http.HttpClient
    $form = New-Object System.Net.Http.MultipartFormDataContent
    try {
        $file = New-Object System.Net.Http.ByteArrayContent -ArgumentList (,$png)
        $file.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse($ContentType)
        $form.Add($file, 'files', $Filename)
        $form.Add((New-Object System.Net.Http.StringContent($RelativePath)), 'relative_paths')
        $response = $client.PostAsync($Url, $form).GetAwaiter().GetResult()
        $payload = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) { throw "Image import failed with HTTP $([int]$response.StatusCode): $payload" }
        return $payload | ConvertFrom-Json
    } finally { $form.Dispose(); $client.Dispose() }
}

function Import-AcceptanceAnnotations([string]$Url, [object[]]$Uploads) {
    Add-Type -AssemblyName System.Net.Http
    $http = [System.Net.Http.HttpClient]::new()
    $form = [System.Net.Http.MultipartFormDataContent]::new()
    try {
        foreach ($upload in $Uploads) {
            $bytes = [System.Text.Encoding]::UTF8.GetBytes([string]$upload.Content)
            $part = [System.Net.Http.ByteArrayContent]::new([byte[]]$bytes)
            $part.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse([string]$upload.Mime)
            $form.Add($part, 'files', [string]$upload.Name)
        }
        $response = $http.PostAsync($Url, $form).GetAwaiter().GetResult()
        $payload = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            throw "Annotation import failed with HTTP $([int]$response.StatusCode): $payload"
        }
        return $payload | ConvertFrom-Json
    } finally {
        $form.Dispose()
        $http.Dispose()
    }
}

function Get-AcceptanceContentSha256([string]$Url) {
    Add-Type -AssemblyName System.Net.Http
    $http = [System.Net.Http.HttpClient]::new()
    try {
        $bytes = $http.GetByteArrayAsync($Url).GetAwaiter().GetResult()
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try { return ([BitConverter]::ToString($sha.ComputeHash([byte[]]$bytes))).Replace('-', '').ToLowerInvariant() }
        finally { $sha.Dispose() }
    } finally { $http.Dispose() }
}

function Get-NormalizedLineageReviewEvidence($Evidence) {
    return [ordered]@{
        calibration_operator_id = $Evidence.calibration_operator_id
        independent_reviewer_id = $Evidence.independent_reviewer_id
        independent_review_decision = $Evidence.independent_review_decision
        independent_review_note = $Evidence.independent_review_note
        reviewed_at_utc = $Evidence.reviewed_at_utc
        reviewed_geometry_sha256 = $Evidence.reviewed_geometry_sha256
        reviewed_source_payload_sha256 = $Evidence.reviewed_source_payload_sha256
        reviewed_meters_per_unit = $Evidence.reviewed_meters_per_unit
        reviewed_calibration_method = $Evidence.reviewed_calibration_method
        reviewed_calibration_evidence = $Evidence.reviewed_calibration_evidence
    }
}

function Assert-AcceptanceLineageEvidence(
    [string]$Api,
    $Fixture,
    [string]$ProjectId,
    [switch]$AllowRemappedIds,
    $Baseline = $null
) {
    $project = Invoke-RestMethod "$Api/projects/$ProjectId"
    if (-not $AllowRemappedIds -and [string]$project.id -cne [string]$Fixture.project_id) {
        throw 'Lineage project ID changed while opening the historical profile.'
    }
    $scientific = @()
    $assets = @()
    if (@($Fixture.records | Where-Object kind -eq 'scientific_record').Count -gt 0) {
        $scientificResponse = Invoke-RestMethod "$Api/projects/$ProjectId/scientific-records?limit=500"
        $scientific = @($scientificResponse.items)
    }
    if (@($Fixture.records | Where-Object kind -in @('spatial_source_asset', 'spatial_calibration_review')).Count -gt 0) {
        $assets = @(Invoke-RestMethod "$Api/projects/$ProjectId/spatial/assets")
    }
    $observed = @()
    foreach ($record in @($Fixture.records)) {
        $kind = [string]$record.kind
        $expectedId = [string]$record.id
        $expectedHash = [string]$record.sha256
        if ($kind -eq 'scientific_record') {
            $matches = @(if ($AllowRemappedIds) {
                @($scientific | Where-Object { $_.content_sha256 -ceq $expectedHash })
            } else {
                @($scientific | Where-Object { [string]$_.id -ceq $expectedId -and $_.content_sha256 -ceq $expectedHash })
            })
            if ($matches.Count -ne 1) { throw "Expected one preserved scientific record with SHA-256 $expectedHash; found $($matches.Count)." }
            $observed += [pscustomobject]@{kind=$kind;original_id=$expectedId;current_id=[string]$matches[0].id;sha256=$expectedHash;evidence=$null;asset_id=$null}
            continue
        }
        if ($kind -eq 'spatial_source_asset') {
            $matches = @(if ($AllowRemappedIds) {
                @($assets | Where-Object { $_.sha256 -ceq $expectedHash })
            } else {
                @($assets | Where-Object { [string]$_.id -ceq $expectedId -and $_.sha256 -ceq $expectedHash })
            })
            if ($matches.Count -ne 1) { throw "Expected one preserved spatial source with SHA-256 $expectedHash; found $($matches.Count)." }
            $actualContentHash = Get-AcceptanceContentSha256 "$Api/projects/$ProjectId/spatial/assets/$($matches[0].id)/content"
            if ($actualContentHash -cne $expectedHash) { throw 'Spatial source API content does not match its immutable source hash.' }
            $observed += [pscustomobject]@{kind=$kind;original_id=$expectedId;current_id=[string]$matches[0].id;sha256=$expectedHash;evidence=$null;asset_id=[string]$matches[0].id}
            continue
        }
        if ($kind -eq 'spatial_calibration_review') {
            $reviews = @()
            foreach ($asset in $assets) {
                $response = Invoke-RestMethod "$Api/projects/$ProjectId/spatial/assets/$($asset.id)/calibration-reviews"
                foreach ($review in @($response)) {
                    $reviews += [pscustomobject]@{review=$review;asset_id=[string]$asset.id}
                }
            }
            if ($AllowRemappedIds) {
                $baselineReview = @($Baseline | Where-Object kind -eq 'spatial_calibration_review')
                if ($baselineReview.Count -ne 1) { throw 'Lineage exchange comparison requires exactly one baseline calibration review.' }
                $expectedEvidence = $baselineReview[0].evidence | ConvertTo-Json -Depth 8 -Compress
                $matches = @($reviews | Where-Object {
                    $_.review.source_sha256 -ceq $_.review.evidence.reviewed_source_payload_sha256 -and
                    $_.asset_id -ceq [string]$_.review.spatial_source_asset_id -and
                    $_.asset_id -ceq [string]$_.review.evidence.reviewed_spatial_source_asset_id -and
                    ((Get-NormalizedLineageReviewEvidence $_.review.evidence | ConvertTo-Json -Depth 8 -Compress) -ceq $expectedEvidence)
                })
            } else {
                $matches = @($reviews | Where-Object { [string]$_.review.id -ceq $expectedId -and $_.review.evidence_sha256 -ceq $expectedHash })
            }
            if ($matches.Count -ne 1) { throw "Expected one preserved calibration review; found $($matches.Count)." }
            $review = $matches[0].review
            $normalized = Get-NormalizedLineageReviewEvidence $review.evidence
            $observed += [pscustomobject]@{kind=$kind;original_id=$expectedId;current_id=[string]$review.id;sha256=[string]$review.evidence_sha256;evidence=$normalized;asset_id=[string]$matches[0].asset_id}
            continue
        }
        throw "Unsupported lineage evidence kind: $kind"
    }
    return ,$observed
}

function Import-AcceptanceExchange([string]$Url, [string]$ArchivePath, [string]$ProjectName) {
    Add-Type -AssemblyName System.Net.Http
    $http = [System.Net.Http.HttpClient]::new()
    $form = [System.Net.Http.MultipartFormDataContent]::new()
    try {
        $archiveBytes = [IO.File]::ReadAllBytes($ArchivePath)
        $file = [System.Net.Http.ByteArrayContent]::new([byte[]]$archiveBytes)
        $file.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse('application/zip')
        $form.Add($file, 'file', [IO.Path]::GetFileName($ArchivePath))
        $form.Add([System.Net.Http.StringContent]::new($ProjectName), 'project_name')
        $response = $http.PostAsync($Url, $form).GetAwaiter().GetResult()
        $payload = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) { throw "Project Exchange import failed with HTTP $([int]$response.StatusCode): $payload" }
        return $payload | ConvertFrom-Json
    } finally {
        $form.Dispose()
        $http.Dispose()
    }
}

function Export-AcceptanceExchange([string]$Api, [string]$ProjectId, [string]$ArchivePath, [string]$Notes) {
    $exchange = Invoke-RestMethod "$Api/projects/$ProjectId/exchange-packages" -Method Post -ContentType 'application/json' -Body (@{include_media=$true;include_model_weights=$false;include_generated_artifacts=$true;notes=$Notes} | ConvertTo-Json)
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    do {
        Start-Sleep -Milliseconds 500
        $job = Invoke-RestMethod "$Api/jobs/$($exchange.job_id)"
    } while ($job.status -in @('queued','running') -and [DateTime]::UtcNow -lt $deadline)
    if ($job.status -ne 'succeeded') { throw "Project Exchange export job ended as $($job.status)." }
    Invoke-WebRequest "$Api/exchange-packages/$($exchange.package.id)/download" -OutFile $ArchivePath
    if ((Get-Item $ArchivePath).Length -le 0) { throw 'Project Exchange archive is empty.' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        if (-not ($zip.Entries | Where-Object FullName -eq 'reefvision-exchange-manifest.json')) {
            throw 'Project Exchange archive has no reefvision-exchange-manifest.json.'
        }
    } finally { $zip.Dispose() }
    return $exchange
}

function New-AcceptanceSam2Image {
    param([switch]$YoloFixture)
    # Different imported images need different pixels: the import layer
    # deduplicates by image content even when filenames differ.
    Add-Type -AssemblyName System.Drawing
    $bitmap = [System.Drawing.Bitmap]::new(256, 256)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(210,155,92))
    $stream = [System.IO.MemoryStream]::new()
    try {
        $background = if ($YoloFixture) {
            [System.Drawing.Color]::FromArgb(62,49,36)
        } else {
            [System.Drawing.Color]::FromArgb(36,49,62)
        }
        $graphics.Clear($background)
        $graphics.FillEllipse($brush, 42, 42, 174, 174)
        $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
        return ,$stream.ToArray()
    } finally {
        $stream.Dispose()
        $brush.Dispose()
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

New-Item -ItemType Directory -Path $EvidenceRoot -Force | Out-Null
Save-Report
if ($PlanOnly) {
    $report.completed_at_utc = [DateTime]::UtcNow.ToString('o')
    Save-Report
    Write-Host 'PLAN ONLY - no MSI installation, launch, upgrade, or uninstall was performed.' -ForegroundColor Yellow
    Write-Host "Evidence report: $ReportPath"
    exit 0
}

$acceptanceAlreadyUninstalled = $false
try {
    if (-not (Test-ReefVisionAdministrator)) { throw 'Administrator privileges are required. Rerun PowerShell as Administrator on the disposable machine.' }
    $existing = @(Get-ReefVisionInstalledRegistrations)
    if ($existing.Count -gt 0) { throw 'Refusing to modify an existing ReefVision installation. Start from a disposable machine with no ReefVision registration.' }
    New-Item -ItemType Directory -Path $RunRoot,$DataRoot -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $RunRoot '.reefvision-acceptance-run') -Value $Token
    Set-Content -LiteralPath (Join-Path $DataRoot '.reefvision-clean-install-acceptance') -Value $Token
    if ($LineageFixture) {
        $stagedLineage = Copy-ReefVisionLineageProfile -Fixture $LineageFixture -DataRoot $DataRoot
        $report.lineage_preflight = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Verified and staged $LineageProfile at revision $($LineageFixture.revision); live database SHA-256 $((Get-FileHash -LiteralPath $stagedLineage.database -Algorithm SHA256).Hash.ToLowerInvariant()); backup remained outside the live profile."
    }

    # Seed a declarative record before launch so the installed candidate, not
    # a source checkout, proves the inspect-only discovery boundary. Earlier
    # upgrade baselines may ignore this directory; only the final candidate is
    # allowed to mark provider_manifests PASS below.
    $providerManifestDirectory = Join-Path $DataRoot 'provider-manifests'
    $providerManifestPath = Join-Path $providerManifestDirectory 'local-acceptance.json'
    New-Item -ItemType Directory -Path $providerManifestDirectory -Force | Out-Null
    $providerManifestJson = @{
        manifest_version = 1
        provider_id = 'local_acceptance'
        display_name = 'Installed acceptance manifest'
        provider_version = '0.1.0'
        description = 'Declarative installed-app acceptance record with no executable adapter.'
        capabilities = @('image_semantic_segmentation', 'cpu_inference')
        supported_tasks = @('relative_depth')
        availability = @{
            status = 'unavailable'
            reason = 'Installed acceptance deliberately supplies no executable adapter.'
        }
        code_license = 'Apache-2.0'
        weight_license = 'No weights supplied'
        notes = @('Inspection only')
    } | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText(
        $providerManifestPath,
        $providerManifestJson,
        [Text.UTF8Encoding]::new($false)
    )
    $providerManifestHash = (Get-FileHash -LiteralPath $providerManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()

    $initialInstaller = if ($PreviousInstallerPath -and -not $SkipUpgrade) { $PreviousInstallerPath } else { $InstallerPath }
    $exitCode = Run-Msi -Action Install -PackageOrProduct $initialInstaller -LogName 'install.log' -TargetRoot $InstallRoot
    if (-not (Test-Path (Join-Path $InstallRoot 'ReefVision.exe'))) { throw 'Installed ReefVision.exe is missing.' }
    if (-not (Test-Path (Join-Path $InstallRoot 'backend\reefvision-api\reefvision-api.exe'))) { throw 'Installed reefvision-api.exe is missing.' }
    $report.install = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "msiexec exit code $exitCode; desktop and sidecar present"
    $shortcutCandidates = @(
        (Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'ReefVision.lnk'),
        (Join-Path ([Environment]::GetFolderPath('CommonPrograms')) 'ReefVision\ReefVision.lnk'),
        (Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'ReefVision.lnk'),
        (Join-Path ([Environment]::GetFolderPath('Programs')) 'ReefVision\ReefVision.lnk')
    )
    $shortcuts = @($shortcutCandidates | Where-Object { Test-Path -LiteralPath $_ })
    $report.shortcuts = if ($shortcuts.Count) { New-ReefVisionEvidenceResult -Status 'PASS' -Detail ($shortcuts -join '; ') } else { New-ReefVisionEvidenceResult -Status 'FAIL' -Detail 'No ReefVision desktop or Start menu shortcut was found.' }
    if (-not $shortcuts.Count) { throw 'The MSI installed no discoverable ReefVision shortcut.' }

    if ($SpatialWorkflowNodePath) {
        $report.spatial_workflow = Get-ReefVisionInstalledJourneyEvidence {
            New-Item -ItemType Directory -Path $SpatialDataRoot | Out-Null
            Set-Content -LiteralPath (Join-Path $SpatialDataRoot '.reefvision-clean-install-acceptance') -Value $Token
            $debugPort = Get-ReefVisionLoopbackDebugPort
            $spatialDesktop = $null
            $ordinaryUser = $null
            $browserSid = ''
            $browserArtifacts = ''
            try {
                if ($HostedStandardUserWebView2) {
                    $ordinaryUser = New-ReefVisionHostedGuiAccount -RunRoot $RunRoot
                    $browserSid = $ordinaryUser.sid.Value
                    $spatialDesktop = Start-ReefVisionHostedGui -Account $ordinaryUser -Executable (Join-Path $InstallRoot 'ReefVision.exe') `
                        -Profile $SpatialDataRoot -DebugPort $debugPort -EvidenceRoot $EvidenceRoot
                    $browserArtifacts = $ordinaryUser.browser_artifacts
                } else {
                    $spatialDesktop = Start-AcceptanceDesktop -ProfileDataRoot $SpatialDataRoot -WebViewDebugPort $debugPort
                }
                $spatialPort = Wait-BackendPort -Path (Join-Path $SpatialDataRoot 'runtime\backend-port.txt') -DesktopProcess $spatialDesktop -BackendLogPath (Join-Path $SpatialDataRoot 'logs\backend.log')
                $spatialApi = "http://127.0.0.1:$spatialPort/api/v1"
                $null = Assert-AcceptancePackagedBackend -Api $spatialApi -ExpectedAppVersion $ProductVersion -ExpectedRevision $ExpectedSchemaRevision
                if ($FirstUseAcceptance) {
                    try {
                        $firstUse = Invoke-ReefVisionFirstUseAcceptance -NodePath $SpatialWorkflowNodePath -RepositoryRoot $RepositoryRoot `
                            -EvidenceRoot $EvidenceRoot -Api $spatialApi -DebugPort $debugPort -DesktopProcessId $spatialDesktop.Id `
                            -ExpectedVersion $ProductVersion -ExpectedBrowserSid $browserSid -BrowserArtifactsDirectory $browserArtifacts
                        $report.first_use_workflow = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Fresh installed profile completed keyboard onboarding, reviewed an annotation, and downloaded YOLO export SHA-256 $($firstUse.export_sha256)."
                    } catch {
                        $report.first_use_workflow = New-ReefVisionEvidenceResult -Status 'FAIL' -Detail $_.Exception.Message
                        throw
                    }
                }
                if ($ResearchWorkflowAcceptance) {
                    $report.research_workflow = Get-ReefVisionResearchJourneyEvidence {
                        Invoke-ReefVisionResearchJourneyAcceptance -NodePath $SpatialWorkflowNodePath -RepositoryRoot $RepositoryRoot `
                            -EvidenceRoot $EvidenceRoot -Api $spatialApi -DebugPort $debugPort -DesktopProcessId $spatialDesktop.Id `
                            -ExpectedBrowserSid $browserSid -BrowserArtifactsDirectory $browserArtifacts
                    }
                }
                $spatialResult = Invoke-ReefVisionSpatialWebView2Acceptance -NodePath $SpatialWorkflowNodePath -RepositoryRoot $RepositoryRoot `
                    -EvidenceRoot $EvidenceRoot -Api $spatialApi -DebugPort $debugPort -DesktopProcessId $spatialDesktop.Id `
                    -ExpectedBrowserSid $browserSid -BrowserArtifactsDirectory $browserArtifacts
                if ($WorkspaceWorkflowAcceptance) {
                    try {
                        $workspaces = Invoke-ReefVisionWorkspaceAcceptance -NodePath $SpatialWorkflowNodePath -RepositoryRoot $RepositoryRoot `
                            -EvidenceRoot $EvidenceRoot -Api $spatialApi -DebugPort $debugPort -DesktopProcessId $spatialDesktop.Id `
                            -ExpectedBrowserSid $browserSid -BrowserArtifactsDirectory $browserArtifacts
                        $workspaces | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath (Join-Path $EvidenceRoot 'workspace-evidence.json')
                        $report.workspace_workflow = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Installed WebView2 passed $($workspaces.completed_journeys) class, QC, dense image and manual video journeys."
                    } catch {
                        $report.workspace_workflow = New-ReefVisionEvidenceResult -Status 'FAIL' -Detail $_.Exception.Message
                    }
                }
                $spatialResult
            } finally {
                try {
                    if ($ordinaryUser) {
                        Remove-ReefVisionHostedGuiAccount -Account $ordinaryUser -EvidenceRoot $EvidenceRoot
                    } elseif ($spatialDesktop) {
                        try {
                            $spatialDesktop.Refresh()
                            Stop-AcceptanceDesktop $spatialDesktop
                        } catch {
                            if (-not $spatialDesktop.HasExited) {
                                $spatialDesktop.Kill($true)
                                $null = $spatialDesktop.WaitForExit(15000)
                            }
                            throw
                        }
                    }
                } finally {
                    Wait-ReefVisionWebView2DebugClosure -Port $debugPort
                }
            }
        }
        if ($ResearchWorkflowAcceptance -and $report.research_workflow.status -eq 'NOT RUN') {
            $report.research_workflow = New-ReefVisionEvidenceResult -Status 'FAIL' -Detail $report.spatial_workflow.detail
        }
        if ($FirstUseAcceptance -and $report.first_use_workflow.status -eq 'NOT RUN') {
            $report.first_use_workflow = New-ReefVisionEvidenceResult -Status 'FAIL' -Detail $report.spatial_workflow.detail
        }
        if ($WorkspaceWorkflowAcceptance -and $report.workspace_workflow.status -eq 'NOT RUN') {
            $report.workspace_workflow = New-ReefVisionEvidenceResult -Status 'FAIL' -Detail $report.spatial_workflow.detail
        }
        Save-Report
    }

    $desktop = Start-AcceptanceDesktop
    $port = Wait-BackendPort -Path (Join-Path $DataRoot 'runtime\backend-port.txt') -DesktopProcess $desktop -BackendLogPath (Join-Path $DataRoot 'logs\backend.log')
    $api = "http://127.0.0.1:$port/api/v1"
    $initialVersion = Get-AcceptanceMsiProperty -Path $initialInstaller -Name 'ProductVersion'
    $initialRevision = if ($initialInstaller -eq $InstallerPath) {
        $ExpectedSchemaRevision
    } elseif ($ExpectedInitialSchemaRevision) {
        $ExpectedInitialSchemaRevision
    } elseif ($LineageFixture) {
        [string]$LineageFixture.revision
    } else {
        ''
    }
    $migrationPayload = Assert-AcceptancePackagedBackend -Api $api -ExpectedAppVersion $initialVersion -ExpectedRevision $initialRevision
    $report.first_launch = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Desktop and packaged backend started; database initialized; API version $initialVersion"
    $report.frontend_backend_connectivity = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Desktop-published loopback API responded.'
    $webviewPid = Wait-AcceptanceWebView2 -DesktopProcessId $desktop.Id
    $report.webview2 = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "WebView2 browser PID $webviewPid started under the desktop."
    if ($initialRevision) {
        $report.schema_migration = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Packaged database reached $($migrationPayload.current_schema_revision)."
    }
    $lineageBaseline = $null
    if ($LineageFixture) {
        $lineageBaseline = Assert-AcceptanceLineageEvidence -Api $api -Fixture $LineageFixture -ProjectId $LineageFixture.project_id
        $report.lineage_initial_evidence = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Installed $initialVersion opened project $($LineageFixture.project_id) and preserved $(@($lineageBaseline).Count) declared evidence records from revision $($LineageFixture.revision)."
    }

    # Project templates were intentionally reduced to 'blank' in 1.0.
    # The acceptance fixture must explicitly create its class instead of
    # relying on the removed octocoral starter template.
    $project = Invoke-RestMethod "$api/projects" -Method Post -ContentType 'application/json' -Body (@{name="Clean install $Token";template='blank'} | ConvertTo-Json)
    $projectId = $project.id
    $testClass = Invoke-RestMethod "$api/projects/$projectId/classes" -Method Post -ContentType 'application/json' -Body (@{class_index=0;name='Acceptance coral';display_color='#7A8C9D'} | ConvertTo-Json)
    if (-not $testClass.id) { throw 'Acceptance label class could not be created.' }
    $Catalog = Invoke-RestMethod "$api/projects/$projectId/model-catalog"
    # Architecture entries use selection_kind=builtin_architecture;
    # category=architecture is a separate display grouping.
    $Architectures = @($Catalog.models | Where-Object { $_.selection_kind -eq 'builtin_architecture' })
    if ($Architectures.Count -lt 15) { throw 'Fresh profile does not expose the supported YOLO11 architecture families.' }
    $UnexpectedModels = @($Catalog.models | Where-Object {
        $_.selection_kind -eq 'managed_catalog_model' -or $_.installation_state -eq 'Ready' -or @($_.expected_files).Count -gt 0
    })
    if ($UnexpectedModels.Count -gt 0) { throw 'Fresh profile reports pretrained/downloadable or already-ready models.' }
    $CachedWeights = @(Get-ChildItem -LiteralPath $DataRoot -Recurse -File | Where-Object {
        $_.Extension -in @('.pt', '.pth', '.ckpt', '.safetensors', '.onnx', '.engine', '.bin', '.h5')
    })
    if ($CachedWeights.Count -gt 0) { throw 'Fresh profile contains unexpected model weights.' }
    $report.model_policy = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "$($Architectures.Count) architectures; zero pretrained/downloadable models; zero cached weights; isolated provider caches."
    $import = Import-AcceptanceImage "$api/projects/$projectId/imports/images"
    $imageId = $import.successful[0].image_id
    if ($CameraFixturePath) {
        # Optional physical acceptance fixture: only the disposable installed
        # backend receives the camera file. Never rewrite or EXIF-transpose it.
        # This is backend evidence, not a substitute for interactive WebView2 QA.
        $cameraHashBefore = (Get-FileHash -LiteralPath $CameraFixturePath -Algorithm SHA256).Hash
        $cameraBytes = [System.IO.File]::ReadAllBytes($CameraFixturePath)
        $cameraName = [System.IO.Path]::GetFileName($CameraFixturePath)
        $cameraImport = Import-AcceptanceImage -Url "$api/projects/$projectId/imports/images" -ImageBytes $cameraBytes -Filename $cameraName -RelativePath "camera/$cameraName" -ContentType 'image/jpeg'
        if (@($cameraImport.successful).Count -ne 1) {
            throw "Real camera JPEG did not import exactly once: $($cameraImport | ConvertTo-Json -Depth 5 -Compress)"
        }
        $cameraId = $cameraImport.successful[0].image_id
        $cameraMetadata = Invoke-RestMethod "$api/images/$cameraId"
        if ($cameraMetadata.media_type -ne 'image/jpeg' -or $cameraMetadata.width_px -le 0 -or $cameraMetadata.height_px -le 0) {
            throw 'Real camera JPEG lost its media type or source-pixel dimensions.'
        }
        # Validate the decoded source raster against the API's scientific pixel frame.
        $null = Assert-ReefVisionCameraRaster -Bytes $cameraBytes -ContentType 'image/jpeg' -ExpectedWidth ([int]$cameraMetadata.width_px) -ExpectedHeight ([int]$cameraMetadata.height_px)
        $cameraHttp = [System.Net.Http.HttpClient]::new()
        try {
            $storedBytes = $cameraHttp.GetByteArrayAsync("$api/images/$cameraId/content").GetAwaiter().GetResult()
            $sha = [System.Security.Cryptography.SHA256]::Create()
            try {
                $storedHash = [BitConverter]::ToString($sha.ComputeHash([byte[]]$storedBytes)).Replace('-', '')
            } finally { $sha.Dispose() }
            if ($storedHash -cne $cameraHashBefore) {
                throw 'Installed backend modified the original camera JPEG bytes.'
            }
            $displayResponse = $cameraHttp.GetAsync("$api/images/$cameraId/display").GetAwaiter().GetResult()
            try {
                if (-not $displayResponse.IsSuccessStatusCode) { throw 'Real camera JPEG display endpoint failed.' }
                $displayType = [string]$displayResponse.Content.Headers.ContentType.MediaType
                if ($displayType -notin @('image/jpeg', 'image/png')) {
                    throw "Real camera JPEG display has an unsupported content type: $displayType"
                }
                $displayBytes = $displayResponse.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
                if ($displayBytes.Length -eq 0) { throw 'Real camera JPEG display returned no pixels.' }
                # A nonempty HTTP response is insufficient: verify decodable pixels,
                # the declared media type, and unchanged annotation coordinates.
                $null = Assert-ReefVisionCameraRaster -Bytes ([byte[]]$displayBytes) -ContentType $displayType -ExpectedWidth ([int]$cameraMetadata.width_px) -ExpectedHeight ([int]$cameraMetadata.height_px)
                $orientation = $null
                $exifProperty = $cameraMetadata.metadata_json.PSObject.Properties['exif']
                if ($null -ne $exifProperty -and $null -ne $exifProperty.Value) {
                    $orientationProperty = $exifProperty.Value.PSObject.Properties['Orientation']
                    if ($null -ne $orientationProperty) { $orientation = $orientationProperty.Value }
                }
                if ($null -ne $orientation -and [string]$orientation -ne '1' -and $displayType -ne 'image/png') {
                    throw 'EXIF-oriented camera JPEG must use an unrotated PNG display rendition.'
                }
            } finally { $displayResponse.Dispose() }
        } finally { $cameraHttp.Dispose() }
        if ((Get-FileHash -LiteralPath $CameraFixturePath -Algorithm SHA256).Hash -cne $cameraHashBefore) {
            throw 'Camera acceptance modified the original fixture on disk.'
        }
        # Do not mark the camera acceptance PASS until it survives desktop restart.
        # A successful initial import alone does not establish durable media storage.
    }
    $session = Invoke-RestMethod "$api/images/$imageId/annotations"
    $annotationId = [guid]::NewGuid().ToString()
    $annotationBody = @{
        base_revision = $session.image.annotation_revision
        annotation_status = 'in_progress'
        annotations = @(@{
            id = $annotationId
            label_class_id = $testClass.id
            x_min = 0.1; y_min = 0.1; x_max = 0.9; y_max = 0.9
        })
        mask_annotations = @()
        deleted_mask_annotation_ids = @()
    } | ConvertTo-Json -Depth 6
    $saved = Invoke-RestMethod "$api/images/$imageId/annotations" -Method Put -ContentType 'application/json' -Body $annotationBody
    if ($saved.annotations[0].id -ne $annotationId) { throw 'Durable acceptance annotation was not returned after save.' }

    # Exercise the installed backend's real COCO and YOLO import parsers, not
    # test mocks or source-only fixtures. Imported classes are added to a
    # separate blank project to verify class preservation and idempotence.
    $interopProject = Invoke-RestMethod "$api/projects" -Method Post -ContentType 'application/json' -Body (@{name="Import QA $Token";template='blank'} | ConvertTo-Json)
    $interopId = $interopProject.id
    $interopImage = New-AcceptanceSam2Image
    $cocoImage = Import-AcceptanceImage -Url "$api/projects/$interopId/imports/images" -ImageBytes $interopImage -Filename 'coco-acceptance.png' -RelativePath 'imports/coco-acceptance.png'
    if (@($cocoImage.successful).Count -ne 1) {
        throw "COCO fixture image must import exactly once: $($cocoImage | ConvertTo-Json -Depth 5 -Compress)"
    }
    $cocoImageId = $cocoImage.successful[0].image_id
    $cocoFixture = @{
        images = @(@{id=23;file_name='coco-acceptance.png';width=256;height=256})
        categories = @(@{id=42;name='Swiftia exserta'},@{id=99;name='Muricea pendula'})
        annotations = @(
            @{id=1;image_id=23;category_id=42;bbox=@(32,32,64,64)},
            @{id=2;image_id=23;category_id=42;segmentation=@(,@(112,112,136,112,136,136,112,136))}
        )
    } | ConvertTo-Json -Depth 10 -Compress
    $cocoFiles = @(@{Name='acceptance_coco.json';Content=$cocoFixture;Mime='application/json'})
    $cocoResult = Import-AcceptanceAnnotations -Url "$api/projects/$interopId/imports/annotations" -Uploads $cocoFiles
    if ($cocoResult.boxes_imported -ne 1 -or $cocoResult.masks_imported -ne 1) {
        throw "Packaged COCO import expected one box/one polygon; got $($cocoResult.boxes_imported)/$($cocoResult.masks_imported)."
    }
    $cocoClasses = @( (Invoke-RestMethod "$api/projects/$interopId").label_classes | ForEach-Object { $_.name })
    if ('Swiftia exserta' -notin $cocoClasses -or 'Muricea pendula' -notin $cocoClasses) {
        throw 'COCO import did not preserve an annotated class and an unused class.'
    }
    $cocoSession = Invoke-RestMethod "$api/images/$cocoImageId/annotations"
    if (@($cocoSession.annotations).Count -ne 1 -or @($cocoSession.mask_annotations).Count -ne 1) {
        throw 'COCO import did not persist the box and mask in the annotation session.'
    }
    $repeatCoco = Import-AcceptanceAnnotations -Url "$api/projects/$interopId/imports/annotations" -Uploads $cocoFiles
    if ($repeatCoco.boxes_imported -ne 0 -or $repeatCoco.masks_imported -ne 0) {
        throw 'COCO import is not idempotent on the installed backend.'
    }

    $yoloImage = Import-AcceptanceImage -Url "$api/projects/$interopId/imports/images" -ImageBytes (New-AcceptanceSam2Image -YoloFixture) -Filename 'yolo-acceptance.png' -RelativePath 'imports/yolo-acceptance.png'
    if (@($yoloImage.successful).Count -ne 1) {
        throw "Distinct YOLO fixture image must import exactly once: $($yoloImage | ConvertTo-Json -Depth 5 -Compress)"
    }
    $yoloImageId = $yoloImage.successful[0].image_id
    if ($yoloImageId -eq $cocoImageId) { throw 'COCO and YOLO fixture images unexpectedly deduplicated.' }
    $yoloFiles = @(
        @{Name='yolo-acceptance.txt';Content="0 0.5 0.5 0.25 0.5`n";Mime='text/plain'},
        @{Name='data.yaml';Content="names:`n  0: Jellyfish`n  1: Octocoral`n";Mime='text/yaml'}
    )
    $yoloResult = Import-AcceptanceAnnotations -Url "$api/projects/$interopId/imports/annotations" -Uploads $yoloFiles
    if ($yoloResult.boxes_imported -ne 1) { throw "Packaged YOLO import created $($yoloResult.boxes_imported) boxes instead of one." }
    $yoloClasses = @((Invoke-RestMethod "$api/projects/$interopId").label_classes | ForEach-Object { $_.name })
    if ('Jellyfish' -notin $yoloClasses -or 'Octocoral' -notin $yoloClasses) {
        throw 'YOLO data.yaml class names were not preserved.'
    }
    $yoloSession = Invoke-RestMethod "$api/images/$yoloImageId/annotations"
    if (@($yoloSession.annotations).Count -ne 1) {
        throw 'YOLO import did not create a native image annotation.'
    }
    $report.external_annotation_imports = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Installed backend COCO box/mask, unused class, idempotence; YOLO boxes and all data.yaml class names; project $interopId."

    # Real online acquisition uses only the installed backend, not a developer
    # Python process. The default offline installer smoke test is unchanged.
    $samAcceptedMaskId = $null
    if ($LiveSam2Acceptance) {
        $samImage = New-AcceptanceSam2Image
        $samImport = Import-AcceptanceImage -Url "$api/projects/$projectId/imports/images" -ImageBytes $samImage -Filename 'sam2-live.png' -RelativePath 'synthetic/sam2-live.png'
        if (@($samImport.successful).Count -ne 1) { throw 'Live SAM image was not imported.' }
        $samImageId = $samImport.successful[0].image_id

        $samInstall = Invoke-RestMethod "$api/projects/$projectId/sam2-models/tiny/install" -Method Post
        if (-not $samInstall.id) { throw 'Packaged backend did not queue SAM 2.1 Tiny install.' }
        $samDeadline = [DateTime]::UtcNow.AddMinutes(15)
        do {
            Start-Sleep -Seconds 2
            $samJob = Invoke-RestMethod "$api/jobs/$($samInstall.id)"
        } while ($samJob.status -in @('queued','running') -and [DateTime]::UtcNow -lt $samDeadline)
        if ($samJob.status -ne 'succeeded') { throw "Packaged SAM 2.1 install failed: $($samJob.status); $($samJob.error_message)" }

        # Invoke-RestMethod deliberately emits JSON arrays as a single output
        # object in PowerShell. Avoid @(...Invoke-RestMethod...) double-wrapping
        # the array; enumerate the assigned response explicitly before filtering.
        $samModelsResponse = Invoke-RestMethod "$api/projects/$projectId/sam2-models"
        $samReady = @(
            foreach ($status in $samModelsResponse) {
                if ($null -ne $status -and $status.PSObject.Properties['variant'] -and $status.variant -eq 'tiny') {
                    $status
                }
            }
        )
        if ($samReady.Count -ne 1 -or -not $samReady[0].ready -or -not $samReady[0].revision -or -not $samReady[0].weight_sha256) {
            $summary = ConvertTo-Json -InputObject $samModelsResponse -Depth 6 -Compress
            throw "Packaged SAM 2.1 Tiny did not report a verified ready checkpoint. Model statuses: $summary"
        }
        $samRequest = @{
            task = 'assist_segmentation'
            device = 'cpu'
            allow_model_download = $false
            prompt_fields = @{ image_id=$samImageId;sam2_variant='tiny';box=@(35,35,225,225);label_class_id=$testClass.id }
        } | ConvertTo-Json -Depth 8
        # Actual SAM2 Tiny still runs a full-resolution image encoder even
        # on this 256px synthetic fixture. On GitHub's small Windows CPU VMs
        # that can exceed five minutes; retain a finite 15-minute upper bound.
        $samStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
        Write-Host "Starting real packaged SAM 2.1 Tiny CPU inference at $([DateTime]::UtcNow.ToString('o'))"
        try {
            $samInference = Invoke-RestMethod "$api/projects/$projectId/advanced-providers/sam2/execute" -Method Post -ContentType 'application/json' -Body $samRequest -TimeoutSec 900
        } catch {
            throw "Packaged SAM 2.1 CPU inference failed or exceeded 900 seconds after $([math]::Round($samStopwatch.Elapsed.TotalSeconds, 1)) seconds: $($_.Exception.Message)"
        } finally {
            $samStopwatch.Stop()
            Write-Host "Packaged SAM 2.1 CPU inference elapsed seconds: $([math]::Round($samStopwatch.Elapsed.TotalSeconds, 1))"
        }
        if ($samInference.result.review_status -ne 'pending' -or $samInference.result.proposal_count -ne 1 -or $samInference.result.area_pixels -le 0) {
            throw 'Installed SAM 2.1 did not produce a nonempty pending mask proposal.'
        }
        $samProposalId = $samInference.result.proposal_id
        $samPredictions = Invoke-RestMethod "$api/images/$samImageId/prediction-proposals"
        $samProposal = @($samPredictions.items | Where-Object id -eq $samProposalId)
        if ($samProposal.Count -ne 1 -or $samProposal[0].review_status -ne 'pending' -or $samProposal[0].accepted_mask_annotation_id) {
            throw 'SAM 2.1 inference was not persisted as an unaccepted prediction.'
        }
        if ($samProposal[0].model_checksum -ne $samReady[0].weight_sha256 -or -not $samProposal[0].provenance_json.requires_researcher_review) {
            throw 'SAM 2.1 prediction checksum/provenance is missing or invalid.'
        }
        # Confidence review must select pending predictions without
        # silently treating model output as researcher-verified annotations.
        $reviewQueue = Invoke-RestMethod "$api/projects/$projectId/review-queues" -Method Post -ContentType 'application/json' -Body (@{review_below_confidence=1.0} | ConvertTo-Json)
        $reviewItems = Invoke-RestMethod "$api/review-queues/$($reviewQueue.id)/items"
        if ($reviewQueue.item_count -ne 1 -or @($reviewItems.items | Where-Object image_id -eq $samImageId).Count -ne 1) {
            throw 'Low-confidence review queue did not include the pending SAM prediction.'
        }
        $samAcceptance = Invoke-RestMethod "$api/prediction-proposals/$samProposalId/accept" -Method Post -ContentType 'application/json' -Body (@{ label_class_id=$testClass.id } | ConvertTo-Json)
        if ($samAcceptance.proposal.review_status -notin @('accepted','edited_and_accepted') -or $samAcceptance.mask_annotation.status -ne 'verified') {
            throw 'Explicitly accepting SAM 2.1 proposal did not create a verified raster mask.'
        }
        $samAcceptedMaskId = $samAcceptance.mask_annotation.id
        $reviewAfterAccept = Invoke-RestMethod "$api/review-queues/$($reviewQueue.id)/regenerate" -Method Post
        if ($reviewAfterAccept.item_count -ne 0) {
            throw 'Confidence review incorrectly includes a researcher-accepted prediction.'
        }
        $report.confidence_review = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Packaged API included pending SAM prediction at confidence cutoff 1.0, excluded it after explicit acceptance; queue $($reviewQueue.id)."
        $report.sam2_live = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Installed app's backend downloaded SAM 2.1 Tiny, verified revision $($samReady[0].revision) and SHA256 $($samReady[0].weight_sha256), inferred image $samImageId (area $($samInference.result.area_pixels)), persisted pending proposal $samProposalId and accepted verified mask $samAcceptedMaskId; GUI hotkeys not exercised."
    }
    Stop-AcceptanceDesktop $desktop
    $projectChecksum = (Get-FileHash -LiteralPath (Join-Path $DataRoot 'reefvision.db') -Algorithm SHA256).Hash

    if ($PreviousInstallerPath -and -not $SkipUpgrade) {
        Run-Msi -Action Install -PackageOrProduct $InstallerPath -LogName 'upgrade.log' -TargetRoot $InstallRoot | Out-Null
    }

    $desktop = Start-AcceptanceDesktop
    $port = Wait-BackendPort -Path (Join-Path $DataRoot 'runtime\backend-port.txt') -DesktopProcess $desktop -BackendLogPath (Join-Path $DataRoot 'logs\backend.log')
    $api = "http://127.0.0.1:$port/api/v1"
    $finalMigration = Assert-AcceptancePackagedBackend -Api $api -ExpectedAppVersion $ProductVersion -ExpectedRevision $ExpectedSchemaRevision
    $report.schema_migration = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Packaged database reached $($finalMigration.current_schema_revision)."
    if ($LineageFixture) {
        $lineageFinal = Assert-AcceptanceLineageEvidence -Api $api -Fixture $LineageFixture -ProjectId $LineageFixture.project_id
        $report.lineage_final_evidence = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Candidate $ProductVersion migrated the historical profile to $($finalMigration.current_schema_revision) without changing project $($LineageFixture.project_id) or its $(@($lineageFinal).Count) declared evidence IDs and hashes."
    }
    $providerManifestResponse = Invoke-RestMethod "$api/advanced-providers/manifests"
    $localProviderRecords = @(
        foreach ($manifest in $providerManifestResponse) {
            if ($null -ne $manifest -and
                $manifest.PSObject.Properties['provider_id'] -and
                $manifest.provider_id -eq 'local_acceptance') {
                $manifest
            }
        }
    )
    if ($localProviderRecords.Count -ne 1) {
        throw "Installed provider catalog returned $($localProviderRecords.Count) local acceptance records instead of one."
    }
    $localProviderRecord = $localProviderRecords[0]
    if ($localProviderRecord.source_kind -ne 'local_manifest' -or
        $localProviderRecord.discovery_status -ne 'valid' -or
        $localProviderRecord.source_filename -ne 'local-acceptance.json' -or
        $localProviderRecord.source_sha256 -cne $providerManifestHash -or
        $localProviderRecord.execution_supported -ne $false -or
        $localProviderRecord.execution_surface -ne 'blocked') {
        throw "Installed provider manifest lost its inspect-only identity: $($localProviderRecord | ConvertTo-Json -Depth 6 -Compress)"
    }
    $providerPreflight = Invoke-RestMethod "$api/projects/$projectId/advanced-providers/local_acceptance/preflight" -Method Post -ContentType 'application/json' -Body (@{
        task = 'relative_depth'
        device = 'cpu'
        prompt_fields = @{ image_id = 'must-not-execute' }
    } | ConvertTo-Json -Depth 6)
    $inspectOnlyBlockers = @($providerPreflight.blockers | Where-Object { [string]$_ -match 'inspect-only' })
    if ($providerPreflight.ready -ne $false -or
        $providerPreflight.execution_supported -ne $false -or
        $providerPreflight.execution_surface -ne 'blocked' -or
        $inspectOnlyBlockers.Count -lt 1) {
        throw "Installed local provider preflight did not fail closed: $($providerPreflight | ConvertTo-Json -Depth 6 -Compress)"
    }
    $report.provider_manifests = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Installed packaged API discovered local-acceptance.json at SHA256 $providerManifestHash and returned inspect-only blocked preflight."
    $persisted = Invoke-RestMethod "$api/projects/$projectId"
    if ($persisted.id -ne $projectId) { throw 'Project ID changed across restart.' }
    $persistedAnnotations = Invoke-RestMethod "$api/images/$imageId/annotations"
    if (-not ($persistedAnnotations.annotations | Where-Object id -eq $annotationId)) { throw 'Acceptance annotation did not persist across restart.' }
    if ($CameraFixturePath) {
        # Validate media persistence independently of the in-memory import response.
        # This also covers an MSI upgrade when a previous installer was supplied.
        $persistedCamera = Invoke-RestMethod "$api/images/$cameraId"
        if ($persistedCamera.media_type -ne 'image/jpeg' -or
            [int]$persistedCamera.width_px -ne [int]$cameraMetadata.width_px -or
            [int]$persistedCamera.height_px -ne [int]$cameraMetadata.height_px) {
            throw 'Camera metadata changed or disappeared after packaged desktop restart.'
        }
        $cameraRestartHttp = [System.Net.Http.HttpClient]::new()
        try {
            $persistedCameraBytes = $cameraRestartHttp.GetByteArrayAsync("$api/images/$cameraId/content").GetAwaiter().GetResult()
            $restartSha = [System.Security.Cryptography.SHA256]::Create()
            try {
                $persistedHash = [BitConverter]::ToString($restartSha.ComputeHash([byte[]]$persistedCameraBytes)).Replace('-', '')
            } finally { $restartSha.Dispose() }
            if ($persistedHash -cne $cameraHashBefore) {
                throw 'Camera JPEG original bytes changed or disappeared after desktop restart.'
            }
            $restartDisplayResponse = $cameraRestartHttp.GetAsync("$api/images/$cameraId/display").GetAwaiter().GetResult()
            try {
                if (-not $restartDisplayResponse.IsSuccessStatusCode) {
                    throw 'Camera JPEG display endpoint failed after desktop restart.'
                }
                $restartDisplayType = [string]$restartDisplayResponse.Content.Headers.ContentType.MediaType
                $restartDisplayBytes = $restartDisplayResponse.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
                $null = Assert-ReefVisionCameraRaster -Bytes ([byte[]]$restartDisplayBytes) -ContentType $restartDisplayType -ExpectedWidth ([int]$cameraMetadata.width_px) -ExpectedHeight ([int]$cameraMetadata.height_px)
                Assert-ReefVisionStableCameraDisplay -InitialBytes ([byte[]]$displayBytes) -RestartBytes ([byte[]]$restartDisplayBytes) -InitialContentType $displayType -RestartContentType $restartDisplayType
            } finally { $restartDisplayResponse.Dispose() }
        } finally { $cameraRestartHttp.Dispose() }
        if ((Get-FileHash -LiteralPath $CameraFixturePath -Algorithm SHA256).Hash -cne $cameraHashBefore) {
            throw 'Camera fixture changed on disk during restart acceptance.'
        }
        $report.camera_jpeg = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Installed backend accepted and persisted $cameraName ($($cameraMetadata.width_px)x$($cameraMetadata.height_px)) across desktop restart; original SHA256 $cameraHashBefore unchanged; display decoded as $restartDisplayType and display SHA-256 unchanged across restart. GUI/WebView2 acceptance remains manual."
    }
    if ($LiveSam2Acceptance) {
        $persistedSamSession = Invoke-RestMethod "$api/images/$samImageId/annotations"
        if (-not ($persistedSamSession.mask_annotations | Where-Object id -eq $samAcceptedMaskId)) {
            throw 'Accepted SAM 2.1 mask did not persist across packaged Windows desktop restart.'
        }
    }
    if ($PreviousInstallerPath -and -not $SkipUpgrade) {
        $null = Wait-AcceptanceWebView2 -DesktopProcessId $desktop.Id
        $report.upgrade = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Upgraded from $initialVersion to $ProductVersion; WebView2, database and existing project verified."
    }
    $report.restart = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Desktop and backend restarted cleanly.'
    $report.project_persistence = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Project $projectId, image $imageId, and annotation $annotationId persisted; pre-restart database SHA-256 $projectChecksum"

    $archive = Join-Path $EvidenceRoot 'project-exchange.reefvision.zip'
    $null = Export-AcceptanceExchange -Api $api -ProjectId $projectId -ArchivePath $archive -Notes 'clean install acceptance'
    $report.project_exchange = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Exported inspectable archive: $archive"
    if ($LineageFixture) {
        $lineageArchive = Join-Path $EvidenceRoot "$LineageProfile.reefvision.zip"
        $null = Export-AcceptanceExchange -Api $api -ProjectId $LineageFixture.project_id -ArchivePath $lineageArchive -Notes "installed lineage acceptance: $LineageProfile"
        $lineageImport = Import-AcceptanceExchange -Url "$api/exchange-packages/import" -ArchivePath $lineageArchive -ProjectName "Lineage round trip $Token"
        if ([string]$lineageImport.project_id -ceq [string]$LineageFixture.project_id) {
            throw 'Project Exchange lineage import reused the source project ID.'
        }
        $lineageImported = Assert-AcceptanceLineageEvidence -Api $api -Fixture $LineageFixture -ProjectId $lineageImport.project_id -AllowRemappedIds -Baseline $lineageBaseline
        $report.lineage_exchange_roundtrip = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Exported $lineageArchive, imported isolated project $($lineageImport.project_id), and preserved $(@($lineageImported).Count) scientific/spatial evidence records with remapped IDs."
    }
    Stop-AcceptanceDesktop $desktop

    if ($LineageFixture) {
        New-Item -ItemType Directory -Path $RestoreDataRoot -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $RestoreDataRoot '.reefvision-clean-install-acceptance') -Value $Token
        $restoredLineage = Copy-ReefVisionLineageProfile -Fixture $LineageFixture -DataRoot $RestoreDataRoot -UseBackup
        if ($VerifyPreviousInstallerRejectsUpgradedProfile) {
            $upgradedDatabase = Join-Path $DataRoot 'reefvision.db'
            $upgradedHashBefore = (Get-FileHash -LiteralPath $upgradedDatabase -Algorithm SHA256).Hash.ToLowerInvariant()
            $candidateProductCode = Get-AcceptanceMsiProperty -Path $InstallerPath -Name 'ProductCode'
            Run-Msi -Action Uninstall -PackageOrProduct $candidateProductCode -LogName 'candidate-before-historical-rejection-uninstall.log' | Out-Null
            Run-Msi -Action Install -PackageOrProduct $PreviousInstallerPath -LogName 'historical-rejection-install.log' -TargetRoot $InstallRoot | Out-Null
            $rejectionDetail = Assert-HistoricalDesktopRejectsProfile -ProfileDataRoot $DataRoot -RejectedRevision $ExpectedSchemaRevision
            $upgradedHashAfter = (Get-FileHash -LiteralPath $upgradedDatabase -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($upgradedHashAfter -cne $upgradedHashBefore) {
                throw 'Historical build changed the upgraded database while rejecting it.'
            }
            $report.historical_schema_rejection = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Historical $initialVersion rejected schema $ExpectedSchemaRevision ($rejectionDetail); database SHA-256 remained $upgradedHashAfter."

            $restoreDesktop = Start-AcceptanceDesktop -ProfileDataRoot $RestoreDataRoot
            $restorePort = Wait-BackendPort -Path (Join-Path $RestoreDataRoot 'runtime\backend-port.txt') -DesktopProcess $restoreDesktop -BackendLogPath (Join-Path $RestoreDataRoot 'logs\backend.log')
            $restoreApi = "http://127.0.0.1:$restorePort/api/v1"
            $null = Assert-AcceptancePackagedBackend -Api $restoreApi -ExpectedAppVersion $initialVersion -ExpectedRevision $LineageFixture.revision
            $restoredEvidence = Assert-AcceptanceLineageEvidence -Api $restoreApi -Fixture $LineageFixture -ProjectId $LineageFixture.project_id
            Stop-AcceptanceDesktop $restoreDesktop
            $report.lineage_restore = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Historical $initialVersion opened the separate verified backup at $($LineageFixture.revision) and preserved $(@($restoredEvidence).Count) declared evidence records; live upgraded profile was not replaced."
            $previousProductCode = Get-AcceptanceMsiProperty -Path $PreviousInstallerPath -Name 'ProductCode'
            Run-Msi -Action Uninstall -PackageOrProduct $previousProductCode -LogName 'historical-final-uninstall.log' | Out-Null
            $acceptanceAlreadyUninstalled = $true
        } else {
            $restoreDesktop = Start-AcceptanceDesktop -ProfileDataRoot $RestoreDataRoot
            $restorePort = Wait-BackendPort -Path (Join-Path $RestoreDataRoot 'runtime\backend-port.txt') -DesktopProcess $restoreDesktop -BackendLogPath (Join-Path $RestoreDataRoot 'logs\backend.log')
            $restoreApi = "http://127.0.0.1:$restorePort/api/v1"
            $restoreMigration = Assert-AcceptancePackagedBackend -Api $restoreApi -ExpectedAppVersion $ProductVersion -ExpectedRevision $ExpectedSchemaRevision
            $restoredEvidence = Assert-AcceptanceLineageEvidence -Api $restoreApi -Fixture $LineageFixture -ProjectId $LineageFixture.project_id
            Stop-AcceptanceDesktop $restoreDesktop
            $report.lineage_restore = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Candidate $ProductVersion opened the separate verified $($LineageFixture.revision) backup, migrated it to $($restoreMigration.current_schema_revision), and preserved $(@($restoredEvidence).Count) declared evidence records; live upgraded profile was not replaced."
        }
    }

    if (-not $SkipUninstall) {
        if (-not $acceptanceAlreadyUninstalled) {
            $productCode = Get-AcceptanceMsiProperty -Path $InstallerPath -Name 'ProductCode'
            Run-Msi -Action Uninstall -PackageOrProduct $productCode -LogName 'uninstall.log' | Out-Null
        }
        if (Test-Path (Join-Path $InstallRoot 'ReefVision.exe')) { throw 'ReefVision.exe remains after uninstall.' }
        if (@($shortcutCandidates | Where-Object { Test-Path -LiteralPath $_ }).Count -gt 0) { throw 'A ReefVision shortcut remains after uninstall.' }
        if (@(Get-ReefVisionInstalledRegistrations).Count -gt 0) { throw 'ReefVision uninstall registration remains after uninstall.' }
        $report.uninstall = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Program binaries removed.'
        if (-not (Test-Path $DataRoot)) { throw 'Isolated user data was removed by uninstall.' }
        $report.data_retention = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Isolated project data remained after uninstall.'
    } else {
        $report.data_retention = New-ReefVisionEvidenceResult -Status 'NOT RUN' -Detail 'Uninstall was skipped.'
    }
    if ($report.spatial_workflow.status -eq 'FAIL') {
        throw $report.spatial_workflow.detail
    }
    if ($report.first_use_workflow.status -eq 'FAIL') {
        throw $report.first_use_workflow.detail
    }
    if ($report.workspace_workflow.status -eq 'FAIL') {
        throw $report.workspace_workflow.detail
    }
    if ($report.research_workflow.status -eq 'FAIL') {
        throw $report.research_workflow.detail
    }
} catch {
    $report.failure_reason = $_.Exception.Message
    Save-Report
    throw
} finally {
    # On failure the disposable Windows runner is destroyed. Preserve the
    # packaged sidecar's logs for model-loading/CPU/deadlock diagnostics.
    # Never copy project images, user data or checkpoint weights into CI.
    # The sidecar initially writes backend.log, but FastAPI create_app()
    # switches the rotating logger to api.log. Capture both logs and rotated
    # files: SAM2 stage timings and inference exceptions land in api.log.
    foreach ($profileLogs in @(
        [pscustomobject]@{root=$DataRoot;prefix='live'},
        [pscustomobject]@{root=$SpatialDataRoot;prefix='spatial'},
        [pscustomobject]@{root=$RestoreDataRoot;prefix='restore'}
    )) {
        foreach ($logName in @('backend.log', 'api.log', 'api.log.1', 'api.log.2')) {
            $sourceLog = Join-Path (Join-Path $profileLogs.root 'logs') $logName
            if (Test-Path -LiteralPath $sourceLog -PathType Leaf) {
                try {
                    $evidenceName = "$($profileLogs.prefix).$logName.tail.log"
                    Get-Content -LiteralPath $sourceLog -Tail 500 -ErrorAction Stop |
                        Set-Content -LiteralPath (Join-Path $EvidenceRoot $evidenceName) -Encoding utf8 -ErrorAction Stop
                } catch {
                    Write-Warning "Could not archive $($profileLogs.prefix) $logName tail: $($_.Exception.Message)"
                }
            }
        }
    }
    $report.completed_at_utc = [DateTime]::UtcNow.ToString('o')
    Save-Report
    if (-not $KeepArtifacts -and (Test-Path (Join-Path $RunRoot '.reefvision-acceptance-run')) -and $report.uninstall.status -eq 'PASS') {
        $ExpectedRunRoot = [System.IO.Path]::GetFullPath((Join-Path $AcceptanceRoot "reefvision-clean-$Token"))
        if ([System.IO.Path]::GetFullPath($RunRoot) -ne $ExpectedRunRoot) { throw 'Refusing cleanup outside the generated acceptance run.' }
        Remove-Item -LiteralPath $RunRoot -Recurse -Force
    }
}

Write-Host 'ReefVision clean Windows acceptance passed.' -ForegroundColor Green
Write-Host "Evidence report: $ReportPath"
