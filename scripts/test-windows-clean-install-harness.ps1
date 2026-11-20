$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'lib\windows-clean-acceptance.ps1')
. (Join-Path $PSScriptRoot 'lib\windows-spatial-webview2-acceptance.ps1')

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

$journeyFailure = Get-ReefVisionInstalledJourneyEvidence { throw 'Fixture WebView2 attach timeout.' }
Assert-True ($journeyFailure.status -eq 'FAIL') 'A failed installed journey must remain failed while the independent MSI lifecycle checks run.'
Assert-True ($journeyFailure.detail -eq 'Fixture WebView2 attach timeout.') 'The retained journey failure must identify the original error.'
$journeySuccess = Get-ReefVisionInstalledJourneyEvidence {
    [pscustomobject]@{
        completed_journeys = 9; graph_record_id = 'graph-id'; first_run_id = 'first'; replay_run_id = 'second'
        artifact = [pscustomobject]@{ payload_sha256 = 'comparison-digest' }
        ordinary_detector = [pscustomobject]@{ model_id = 'detector-id'; checkpoint_sha256 = 'checkpoint-digest' }
    }
}
Assert-True ($journeySuccess.status -eq 'PASS' -and $journeySuccess.detail.Contains('comparison-digest') -and $journeySuccess.detail.Contains('checkpoint-digest')) 'Successful journeys must retain the spatial export and the trained detector identities.'

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
        Set-Variable -Name $StatusCodeVariable -Value 200 -Scope 1
        [pscustomobject]@{ webSocketDebuggerUrl = $script:debugFixtureEndpoint }
    }
    try {
        $script:debugFixtureEndpoint = 'ws://127.0.0.1:39513/devtools/browser/abcdef-1234'
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
        Remove-Variable -Name debugFixtureEndpoint -Scope Script -ErrorAction SilentlyContinue
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
