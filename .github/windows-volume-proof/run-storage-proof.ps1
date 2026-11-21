param(
    [Parameter(Mandatory)][string]$RepositoryRoot,
    [Parameter(Mandatory)][string]$ProofRoot,
    [Parameter(Mandatory)][string]$NodePath,
    [Parameter(Mandatory)][string]$PythonPath
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'volume.ps1')
Assert-ReefVisionQuotaHosted

$source = '96476bc462aeed0137a55b02ded6d66b1d4a2c72'
$version = '1.9.0'
$revision = 'b19_registration_0001'
$repo = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$proof = (Resolve-Path -LiteralPath $ProofRoot).Path
$expected = [IO.Path]::GetFullPath("${env:SystemDrive}/rv-storage-proof-$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT")
if ($proof -ine $expected -or (git -C $repo rev-parse HEAD).Trim() -cne $source -or
    @(git -C $repo status --porcelain --untracked-files=no).Count) {
    throw 'Storage proof must bind the job-owned staging root to the clean exact product source.'
}
$node = (Resolve-Path -LiteralPath $NodePath).Path
$python = (Resolve-Path -LiteralPath $PythonPath).Path
$evidence = Join-Path $proof 'evidence'
$receipt = Get-Content -LiteralPath (Join-Path $evidence 'verified-transport.json') -Raw | ConvertFrom-Json
$msi = Join-Path $proof 'payload/ReefVision_1.9.0_x64_en-US.msi'
function Get-ProofHash([string]$Path) {
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
if ($receipt.source_commit -cne $source -or $receipt.build_run_id -ne 44867493658 -or
    $receipt.build_job_id -ne 136734331397 -or (Get-ProofHash $msi) -cne $receipt.original_msi_sha256) {
    throw 'The staging receipt is unrelated to the exact authorized original MSI.'
}
. (Join-Path $repo 'scripts/lib/windows-clean-acceptance.ps1')
. (Join-Path $repo 'scripts/lib/windows-spatial-webview2-acceptance.ps1')
. (Join-Path $repo 'scripts/lib/windows-scheduler-webview2-acceptance.ps1')
if (-not (Test-ReefVisionAdministrator) -or @(Get-ReefVisionInstalledRegistrations).Count) {
    throw 'The original MSI proof requires a fresh administrator-controlled runner with no existing ReefVision registration.'
}
Assert-ReefVisionNoReparseAncestors $proof
$run = Join-Path $proof 'storage-run'
if (Test-Path -LiteralPath $run) { throw 'The owned experiment root must be fresh.' }
New-Item -ItemType Directory -Path $run | Out-Null
$nonce = [guid]::NewGuid().ToString()
Set-Content -LiteralPath (Join-Path $run '.reefvision-acceptance-run') -Value $nonce
$phaseRoot = Join-Path $run 'signals'
New-Item -ItemType Directory -Path $phaseRoot | Out-Null

# Start the exact prereviewed standard-user launcher. Its only QA adaptation is
# requiring the data profile to be under the independently verified volume root.
$libraryDirectory = Join-Path $run 'launcher-library'
New-Item -ItemType Directory -Path $libraryDirectory | Out-Null
$originalLibrary = Join-Path $repo 'scripts/lib/windows-standard-user-webview2.ps1'
$quotaLibrary = Join-Path $libraryDirectory 'windows-standard-user-webview2.ps1'
$trusted = Get-Content -LiteralPath $originalLibrary -Raw
$guard = '-not (Test-ReefVisionPathWithin -Path $Profile -Parent $Account.run_root)'
if ([regex]::Matches($trusted,[regex]::Escape($guard)).Count -ne 1) { throw 'The stock profile guard has changed.' }
$trusted.Replace($guard, '-not (Test-ReefVisionPathWithin -Path $Profile -Parent $Account.quota_root)') |
    Set-Content -LiteralPath $quotaLibrary -Encoding utf8
Copy-Item -LiteralPath (Join-Path $repo 'scripts/lib/windows-clean-acceptance.ps1') -Destination $libraryDirectory
. $quotaLibrary

$install = Join-Path $run 'install'
$exe = Join-Path $install 'ReefVision.exe'
$sidecar = Join-Path $install 'backend/reefvision-api/reefvision-api.exe'
$script:installed = $false
function Invoke-ProofMsi([ValidateSet('Install','Uninstall')][string]$Action) {
    $logPath = Join-Path $evidence "$Action-msi.log"
    $arguments = New-ReefVisionMsiArguments -Action $Action -PackageOrProduct $msi -InstallRoot $install -LogPath $logPath
    $process = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32/msiexec.exe') -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -notin 0,3010,1641) { throw "Original MSI $Action exited $($process.ExitCode)." }
    if ($Action -eq 'Install') { $script:installed = $true } else { $script:installed = $false }
    return $process.ExitCode
}
function Complete-Signal([string]$Name,$Value) {
    $destination = Join-Path $phaseRoot "$Name.ready.json"
    $temp = "$destination.tmp"
    $Value['token'] = $nonce
    $Value | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temp -Encoding utf8
    Move-Item -LiteralPath $temp -Destination $destination
}
function Test-RequestedSignal([string]$Name) {
    $path = Join-Path $phaseRoot "$Name.request.json"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
    $requested = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    if ($requested.token -cne $nonce -or $requested.phase -cne $Name) { throw 'Invalid capacity trial signal.' }
    return $true
}

$owned = $null
$account = $null
$driver = $null
$backend = $null
$debug = $null
$profile = $null
$phaseResult = $null
$dbAfter = Join-Path $evidence 'closed-database.json'
$passed = $false
try {
    $installCode = Invoke-ProofMsi Install
    $registrations = @(Get-ReefVisionInstalledRegistrations)
    if ($registrations.Count -ne 1 -or -not (Test-Path -LiteralPath $exe -PathType Leaf) -or
        -not (Test-Path -LiteralPath $sidecar -PathType Leaf)) { throw 'Original MSI did not register its expected binaries.' }
    $owned = New-ReefVisionQuotaVolume $proof $evidence
    $profile = Join-Path $owned.Root 'data'
    New-Item -ItemType Directory -Path $profile | Out-Null
    Set-Content -LiteralPath (Join-Path $profile '.reefvision-clean-install-acceptance') -Value $nonce
    $account = New-ReefVisionHostedGuiAccount -RunRoot $run
    Add-Member -InputObject $account -NotePropertyName quota_root -NotePropertyValue $owned.Root
    $debug = Get-ReefVisionLoopbackDebugPort
    $app = Start-ReefVisionHostedGui -Account $account -Executable $exe -Profile $profile -DebugPort $debug -EvidenceRoot $evidence -LaunchLabel 'storage'
    $portFile = Join-Path $profile 'runtime/backend-port.txt'
    $deadline = [datetimeoffset]::UtcNow.AddSeconds(120)
    do {
        if (Test-Path -LiteralPath $portFile) {
            $portText = (Get-Content -LiteralPath $portFile -Raw).Trim()
            if ($portText -match '^[0-9]{1,5}$') { break }
        }
        $app.Refresh()
        if ($app.HasExited -or [datetimeoffset]::UtcNow -ge $deadline) { throw 'The exact installed backend did not publish an isolated port.' }
        Start-Sleep -Milliseconds 100
    } while ($true)
    $port = [int]$portText
    $endpoint = Wait-ReefVisionWebView2DebugEndpoint -Port $debug -DesktopProcessId $app.Id -ExpectedBrowserSid $account.sid.Value `
        -FailureEvidencePath (Join-Path $evidence 'storage-cdp-failure.json') -AttachmentEvidencePath (Join-Path $evidence 'storage-cdp.json')
    $backend = Get-ReefVisionInstalledScheduleBackend -Port $port -DesktopProcessId $app.Id -BrowserSid $account.sid.Value `
        -BackendExecutable $sidecar -Profile $profile -Version $version -Revision $revision
    $api = "http://127.0.0.1:$port/api/v1"
    $machine = Invoke-RestMethod -Uri "$api/system/compatibility/machine" -TimeoutSec 5 -NoProxy
    if (-not $machine.packaged_backend) { throw 'Expected the frozen packaged sidecar, not a source server.' }
    [ordered]@{
        source=$source; product='1.9.0'; schema=$revision; build_run_id=$receipt.build_run_id; build_job_id=$receipt.build_job_id;
        install_exit_code=$installCode; original_msi_sha256=$receipt.original_msi_sha256; desktop_sha256=(Get-ProofHash $exe);
        backend=$backend; packaged_backend=$machine.packaged_backend; stock_library_sha256=(Get-ProofHash $originalLibrary);
        qa_library_sha256=(Get-ProofHash $quotaLibrary); expected_middle_integrity=8192;
        browser_test_sha256=(Get-ProofHash (Join-Path $PSScriptRoot 'dedicated-volume-recovery-live.spec.ts'))
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $evidence 'original-installed-identity.json')

    $web = Join-Path $repo 'apps/web'
    $qaSpec = Join-Path $web 'tests/e2e/dedicated-volume-recovery-live.spec.ts'
    if (Test-Path -LiteralPath $qaSpec) { throw 'A product test already uses the isolated QA name.' }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'dedicated-volume-recovery-live.spec.ts') -Destination $qaSpec
    $output = Join-Path $evidence 'storage-playwright'
    $pwJson = Join-Path $evidence 'playwright.json'
    $child = [Diagnostics.ProcessStartInfo]::new()
    $child.FileName = $node
    $child.WorkingDirectory = $web
    $child.CreateNoWindow = $true
    $child.UseShellExecute = $false
    $child.RedirectStandardOutput = $true
    $child.RedirectStandardError = $true
    foreach ($arg in @('node_modules/playwright/cli.js','test','tests/e2e/dedicated-volume-recovery-live.spec.ts',
        '--workers=1','--retries=0','--trace=off','--reporter=dot,json',"--output=$output")) {
        $child.ArgumentList.Add($arg)
    }
    $child.Environment['REEFVISION_GUIDED_TEST_API'] = $api
    $child.Environment['REEFVISION_SPATIAL_WEBVIEW2_ENDPOINT'] = $endpoint
    $child.Environment['REEFVISION_SPATIAL_WEBVIEW2_ARTIFACTS_DIR'] = (Resolve-Path -LiteralPath $account.browser_artifacts).Path
    $child.Environment['REEFVISION_STORAGE_PHASE_ROOT'] = $phaseRoot
    $child.Environment['REEFVISION_STORAGE_PROFILE'] = $profile
    $child.Environment['REEFVISION_STORAGE_NONCE'] = $nonce
    $child.Environment['REEFVISION_STORAGE_SOURCE'] = $source
    $child.Environment['REEFVISION_STORAGE_VERSION'] = $version
    $child.Environment['REEFVISION_STORAGE_SCHEMA'] = $revision
    $child.Environment['PLAYWRIGHT_JSON_OUTPUT_FILE'] = $pwJson
    $driver = [Diagnostics.Process]::Start($child)
    $outTask = $driver.StandardOutput.ReadToEndAsync()
    $errTask = $driver.StandardError.ReadToEndAsync()
    $pressure = $null
    $release = $null
    $deadline = [datetimeoffset]::UtcNow.AddMinutes(5)
    while (-not $driver.HasExited -and [datetimeoffset]::UtcNow -lt $deadline) {
        if ($null -eq $pressure -and (Test-RequestedSignal 'fill')) {
            $null = Get-ReefVisionQuotaVolume $owned
            $checkpoint = Join-Path $evidence 'pre-pressure-journal.json'
            & $python (Join-Path $PSScriptRoot 'fixture_db.py') checkpoint $profile $owned.Root $checkpoint
            if ($LASTEXITCODE) { throw 'The prepared SQLite database was not ready for isolated volume pressure.' }
            $pressure = Set-ReefVisionQuotaPressure $owned
            Complete-Signal 'fill' $pressure
        }
        if ($null -ne $pressure -and $null -eq $release -and (Test-RequestedSignal 'release')) {
            $release = Clear-ReefVisionQuotaPressure $owned
            Complete-Signal 'release' $release
        }
        Start-Sleep -Milliseconds 85
    }
    if (-not $driver.HasExited) { throw 'Timed out waiting for the stock desktop storage witness.' }
    $outTask.GetAwaiter().GetResult() | Set-Content -LiteralPath (Join-Path $evidence 'playwright-stdout.log')
    $errTask.GetAwaiter().GetResult() | Set-Content -LiteralPath (Join-Path $evidence 'playwright-stderr.log')
    if ($driver.ExitCode -ne 0 -or $null -eq $pressure -or $null -eq $release) {
        Get-Content -LiteralPath (Join-Path $evidence 'playwright-stdout.log') -Tail 90
        throw 'Real installed storage proof did not complete.'
    }
    $stats = (Get-Content -LiteralPath $pwJson -Raw | ConvertFrom-Json).stats
    $matches = @(Get-ChildItem -LiteralPath $output -Recurse -File -Filter dedicated-volume-recovery.json)
    if ($stats.expected -ne 1 -or $stats.skipped -ne 0 -or $stats.unexpected -ne 0 -or $matches.Count -ne 1) {
        throw 'Expected one non-skipped direct native result.'
    }
    $phaseResult = Get-Content -LiteralPath $matches[0].FullName -Raw | ConvertFrom-Json
    if ($phaseResult.source -cne $source -or $phaseResult.surface -cne 'tauri-webview2' -or
        $phaseResult.failure.code -cne 'storage_full' -or $phaseResult.recovered_revision -ne 2 -or
        $phaseResult.recovered_annotations -ne 192) { throw 'The browser receipt does not bind the genuine capacity recovery.' }
    $passed = $true
} finally {
    $cleanup = [ordered]@{success_before_cleanup=$passed; listener_closed=$false; sidecar_closed=$false; mounted_volume_detached=$false; uninstalled=$false}
    if ($driver -and -not $driver.HasExited) {
        $driver.Kill($true)
        $driver.WaitForExit(15000) | Out-Null
    }
    try {
        if ($account) {
            Remove-ReefVisionHostedGuiAccount $account $evidence 'storage'
        }
        if ($debug) { Wait-ReefVisionWebView2DebugClosure $debug }
        if ($backend) {
            Wait-ReefVisionWebView2DebugClosure $backend.port
            $cleanup.listener_closed = $true
            $cleanup.sidecar_closed = -not (Get-Process -Id $backend.pid -ErrorAction SilentlyContinue)
            if (-not $cleanup.sidecar_closed) { throw 'The owned packaged sidecar survived native closure.' }
        }
        if ($owned) {
            $null = Clear-ReefVisionQuotaPressure $owned
            foreach ($name in @('backend.log','api.log')) {
                $log = Join-Path $profile "logs/$name"
                if (Test-Path -LiteralPath $log -PathType Leaf) { Copy-Item -LiteralPath $log -Destination $evidence }
            }
            if ($passed) {
                & $python (Join-Path $PSScriptRoot 'fixture_db.py') receipt $profile $owned.Root $dbAfter
                if ($LASTEXITCODE) { throw 'Closed stock database does not retain exactly one new annotation revision.' }
                $actual = Get-Content -LiteralPath $dbAfter -Raw | ConvertFrom-Json
                if ($actual.image_id -cne $phaseResult.image_id -or $actual.original_sha256 -cne $phaseResult.original_sha256) {
                    throw 'Independent closed database audit disagrees with the normal editor receipt.'
                }
            }
        }
    } finally {
        try {
            $vhd = Join-Path $proof 'capacity-fixture.vhdx'
            if (Test-Path -LiteralPath $vhd -PathType Leaf) {
                $isAttached = (Get-DiskImage -ImagePath $vhd).Attached
                if ($isAttached) { Dismount-DiskImage -ImagePath $vhd | Out-Null }
                $cleanup.mounted_volume_detached = -not (Get-DiskImage -ImagePath $vhd).Attached
                if (-not $cleanup.mounted_volume_detached) { throw 'The owned bounded VHD remains attached.' }
            }
        } finally {
            if ($script:installed) {
                $null = Invoke-ProofMsi Uninstall
                $cleanup.uninstalled = @(Get-ReefVisionInstalledRegistrations).Count -eq 0
            }
            $cleanup | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $evidence 'cleanup.json')
        }
    }
}
if (-not ($passed -and $cleanup.listener_closed -and $cleanup.sidecar_closed -and
    $cleanup.mounted_volume_detached -and $cleanup.uninstalled)) {
    throw 'Stock storage proof or required cleanup remains incomplete.'
}
