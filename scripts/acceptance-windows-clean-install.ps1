param(
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [Parameter(Mandatory = $true)][string]$AcceptanceRoot,
    [string]$PreviousInstallerPath = '',
    [switch]$PreviousInstallerSupportsIsolatedAcceptance,
    [switch]$DisposableTest,
    [switch]$PlanOnly,
    [switch]$KeepArtifacts,
    [switch]$SkipUpgrade,
    [switch]$SkipUninstall,
    [switch]$LiveSam2Acceptance,
    [switch]$ApprovedCheckpointDownload
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'lib\windows-clean-acceptance.ps1')

if (-not $DisposableTest -and -not $PlanOnly) {
    throw 'Refusing destructive MSI acceptance. Supply -DisposableTest on a disposable Windows VM/machine, or use -PlanOnly.'
}
if ($DisposableTest -and $PlanOnly) { throw '-DisposableTest and -PlanOnly are mutually exclusive.' }

# Live SAM acceptance obtains pretrained checkpoint weights over the network.
# Require a separate, explicit approval switch even on disposable machines;
# unattended PR workflows must never silently fetch weights.
if ($LiveSam2Acceptance -and -not $ApprovedCheckpointDownload) {
    throw 'Live SAM acceptance requires explicit -ApprovedCheckpointDownload researcher approval before fetching pretrained weights.'
}

