$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'lib\windows-clean-acceptance.ps1')

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
$acceptanceScript = Get-Content -LiteralPath $acceptancePath -Raw
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
Assert-True (($acceptanceScript -split 'Assert-ReefVisionCameraRaster').Count -eq 3) 'Camera acceptance must decode and validate both original and display rasters.'
Assert-True ($acceptanceScript.Contains('source SHA256 $cameraHashBefore unchanged')) 'Camera acceptance must record source integrity evidence.'

Assert-True ($acceptanceScript.Contains('function Import-AcceptanceAnnotations')) 'Windows acceptance must use a real multipart annotation import.'
Assert-True ($acceptanceScript.Contains('cocoResult.boxes_imported -ne 1')) 'COCO imported box acceptance is missing.'
Assert-True ($acceptanceScript.Contains('yoloResult.boxes_imported -ne 1')) 'YOLO imported box acceptance is missing.'
Assert-True ($acceptanceScript.Contains('LiveSam2Acceptance')) 'Live SAM mode must be declared.'
Assert-True ($acceptanceScript.Contains("HF_HUB_OFFLINE'] = '0'")) 'Opt-in live SAM must allow a real network download.'
Assert-True ($acceptanceScript.Contains('samAcceptedMaskId')) 'Live SAM acceptance must validate mask preservation.'
Assert-True ($acceptanceScript.Contains("'api.log', 'api.log.1'")) 'Failed SAM2 acceptance must archive API logs, not only startup backend.log.'
Assert-True ($acceptanceScript.Contains('api.log.tail.log') -or $acceptanceScript.Contains('$logName.tail.log')) 'SAM2 API log archive name must match the uploaded *.log evidence pattern.'
Assert-True ($acceptanceScript.Contains('$expectedInitialVersion')) 'Acceptance must verify which MSI version launched before upgrade.'
Assert-True ($acceptanceScript.Contains('$postUpgradeVersion')) 'Acceptance must read the packaged API version after upgrade.'
Assert-True ($acceptanceScript.Contains('Post-upgrade API version')) 'Upgrade must fail when the packaged API version did not change to the candidate.'
Assert-True ($acceptanceScript -match 'Stop-AcceptanceDesktop\s+\$desktop\s*\r?\n\s*\$projectChecksum\s*=\s*\(Get-FileHash\s+-LiteralPath\s+\(Join-Path\s+\$DataRoot\s+''reefvision\.db''\)') 'Desktop shutdown must occur before hashing reefvision.db.'
Assert-True ($acceptanceScript -match 'Where-Object\s+FullName\s+-eq\s+''reefvision-exchange-manifest\.json''') 'Project Exchange validation does not require the canonical manifest name.'
Assert-True ($acceptanceScript -notmatch 'Where-Object\s+FullName\s+-eq\s+''manifest\.json''') 'Project Exchange validation still accepts the incorrect manifest.json name.'

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
