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
    [switch]$LiveSam2Acceptance
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'lib\windows-clean-acceptance.ps1')

if (-not $DisposableTest -and -not $PlanOnly) {
    throw 'Refusing destructive MSI acceptance. Supply -DisposableTest on a disposable Windows VM/machine, or use -PlanOnly.'
}
if ($DisposableTest -and $PlanOnly) { throw '-DisposableTest and -PlanOnly are mutually exclusive.' }

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

function Get-MsiProductVersion([string]$Path) {
    $database = (New-Object -ComObject WindowsInstaller.Installer).OpenDatabase($Path, 0)
    $view = $database.OpenView("SELECT `Value` FROM `Property` WHERE `Property`='ProductVersion'")
    try {
        [void]$view.Execute()
        $record = $view.Fetch()
        if ($null -eq $record) { throw "MSI does not declare ProductVersion: $Path" }
        return ConvertTo-ReefVisionVersionString ([string]$record.StringData(1))
    }
    finally {
        [void]$view.Close()
    }
}

$ProductVersion = Get-MsiProductVersion -Path $InstallerPath
$PreviousProductVersion = if ($PreviousInstallerPath) { Get-MsiProductVersion -Path $PreviousInstallerPath } else { $null }

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
    model_policy = New-ReefVisionEvidenceResult
    sam2_live = if ($LiveSam2Acceptance) { New-ReefVisionEvidenceResult } else { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'Real SAM 2.1 packaged runtime acceptance not requested' }
    external_annotation_imports = New-ReefVisionEvidenceResult
    confidence_review = if ($LiveSam2Acceptance) { New-ReefVisionEvidenceResult } else { New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'Real pending prediction review not requested' }
    project_persistence = New-ReefVisionEvidenceResult
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
    $versionPayload = Invoke-RestMethod "$api/system/version"
    $expectedInitialVersion = if ($PreviousInstallerPath -and -not $SkipUpgrade) { $PreviousProductVersion } else { $ProductVersion }
    $actualInitialVersion = ConvertTo-ReefVisionVersionString ([string]$versionPayload.application_version)
    if ($actualInitialVersion -ne $expectedInitialVersion) {
        throw "Initial packaged API version $actualInitialVersion does not match installed MSI version $expectedInitialVersion."
    }
    $migrationPayload = Invoke-RestMethod "$api/system/migrations/status"
    $report.first_launch = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Desktop and packaged backend started; database initialized; API version $($versionPayload.application_version)"
    $report.frontend_backend_connectivity = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Desktop-published loopback API responded; migration status: $($migrationPayload.schema_status)"

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
    if ($PreviousInstallerPath -and -not $SkipUpgrade) {
        $postUpgradeVersion = Invoke-RestMethod "$api/system/version"
        $actualPostUpgradeVersion = ConvertTo-ReefVisionVersionString ([string]$postUpgradeVersion.application_version)
        if ($actualPostUpgradeVersion -ne $ProductVersion) {
            throw "Post-upgrade API version $actualPostUpgradeVersion does not match candidate MSI version $ProductVersion."
        }
        $report.upgrade = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Upgraded packaged API from $PreviousProductVersion to $ProductVersion."
    }
    $persisted = Invoke-RestMethod "$api/projects/$projectId"
    if ($persisted.id -ne $projectId) { throw 'Project ID changed across restart.' }
    $persistedAnnotations = Invoke-RestMethod "$api/images/$imageId/annotations"
    if (-not ($persistedAnnotations.annotations | Where-Object id -eq $annotationId)) { throw 'Acceptance annotation did not persist across restart.' }
    if ($LiveSam2Acceptance) {
        $persistedSamSession = Invoke-RestMethod "$api/images/$samImageId/annotations"
        if (-not ($persistedSamSession.mask_annotations | Where-Object id -eq $samAcceptedMaskId)) {
            throw 'Accepted SAM 2.1 mask did not persist across packaged Windows desktop restart.'
        }
    }
    $report.restart = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Desktop and backend restarted cleanly.'
    $report.project_persistence = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Project $projectId, image $imageId, and annotation $annotationId persisted; pre-restart database SHA-256 $projectChecksum"

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
        Remove-Item -LiteralPath $RunRoot -Recurse -Force
    }
}

Write-Host 'ReefVision clean Windows acceptance passed.' -ForegroundColor Green
Write-Host "Evidence report: $ReportPath"