$InstallerPath = (Resolve-Path -LiteralPath $InstallerPath).Path
if ([System.IO.Path]::GetExtension($InstallerPath) -ine '.msi') { throw 'InstallerPath must identify an MSI.' }
if ($PreviousInstallerPath) {
    $PreviousInstallerPath = (Resolve-Path -LiteralPath $PreviousInstallerPath).Path
    if ([System.IO.Path]::GetExtension($PreviousInstallerPath) -ine '.msi') { throw 'PreviousInstallerPath must identify an MSI.' }
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
$EvidenceRoot = Join-Path $RepositoryRoot ".artifacts\windows-clean-acceptance-$Token"
$ReportPath = Join-Path $EvidenceRoot 'report.json'
$InstallerHash = (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash
# Validate the entire function result, not just the COM record's value:
# leaked PowerShell pipeline output must never enter evidence or upgrade checks.
$ProductVersion = Assert-ReefVisionMsiVersionScalar -Value (Get-ReefVisionMsiProductVersion -Path $InstallerPath)
$PreviousProductVersion = $null
if ($PreviousInstallerPath -and -not $SkipUpgrade) {
    $PreviousProductVersion = Assert-ReefVisionMsiVersionScalar -Value (Get-ReefVisionMsiProductVersion -Path $PreviousInstallerPath)
    [void](Assert-ReefVisionUpgradeVersion -PreviousVersion $PreviousProductVersion -TargetVersion $ProductVersion)
}

$report = [ordered]@{
    schema_version = 'reefvision-windows-clean-acceptance-1'
    started_at_utc = [DateTime]::UtcNow.ToString('o')
    completed_at_utc = $null
    reefvision_version = $ProductVersion
    installer_path = $InstallerPath
    installer_sha256 = $InstallerHash
    previous_installer_path = if ($PreviousInstallerPath) { $PreviousInstallerPath } else { $null }
    previous_installer_version = $PreviousProductVersion
    windows_version = [Environment]::OSVersion.VersionString
    architecture = $env:PROCESSOR_ARCHITECTURE
    acceptance_root = $AcceptanceRoot
    isolated_data_root = $DataRoot
    plan_only = [bool]$PlanOnly
    install = New-ReefVisionEvidenceResult
    shortcuts = New-ReefVisionEvidenceResult
    first_launch = New-ReefVisionEvidenceResult
    frontend_backend_connectivity = New-ReefVisionEvidenceResult
    migration = $null
    model_policy = New-ReefVisionEvidenceResult
    sam2_live = if ($LiveSam2Acceptance) { New-ReefVisionEvidenceResult } else { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'Real SAM 2.1 packaged runtime acceptance not requested' }
    external_annotation_imports = New-ReefVisionEvidenceResult
    confidence_review = if ($LiveSam2Acceptance) { New-ReefVisionEvidenceResult } else { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'Real pending prediction review not requested' }
    project_persistence = New-ReefVisionEvidenceResult
    class_visibility_persistence = New-ReefVisionEvidenceResult
    qc_review_coordination = New-ReefVisionEvidenceResult
    qc_workflow_persistence = New-ReefVisionEvidenceResult
    qc_workflow_replay = New-ReefVisionEvidenceResult
    restart = New-ReefVisionEvidenceResult
    project_exchange = New-ReefVisionEvidenceResult
    upgrade = if ($SkipUpgrade) { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'SkipUpgrade requested' } elseif (-not $PreviousInstallerPath) { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'previous installer not supplied' } else { New-ReefVisionEvidenceResult }
    uninstall = if ($SkipUninstall) { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'SkipUninstall requested' } else { New-ReefVisionEvidenceResult }
    data_retention = New-ReefVisionEvidenceResult
    failure_reason = $null
}

function Save-Report { Write-ReefVisionEvidenceReport -Report $report -Path $ReportPath }
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
# backend-port.txt is written before the packaged Uvicorn API is ready.
# A successful port-file read is not sufficient after desktop restarts.
function Wait-BackendApiReady(
    [string]$ApiBaseUrl,
    [System.Diagnostics.Process]$DesktopProcess,
    [string]$BackendLogPath,
    [int]$Seconds = 120
) {
    if ($ApiBaseUrl -notmatch '^http://127\.0\.0\.1:\d{1,5}/api/v1$') {
        throw 'Backend readiness must use the installed loopback API.'
    }
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    $lastFailure = 'API did not respond'
    while ([DateTime]::UtcNow -lt $deadline) {
        $DesktopProcess.Refresh()
        if ($DesktopProcess.HasExited) {
            $exitCode = try { $DesktopProcess.ExitCode } catch { 'unavailable' }
            throw "Desktop exited before packaged API became ready (exit code: $exitCode)."
        }
        try {
            $version = Invoke-RestMethod -Uri "$ApiBaseUrl/system/version" -TimeoutSec 3 -ErrorAction Stop
            $migration = Invoke-RestMethod -Uri "$ApiBaseUrl/system/migrations/status" -TimeoutSec 3 -ErrorAction Stop
            if ($version.application_version -and $migration.schema_status -eq 'up_to_date' -and
                $migration.current_schema_revision -eq $migration.expected_schema_revision) {
                return
            }
            $lastFailure = "API returned incomplete version or migration readiness: $($migration.schema_status)"
        } catch {
            $lastFailure = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 500
    }
    $logTail = if (Test-Path -LiteralPath $BackendLogPath -PathType Leaf) {
        (Get-Content -LiteralPath $BackendLogPath -Tail 20 | Out-String).TrimEnd()
    } else { '(backend log unavailable)' }
    throw ("Packaged API was not ready after $Seconds seconds ($lastFailure). Backend log tail:" + [Environment]::NewLine + $logTail)
}

function Start-AcceptanceDesktop {
    $BackendPortPath = Join-Path $DataRoot 'runtime\backend-port.txt'
    Remove-Item -LiteralPath $BackendPortPath -Force -ErrorAction SilentlyContinue
    $isolatedOverrides = @{
        REEFVISION_WINDOWS_ACCEPTANCE = '1'
        REEFVISION_ACCEPTANCE_DATA_DIR = $DataRoot
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
    return Invoke-ReefVisionIsolatedEnvironment -DataRoot $DataRoot -AdditionalEnvironment $isolatedOverrides -Action {
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
function Import-AcceptanceImage(
    [string]$Url,
    [byte[]]$ImageBytes = $null,
    [string]$Filename = 'acceptance.png',
    [string]$RelativePath = 'synthetic/acceptance.png'
) {
    Add-Type -AssemblyName System.Net.Http
    $png = if ($null -ne $ImageBytes) { $ImageBytes } else { [Convert]::FromBase64String('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=') }
    $client = New-Object System.Net.Http.HttpClient
    $form = New-Object System.Net.Http.MultipartFormDataContent
    try {
        $file = New-Object System.Net.Http.ByteArrayContent -ArgumentList (,$png)
        $file.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse('image/png')
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

try {
    if (-not (Test-ReefVisionAdministrator)) { throw 'Administrator privileges are required. Rerun PowerShell as Administrator on the disposable machine.' }
    $existing = @(Get-ReefVisionInstalledRegistrations)
    if ($existing.Count -gt 0) { throw 'Refusing to modify an existing ReefVision installation. Start from a disposable machine with no ReefVision registration.' }
    New-Item -ItemType Directory -Path $RunRoot,$DataRoot -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $RunRoot '.reefvision-acceptance-run') -Value $Token
    Set-Content -LiteralPath (Join-Path $DataRoot '.reefvision-clean-install-acceptance') -Value $Token

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

    $desktop = Start-AcceptanceDesktop
    $port = Wait-BackendPort -Path (Join-Path $DataRoot 'runtime\backend-port.txt') -DesktopProcess $desktop -BackendLogPath (Join-Path $DataRoot 'logs\backend.log')
    $api = "http://127.0.0.1:$port/api/v1"
    Wait-BackendApiReady -ApiBaseUrl $api -DesktopProcess $desktop -BackendLogPath (Join-Path $DataRoot 'logs\backend.log')
    $versionPayload = Invoke-RestMethod "$api/system/version"
    $migrationPayload = Invoke-RestMethod "$api/system/migrations/status"
    # A healthy HTTP endpoint is not proof that the installed SQLite schema
    # was migrated. Verify both its revision and its disposable data boundary
    # before the first project write. Report only schema metadata, never rows.
    $expectedDatabase = [System.IO.Path]::GetFullPath((Join-Path $DataRoot 'reefvision.db'))
    $actualDatabase = if ($versionPayload.database_path) {
        [System.IO.Path]::GetFullPath([string]$versionPayload.database_path)
    } else { '' }
    $databaseIsIsolated = [string]::Equals(
        $actualDatabase, $expectedDatabase,
        [System.StringComparison]::OrdinalIgnoreCase
    )
    $report.migration = [ordered]@{
        schema_status = [string]$migrationPayload.schema_status
        current_revision = [string]$migrationPayload.current_schema_revision
        expected_revision = [string]$migrationPayload.expected_schema_revision
        database_path_is_isolated = $databaseIsIsolated
    }
    if (-not $databaseIsIsolated) {
        throw 'Packaged API database path escapes the disposable acceptance data root; refusing project writes.'
    }
    if ($migrationPayload.schema_status -ne 'up_to_date' -or
        $migrationPayload.current_schema_revision -ne $migrationPayload.expected_schema_revision) {
        throw "Packaged API schema is not migrated: status=$($migrationPayload.schema_status); current=$($migrationPayload.current_schema_revision); expected=$($migrationPayload.expected_schema_revision). Refusing project writes."
    }
    $report.first_launch = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Desktop and packaged backend started; database initialized; API version $($versionPayload.application_version)"
    $report.frontend_backend_connectivity = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Desktop-published loopback API responded; migration status: $($migrationPayload.schema_status)"

    # Project templates were intentionally reduced to 'blank' in 1.0.
    # The acceptance fixture must explicitly create its class instead of
    # relying on the removed octocoral starter template.
    $project = Invoke-RestMethod "$api/projects" -Method Post -ContentType 'application/json' -Body (@{name="Clean install $Token";template='blank'} | ConvertTo-Json)
    $projectId = $project.id
    $testClass = Invoke-RestMethod "$api/projects/$projectId/classes" -Method Post -ContentType 'application/json' -Body (@{class_index=0;name='Acceptance coral';display_color='#7A8C9D'} | ConvertTo-Json)
    if (-not $testClass.id) { throw 'Acceptance label class could not be created.' }
    # 1.6 class visibility must persist in the installed, isolated backend,
    # not just in source-tree API tests. A saved empty user preference
    # intentionally overrides the project's nonempty default.
    $visibilityUrl = "$api/projects/$projectId/class-visibility"
    $defaultVisibility = Invoke-RestMethod "$visibilityUrl/defaults/annotations" -Method Put -ContentType 'application/json' -Body (@{
        hidden_class_ids = @([string]$testClass.id)
    } | ConvertTo-Json -Depth 4)
    $userVisibility = Invoke-RestMethod "$visibilityUrl/preferences/annotations" -Method Put -ContentType 'application/json' -Body (@{
        hidden_class_ids = @()
    } | ConvertTo-Json -Depth 4)
    $initialVisibility = Invoke-RestMethod $visibilityUrl
    if (-not $defaultVisibility.saved -or -not $userVisibility.saved -or
        $initialVisibility.project_id -ne $projectId -or
        -not ([string]$initialVisibility.user_identity).StartsWith('local-user:') -or
        -not $initialVisibility.project_defaults.annotations.saved -or
        @($initialVisibility.project_defaults.annotations.hidden_class_ids).Count -ne 1 -or
        $initialVisibility.project_defaults.annotations.hidden_class_ids[0] -ne $testClass.id -or
        -not $initialVisibility.user_preferences.annotations.saved -or
        @($initialVisibility.user_preferences.annotations.hidden_class_ids).Count -ne 0) {
        throw 'Installed class visibility did not save a project default and explicit empty local-user override.'
    }
    $visibilityIdentity = [string]$initialVisibility.user_identity
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
        # msiexec exit 0 alone does not prove the newer desktop was installed.
        # Keep upgrade unaccepted until the restarted API, registry and
        # preserved scientific project are checked below.
        $report.upgrade = New-ReefVisionEvidenceResult -Status 'NOT RUN' -Detail 'MSI returned success; post-upgrade checks pending.'
    }

    $desktop = Start-AcceptanceDesktop
    $port = Wait-BackendPort -Path (Join-Path $DataRoot 'runtime\backend-port.txt') -DesktopProcess $desktop -BackendLogPath (Join-Path $DataRoot 'logs\backend.log')
    $api = "http://127.0.0.1:$port/api/v1"
    Wait-BackendApiReady -ApiBaseUrl $api -DesktopProcess $desktop -BackendLogPath (Join-Path $DataRoot 'logs\backend.log')
    $persisted = Invoke-RestMethod "$api/projects/$projectId"
    if ($persisted.id -ne $projectId) { throw 'Project ID changed across restart.' }
    $persistedAnnotations = Invoke-RestMethod "$api/images/$imageId/annotations"
    if (-not ($persistedAnnotations.annotations | Where-Object id -eq $annotationId)) { throw 'Acceptance annotation did not persist across restart.' }
    # The desktop chooses a fresh ephemeral loopback port on each launch.
    # Never reuse the first launch's cached visibility URL after restart.
    $persistedVisibility = Invoke-RestMethod "$api/projects/$projectId/class-visibility"
    if ($persistedVisibility.project_id -ne $projectId -or
        [string]$persistedVisibility.user_identity -ne $visibilityIdentity -or
        -not $persistedVisibility.project_defaults.annotations.saved -or
        @($persistedVisibility.project_defaults.annotations.hidden_class_ids).Count -ne 1 -or
        $persistedVisibility.project_defaults.annotations.hidden_class_ids[0] -ne $testClass.id -or
        -not $persistedVisibility.user_preferences.annotations.saved -or
        @($persistedVisibility.user_preferences.annotations.hidden_class_ids).Count -ne 0) {
        throw 'Installed class visibility project default, saved empty override, or local identity changed after restart/upgrade.'
    }
    $report.class_visibility_persistence = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Packaged API persisted project annotation default, explicit empty local-user override, and stable local identity across restart/upgrade.'
    if ($LiveSam2Acceptance) {
        $persistedSamSession = Invoke-RestMethod "$api/images/$samImageId/annotations"
        if (-not ($persistedSamSession.mask_annotations | Where-Object id -eq $samAcceptedMaskId)) {
            throw 'Accepted SAM 2.1 mask did not persist across packaged Windows desktop restart.'
        }
    }
    if ($PreviousInstallerPath -and -not $SkipUpgrade) {
        $upgradedVersion = Invoke-RestMethod "$api/system/version"
        $upgradedMigration = Invoke-RestMethod "$api/system/migrations/status"
        $registrations = @(Get-ReefVisionInstalledRegistrations)
        $upgradedDatabase = if ($upgradedVersion.database_path) {
            [System.IO.Path]::GetFullPath([string]$upgradedVersion.database_path)
        } else { '' }
        if ([string]$upgradedVersion.application_version -ne $ProductVersion -or
            $registrations.Count -ne 1 -or
            [string]$registrations[0].DisplayVersion -ne $ProductVersion) {
            throw "MSI upgrade did not expose expected version $ProductVersion through both API and Windows registration."
        }
        if (-not [string]::Equals($upgradedDatabase, $expectedDatabase, [System.StringComparison]::OrdinalIgnoreCase) -or
            $upgradedMigration.schema_status -ne 'up_to_date' -or
            $upgradedMigration.current_schema_revision -ne $upgradedMigration.expected_schema_revision) {
            throw 'MSI upgrade changed the isolated database boundary or left migrations incomplete.'
        }
        $report.upgrade = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Verified version $PreviousProductVersion -> $ProductVersion through MSI, registry and packaged API; project and annotation retained; isolated schema current."
    }
    $report.restart = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Desktop and backend restarted cleanly.'
    $report.project_persistence = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Project $projectId, image $imageId, and annotation $annotationId persisted; pre-restart database SHA-256 $projectChecksum"

    # 1.6 packaged QC acceptance: exercise the actual installed API against
    # disposable project media, not a source-tree TestClient or synthetic mock.
    # Triage is manual coordination only; no prediction or annotation approval.
    $qcQueue = Invoke-RestMethod "$api/projects/$projectId/review-queues" -Method Post -ContentType 'application/json' -Body '{}'
    if ($qcQueue.project_id -ne $projectId -or [int]$qcQueue.item_count -lt 1) {
        throw 'Installed QC review queue did not retain the disposable project scope.'
    }
    $qcPage = Invoke-RestMethod "$api/review-queues/$($qcQueue.id)/items"
    $qcMatches = @($qcPage.items | Where-Object { $_.image_id -eq $imageId })
    if ($qcMatches.Count -ne 1) { throw 'Installed QC queue did not contain exactly one acceptance image.' }
    $qcItemId = [string]$qcMatches[0].id
    $qcEventsUrl = "$api/review-queues/$($qcQueue.id)/items/$qcItemId/events"
    $qcCommentBody = @{
        client_request_id = [guid]::NewGuid().ToString()
        event_type = 'comment'
        actor = 'disposable-lab-reviewer'
        comment = 'Review synthetic annotation boundary'
    } | ConvertTo-Json
    $qcComment = Invoke-RestMethod $qcEventsUrl -Method Post -ContentType 'application/json' -Body $qcCommentBody
    $qcCommentRetry = Invoke-RestMethod $qcEventsUrl -Method Post -ContentType 'application/json' -Body $qcCommentBody
    if ($qcComment.id -ne $qcCommentRetry.id) { throw 'Installed QC comment retry duplicated the audit event.' }
    $qcAssignBody = @{
        client_request_id = [guid]::NewGuid().ToString()
        event_type = 'assign'
        actor = 'disposable-lab-reviewer'
        assignee = 'disposable-reviewer-two'
    } | ConvertTo-Json
    $null = Invoke-RestMethod $qcEventsUrl -Method Post -ContentType 'application/json' -Body $qcAssignBody
    $qcBulkUrl = "$api/review-queues/$($qcQueue.id)/items/bulk"
    $qcSkipBody = @{
        item_ids = @($qcItemId)
        action = 'skip'
        reason = 'Synthetic QC acceptance'
        actor = 'disposable-lab-reviewer'
    } | ConvertTo-Json
    $qcSkipped = Invoke-RestMethod $qcBulkUrl -Method Post -ContentType 'application/json' -Body $qcSkipBody
    $qcSkipRetry = Invoke-RestMethod $qcBulkUrl -Method Post -ContentType 'application/json' -Body $qcSkipBody
    if ($qcSkipped.changed_count -ne 1 -or $qcSkipRetry.changed_count -ne 0 -or
        $qcSkipped.requires_researcher_review -ne $true) {
        throw 'Installed QC bulk skip was not guarded and retry-safe.'
    }
    $qcReturnBody = @{item_ids=@($qcItemId);action='return';actor='disposable-lab-reviewer'} | ConvertTo-Json
    $qcReturned = Invoke-RestMethod $qcBulkUrl -Method Post -ContentType 'application/json' -Body $qcReturnBody
    $qcStartBody = @{item_ids=@($qcItemId);action='start';actor='disposable-lab-reviewer'} | ConvertTo-Json
    $qcStarted = Invoke-RestMethod $qcBulkUrl -Method Post -ContentType 'application/json' -Body $qcStartBody
    if ($qcReturned.changed_count -ne 1 -or $qcStarted.changed_count -ne 1 -or
        @($qcStarted.items)[0].review_state -ne 'in_progress') {
        throw 'Installed QC bulk return/start transitions did not persist.'
    }
    $qcHistory = Invoke-RestMethod $qcEventsUrl
    $qcEventTypes = @($qcHistory.items | ForEach-Object { $_.event_type } | Sort-Object)
    if ($qcHistory.total -ne 5 -or
        ($qcEventTypes -join ',') -ne 'assign,comment,triage_return,triage_skip,triage_start' -or
        $qcHistory.current_assignee -ne 'disposable-reviewer-two') {
        throw 'Installed QC audit history or reviewer assignment is inconsistent.'
    }
    $qcAnnotations = Invoke-RestMethod "$api/images/$imageId/annotations"
    if (@($qcAnnotations.annotations | Where-Object { $_.id -eq $annotationId }).Count -ne 1) {
        throw 'QC triage modified the original researcher annotation.'
    }

    # 1.6 Workflow Builder installed-package acceptance. The standalone QC API
    # above is not evidence that saved typed graphs actually execute in the MSI.
    # This uses the same project and a separate queue; it never approves a
    # machine prediction or changes the original annotation.
    $qcWorkflowGraph = @{
        graph_id = "qc-review-queue-installed-$Token"
        name = 'Installed QC review queue'
        nodes = @(
            @{ node_id = 'project'; node_type = 'project_source' },
            @{ node_id = 'qc'; node_type = 'qc_review_queue' }
        )
        edges = @(
            @{
                edge_id = 'project-qc'
                source_node_id = 'project'
                source_port_id = 'project'
                target_node_id = 'qc'
                target_port_id = 'project'
            }
        )
    }
    $qcWorkflowPlan = Invoke-RestMethod "$api/projects/$projectId/workflow-graphs/plan" -Method Post -ContentType 'application/json' -Body ($qcWorkflowGraph | ConvertTo-Json -Depth 12)
    if (-not $qcWorkflowPlan.valid -or -not $qcWorkflowPlan.executable) {
        throw 'Installed Workflow Builder did not accept the typed project -> QC review graph.'
    }
    $qcWorkflowSaved = Invoke-RestMethod "$api/projects/$projectId/workflow-graphs" -Method Post -ContentType 'application/json' -Body (@{ graph = $qcWorkflowGraph } | ConvertTo-Json -Depth 12)
    $qcWorkflowQueued = Invoke-RestMethod "$api/projects/$projectId/workflow-runs" -Method Post -ContentType 'application/json' -Body (@{ graph_record_id = $qcWorkflowSaved.id } | ConvertTo-Json)
    if (-not $qcWorkflowQueued.id -or -not $qcWorkflowQueued.job_id) {
        throw 'Installed Workflow Builder did not persist a queued QC graph run.'
    }
    $qcWorkflowDeadline = [DateTime]::UtcNow.AddSeconds(120)
    do {
        Start-Sleep -Milliseconds 500
        $qcWorkflowJob = Invoke-RestMethod "$api/jobs/$($qcWorkflowQueued.job_id)"
    } while ($qcWorkflowJob.status -in @('queued', 'running') -and [DateTime]::UtcNow -lt $qcWorkflowDeadline)
    if ($qcWorkflowJob.status -ne 'succeeded') {
        throw "Installed QC Workflow Builder job failed or timed out: $($qcWorkflowJob.status); $($qcWorkflowJob.error_message)"
    }
    $qcWorkflowDetail = Invoke-RestMethod "$api/workflow-runs/$($qcWorkflowQueued.id)"
    $qcWorkflowArtifacts = @($qcWorkflowDetail.artifacts | Where-Object { $_.data_type -eq 'review_queue_reference' })
    $qcWorkflowNodes = @($qcWorkflowDetail.nodes | Where-Object { $_.node_type -eq 'qc_review_queue' })
    if ($qcWorkflowDetail.run.status -ne 'succeeded' -or $qcWorkflowArtifacts.Count -ne 1 -or
        $qcWorkflowNodes.Count -ne 1 -or $qcWorkflowNodes[0].status -ne 'succeeded' -or
        ([string]$qcWorkflowArtifacts[0].payload_sha256).Length -ne 64) {
        throw 'Installed saved QC workflow did not persist a successful typed node and hashed output.'
    }
    $qcWorkflowPayload = $qcWorkflowArtifacts[0].payload_json
    $qcWorkflowQueue = Invoke-RestMethod "$api/review-queues/$($qcWorkflowPayload.queue_id)"
    if ($qcWorkflowPayload.project_id -ne $projectId -or
        $qcWorkflowPayload.workflow_run_id -ne $qcWorkflowQueued.id -or
        $qcWorkflowPayload.review_status -ne 'requires_researcher_review' -or
        $qcWorkflowPayload.priority_score_unit -ne 'dimensionless' -or
        $qcWorkflowQueue.project_id -ne $projectId -or
        $qcWorkflowQueue.created_by -notlike 'workflow:*' -or
        $qcWorkflowQueue.item_count -lt 1 -or
        ([string]$qcWorkflowPayload.input_checksums.scoring_provenance_sha256).Length -ne 64 -or
        ([string]$qcWorkflowPayload.input_checksums.item_evidence_sha256).Length -ne 64) {
        throw 'Installed QC Workflow Builder lost project scope, scientific evidence or researcher-review gating.'
    }
    $qcWorkflowArtifactSha = [string]$qcWorkflowArtifacts[0].payload_sha256

    # A second packaged-desktop restart proves QC coordination survives SQLite
    # closure/reopen; the prior test already covered ordinary image persistence.
    Stop-AcceptanceDesktop $desktop
    $desktop = Start-AcceptanceDesktop
    $port = Wait-BackendPort -Path (Join-Path $DataRoot 'runtime\backend-port.txt') -DesktopProcess $desktop -BackendLogPath (Join-Path $DataRoot 'logs\backend.log')
    $api = "http://127.0.0.1:$port/api/v1"
    Wait-BackendApiReady -ApiBaseUrl $api -DesktopProcess $desktop -BackendLogPath (Join-Path $DataRoot 'logs\backend.log')
    $qcPersistedQueue = Invoke-RestMethod "$api/review-queues/$($qcQueue.id)"
    $qcPersistedItems = Invoke-RestMethod "$api/review-queues/$($qcQueue.id)/items"
    $qcPersistedEvents = Invoke-RestMethod "$api/review-queues/$($qcQueue.id)/items/$qcItemId/events"
    $qcPersistedItem = @($qcPersistedItems.items | Where-Object { $_.id -eq $qcItemId })
    if ($qcPersistedQueue.project_id -ne $projectId -or $qcPersistedItem.Count -ne 1 -or
        $qcPersistedItem[0].review_state -ne 'in_progress' -or
        $qcPersistedEvents.total -ne 5 -or
        $qcPersistedEvents.current_assignee -ne 'disposable-reviewer-two') {
        throw 'QC queue, bulk triage, audit events or reviewer assignment did not survive desktop restart.'
    }
    $qcPersistedAnnotations = Invoke-RestMethod "$api/images/$imageId/annotations"
    if (@($qcPersistedAnnotations.annotations | Where-Object { $_.id -eq $annotationId }).Count -ne 1) {
        throw 'Packaged QC review changed the researcher annotation across restart.'
    }
    $report.qc_review_coordination = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Installed API: scoped queue, idempotent comment and bulk skip, assignment, return/start, five durable audit events and unchanged annotation across desktop restart.'

    # Verify saved graph, executed typed artifact, provenance digest and queue
    # survive a full installed-desktop restart, not merely the in-process job.
    $qcPersistedGraphs = @(Invoke-RestMethod "$api/projects/$projectId/workflow-graphs" | Where-Object { $_.id -eq $qcWorkflowSaved.id })
    $qcPersistedWorkflow = Invoke-RestMethod "$api/workflow-runs/$($qcWorkflowQueued.id)"
    $qcPersistedWorkflowArtifacts = @($qcPersistedWorkflow.artifacts | Where-Object { $_.data_type -eq 'review_queue_reference' })
    $qcPersistedWorkflowQueue = Invoke-RestMethod "$api/review-queues/$($qcWorkflowPayload.queue_id)"
    if ($qcPersistedGraphs.Count -ne 1 -or
        $qcPersistedWorkflow.run.status -ne 'succeeded' -or
        $qcPersistedWorkflowArtifacts.Count -ne 1 -or
        $qcPersistedWorkflowArtifacts[0].payload_sha256 -ne $qcWorkflowArtifactSha -or
        $qcPersistedWorkflowArtifacts[0].payload_json.queue_id -ne $qcWorkflowPayload.queue_id -or
        $qcPersistedWorkflowArtifacts[0].payload_json.review_status -ne 'requires_researcher_review' -or
        $qcPersistedWorkflowQueue.project_id -ne $projectId -or
        $qcPersistedWorkflowQueue.item_count -ne $qcWorkflowQueue.item_count) {
        throw 'Installed saved QC Workflow Builder graph, typed artifact, or review queue changed across restart.'
    }
    $report.qc_workflow_persistence = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Installed saved typed project -> QC graph, background execution, dimensionless scored queue and SHA-256 provenance persisted across restart; run $($qcWorkflowQueued.id), human review required."

    # Re-execute the persisted graph from a new installed-desktop process.
    # This is a new scientific run (never an implicit retry/approval of the
    # original queue); unchanged source evidence must yield the same scoring
    # digests, while run and queue identities remain distinct.
    $qcReplayQueued = Invoke-RestMethod "$api/projects/$projectId/workflow-runs" -Method Post -ContentType 'application/json' -Body (@{ graph_record_id = $qcWorkflowSaved.id } | ConvertTo-Json)
    if (-not $qcReplayQueued.id -or -not $qcReplayQueued.job_id -or
        $qcReplayQueued.id -eq $qcWorkflowQueued.id) {
        throw 'Installed saved QC workflow replay did not create a distinct persisted run.'
    }
    $qcReplayDeadline = [DateTime]::UtcNow.AddSeconds(120)
    do {
        Start-Sleep -Milliseconds 500
        $qcReplayJob = Invoke-RestMethod "$api/jobs/$($qcReplayQueued.job_id)"
    } while ($qcReplayJob.status -in @('queued', 'running') -and [DateTime]::UtcNow -lt $qcReplayDeadline)
    if ($qcReplayJob.status -ne 'succeeded') {
        throw "Installed saved QC workflow replay failed or timed out: $($qcReplayJob.status); $($qcReplayJob.error_message)"
    }
    $qcReplayDetail = Invoke-RestMethod "$api/workflow-runs/$($qcReplayQueued.id)"
    $qcReplayArtifacts = @($qcReplayDetail.artifacts | Where-Object { $_.data_type -eq 'review_queue_reference' })
    if ($qcReplayDetail.run.status -ne 'succeeded' -or $qcReplayArtifacts.Count -ne 1) {
        throw 'Installed saved QC workflow replay did not persist exactly one typed queue artifact.'
    }
    $qcReplayPayload = $qcReplayArtifacts[0].payload_json
    if ($qcReplayPayload.workflow_run_id -ne $qcReplayQueued.id -or
        $qcReplayPayload.project_id -ne $projectId -or
        $qcReplayPayload.queue_id -eq $qcWorkflowPayload.queue_id -or
        $qcReplayPayload.review_status -ne 'requires_researcher_review' -or
        $qcReplayPayload.priority_score_unit -ne 'dimensionless' -or
        $qcReplayPayload.item_count -ne $qcWorkflowPayload.item_count -or
        $qcReplayPayload.input_checksums.queue_scope_sha256 -ne $qcWorkflowPayload.input_checksums.queue_scope_sha256 -or
        $qcReplayPayload.input_checksums.item_evidence_sha256 -ne $qcWorkflowPayload.input_checksums.item_evidence_sha256 -or
        $qcReplayPayload.input_checksums.scoring_provenance_sha256 -ne $qcWorkflowPayload.input_checksums.scoring_provenance_sha256) {
        throw 'Installed saved QC replay changed source evidence, scoring provenance, or researcher approval gate.'
    }
    $qcReplayQueue = Invoke-RestMethod "$api/review-queues/$($qcReplayPayload.queue_id)"
    $qcReplayItems = Invoke-RestMethod "$api/review-queues/$($qcReplayPayload.queue_id)/items"
    $qcOriginalAfterReplay = Invoke-RestMethod "$api/review-queues/$($qcWorkflowPayload.queue_id)"
    $qcReviewEventsAfterReplay = Invoke-RestMethod "$api/review-queues/$($qcQueue.id)/items/$qcItemId/events"
    if ($qcReplayQueue.project_id -ne $projectId -or
        $qcReplayQueue.created_by -notlike 'workflow:*' -or
        $qcReplayQueue.item_count -ne @($qcReplayItems.items).Count -or
        $qcOriginalAfterReplay.item_count -ne $qcWorkflowQueue.item_count -or
        $qcReviewEventsAfterReplay.total -ne 5) {
        throw 'Installed saved QC replay changed the original queue, manual audit history, or project scope.'
    }
    $report.qc_workflow_replay = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Installed saved graph re-executed after restart as distinct run $($qcReplayQueued.id), preserving immutable QC evidence digests, review gate, and original reviewer audit."




    $exchange = Invoke-RestMethod "$api/projects/$projectId/exchange-packages" -Method Post -ContentType 'application/json' -Body (@{include_media=$true;include_model_weights=$false;include_generated_artifacts=$true;notes='clean install acceptance'} | ConvertTo-Json)
    $jobId = $exchange.job_id
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    do { Start-Sleep -Milliseconds 500; $job = Invoke-RestMethod "$api/jobs/$jobId" } while ($job.status -in @('queued','running') -and [DateTime]::UtcNow -lt $deadline)
    if ($job.status -ne 'succeeded') { throw "Project Exchange export job ended as $($job.status)." }
    $archive = Join-Path $EvidenceRoot 'project-exchange.reefvision.zip'
    Invoke-WebRequest "$api/exchange-packages/$($exchange.package.id)/download" -OutFile $archive
    if ((Get-Item $archive).Length -le 0) { throw 'Project Exchange archive is empty.' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($archive); try { if (-not ($zip.Entries | Where-Object FullName -eq 'reefvision-exchange-manifest.json')) { throw 'Project Exchange archive has no reefvision-exchange-manifest.json.' } } finally { $zip.Dispose() }
    $report.project_exchange = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Exported inspectable archive: $archive"
    Stop-AcceptanceDesktop $desktop

    if (-not $SkipUninstall) {
        $installer = New-Object -ComObject WindowsInstaller.Installer
        $database = $installer.OpenDatabase($InstallerPath, 0); $view = $database.OpenView("SELECT `Value` FROM `Property` WHERE `Property`='ProductCode'"); $view.Execute(); $productCode = $view.Fetch().StringData(1)
        Run-Msi -Action Uninstall -PackageOrProduct $productCode -LogName 'uninstall.log' | Out-Null
        if (Test-Path (Join-Path $InstallRoot 'ReefVision.exe')) { throw 'ReefVision.exe remains after uninstall.' }
        if (@($shortcutCandidates | Where-Object { Test-Path -LiteralPath $_ }).Count -gt 0) { throw 'A ReefVision shortcut remains after uninstall.' }
        if (@(Get-ReefVisionInstalledRegistrations).Count -gt 0) { throw 'ReefVision uninstall registration remains after uninstall.' }
        $report.uninstall = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Program binaries removed.'
        if (-not (Test-Path $DataRoot)) { throw 'Isolated user data was removed by uninstall.' }
        $report.data_retention = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Isolated project data remained after uninstall.'
    } else {
        $report.data_retention = New-ReefVisionEvidenceResult -Status 'NOT RUN' -Detail 'Uninstall was skipped.'
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
    foreach ($logName in @('backend.log', 'api.log', 'api.log.1', 'api.log.2')) {
        $sourceLog = Join-Path (Join-Path $DataRoot 'logs') $logName
        if (Test-Path -LiteralPath $sourceLog -PathType Leaf) {
            try {
                $evidenceName = "$logName.tail.log"
                Get-Content -LiteralPath $sourceLog -Tail 500 -ErrorAction Stop |
                    Set-Content -LiteralPath (Join-Path $EvidenceRoot $evidenceName) -Encoding utf8 -ErrorAction Stop
            } catch {
                Write-Warning "Could not archive $logName tail: $($_.Exception.Message)"
            }
        }
    }
    $report.completed_at_utc = [DateTime]::UtcNow.ToString('o')
    Save-Report
    if (-not $KeepArtifacts -and (Test-Path (Join-Path $RunRoot '.reefvision-acceptance-run')) -and $report.uninstall.status -eq 'PASS') {
        $ExpectedRunRoot = [System.IO.Path]::GetFullPath((Join-Path $AcceptanceRoot "reefvision-clean-$Token"))
        if ([System.IO.Path]::GetFullPath($RunRoot) -ne $ExpectedRunRoot) { throw 'Refusing cleanup outside the generated acceptance run.' }
        [void](Assert-ReefVisionAcceptanceTreeNoReparsePoints -Path $RunRoot)
        Remove-Item -LiteralPath $RunRoot -Recurse -Force
    }
}

Write-Host 'ReefVision clean Windows acceptance passed.' -ForegroundColor Green
Write-Host "Evidence report: $ReportPath"
