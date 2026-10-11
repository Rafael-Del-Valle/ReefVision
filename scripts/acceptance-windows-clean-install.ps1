param(
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [Parameter(Mandatory = $true)][string]$AcceptanceRoot,
    [string]$PreviousInstallerPath = '',
    [switch]$PreviousInstallerSupportsIsolatedAcceptance,
    [switch]$DisposableTest,
    [switch]$PlanOnly,
    [switch]$KeepArtifacts,
    [switch]$SkipUpgrade,
    [switch]$SkipUninstall
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
$Version = (New-Object -ComObject WindowsInstaller.Installer).OpenDatabase($InstallerPath, 0).OpenView("SELECT `Value` FROM `Property` WHERE `Property`='ProductVersion'")
$Version.Execute(); $VersionRecord = $Version.Fetch(); $ProductVersion = $VersionRecord.StringData(1)

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
    return Invoke-ReefVisionIsolatedEnvironment -DataRoot $DataRoot -AdditionalEnvironment @{
        REEFVISION_WINDOWS_ACCEPTANCE = '1'
        REEFVISION_ACCEPTANCE_DATA_DIR = $DataRoot
    } -Action {
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
function Import-AcceptanceImage([string]$Url) {
    Add-Type -AssemblyName System.Net.Http
    $png = [Convert]::FromBase64String('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
    $client = New-Object System.Net.Http.HttpClient
    $form = New-Object System.Net.Http.MultipartFormDataContent
    try {
        $file = New-Object System.Net.Http.ByteArrayContent -ArgumentList (,$png)
        $file.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse('image/png')
        $form.Add($file, 'files', 'acceptance.png')
        $form.Add((New-Object System.Net.Http.StringContent('synthetic/acceptance.png')), 'relative_paths')
        $response = $client.PostAsync($Url, $form).GetAwaiter().GetResult()
        $payload = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) { throw "Image import failed with HTTP $([int]$response.StatusCode): $payload" }
        return $payload | ConvertFrom-Json
    } finally { $form.Dispose(); $client.Dispose() }
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
    Stop-AcceptanceDesktop $desktop
    $projectChecksum = (Get-FileHash -LiteralPath (Join-Path $DataRoot 'reefvision.db') -Algorithm SHA256).Hash

    if ($PreviousInstallerPath -and -not $SkipUpgrade) {
        Run-Msi -Action Install -PackageOrProduct $InstallerPath -LogName 'upgrade.log' -TargetRoot $InstallRoot | Out-Null
        $report.upgrade = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Previous installer upgraded to current installer.'
    }

    $desktop = Start-AcceptanceDesktop
    $port = Wait-BackendPort -Path (Join-Path $DataRoot 'runtime\backend-port.txt') -DesktopProcess $desktop -BackendLogPath (Join-Path $DataRoot 'logs\backend.log')
    $api = "http://127.0.0.1:$port/api/v1"
    $persisted = Invoke-RestMethod "$api/projects/$projectId"
    if ($persisted.id -ne $projectId) { throw 'Project ID changed across restart.' }
    $persistedAnnotations = Invoke-RestMethod "$api/images/$imageId/annotations"
    if (-not ($persistedAnnotations.annotations | Where-Object id -eq $annotationId)) { throw 'Acceptance annotation did not persist across restart.' }
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
