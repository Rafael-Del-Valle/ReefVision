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
function Assert-ThrowsContaining([scriptblock]$Action, [string]$ExpectedText) {
    $failure = $null
    try { & $Action | Out-Null } catch { $failure = $_.Exception.Message }
    if ($null -eq $failure -or -not $failure.Contains($ExpectedText)) {
        throw "Expected failure containing '$ExpectedText'; received '$failure'"
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

# A junction that looks like a disposable directory must not redirect MSI
# installation or later recursive cleanup into an unrelated research tree.
$fixtureRoot = Join-Path $env:TEMP ('rv-acceptance-link-test-' + [guid]::NewGuid().ToString('N'))
$externalRoot = Join-Path $fixtureRoot 'external'
$unrelatedRoot = Join-Path $fixtureRoot 'unrelated'
$linkedRoot = Join-Path $fixtureRoot 'linked'
$nestedLink = Join-Path $externalRoot 'nested-link'
$externalSentinel = Join-Path $externalRoot 'preserve.txt'
try {
    New-Item -ItemType Directory -Path $externalRoot,$unrelatedRoot -Force | Out-Null
    Set-Content -LiteralPath $externalSentinel -Value 'research assets stay untouched'
    $originalHash = (Get-FileHash -LiteralPath $externalSentinel -Algorithm SHA256).Hash
    Assert-True ((Assert-ReefVisionAcceptanceTreeNoReparsePoints -Path $externalRoot) -eq $true) 'Normal disposable cleanup tree was rejected.'
    Assert-True ((Assert-ReefVisionSafeAcceptanceRoot -Path (Join-Path $externalRoot 'new-run') -RepositoryRoot $Root -DefaultDataRoot $defaultData) -eq (Resolve-ReefVisionAcceptancePath (Join-Path $externalRoot 'new-run'))) 'Normal nested acceptance root was rejected.'
    New-Item -ItemType Junction -Path $linkedRoot -Target $externalRoot | Out-Null
    Assert-ThrowsContaining {
        Assert-ReefVisionSafeAcceptanceRoot -Path $linkedRoot -RepositoryRoot $Root -DefaultDataRoot $defaultData
    } 'symlink/junction'
    Assert-ThrowsContaining {
        Assert-ReefVisionSafeAcceptanceRoot -Path (Join-Path $linkedRoot 'new-run') -RepositoryRoot $Root -DefaultDataRoot $defaultData
    } 'symlink/junction'
    New-Item -ItemType Junction -Path $nestedLink -Target $unrelatedRoot | Out-Null
    Assert-ThrowsContaining {
        Assert-ReefVisionAcceptanceTreeNoReparsePoints -Path $externalRoot
    } 'symlink/junction'
    Assert-True ((Get-FileHash -LiteralPath $externalSentinel -Algorithm SHA256).Hash -eq $originalHash) 'Junction rejection changed external data.'
}
finally {
    # Remove only our two junction entries before removing our disposable
    # directories. Never recurse into a junction target.
    if (Test-Path -LiteralPath $nestedLink) { Remove-Item -LiteralPath $nestedLink -Force }
    if (Test-Path -LiteralPath $linkedRoot) { Remove-Item -LiteralPath $linkedRoot -Force }
    if (Test-Path -LiteralPath $fixtureRoot) { Remove-Item -LiteralPath $fixtureRoot -Recurse -Force }
}
$acceptanceSource = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'acceptance-windows-clean-install.ps1') -Raw
Assert-True ($acceptanceSource.Contains('Assert-ReefVisionAcceptanceTreeNoReparsePoints -Path $RunRoot')) 'MSI acceptance cleanup must recheck linked descendants.'

$arguments = New-ReefVisionMsiArguments -Action Install -PackageOrProduct 'C:\build\ReefVision.msi' -InstallRoot 'C:\rv-test\install' -LogPath 'C:\rv-test\install.log'
Assert-True ($arguments[0] -eq '/i') 'Install command does not use /i.'
Assert-True (($arguments -join ' ') -match 'INSTALLDIR=') 'Install command omitted isolated INSTALLDIR.'
# A same-version MSI reinstall is not an upgrade, and must never earn
# a passing migration/rollback acceptance result.
Assert-True (Assert-ReefVisionUpgradeVersion -PreviousVersion '1.0.1' -TargetVersion '1.0.2') 'Valid patch upgrade was rejected.'
Assert-True (Assert-ReefVisionUpgradeVersion -PreviousVersion '1.9.65535' -TargetVersion '2.0.0') 'Valid major upgrade was rejected.'
Assert-ThrowsContaining { Assert-ReefVisionUpgradeVersion -PreviousVersion '1.0.2' -TargetVersion '1.0.2' } 'Refusing non-upgrade'
Assert-ThrowsContaining { Assert-ReefVisionUpgradeVersion -PreviousVersion '1.0.2' -TargetVersion '1.0.1' } 'Refusing non-upgrade'
Assert-ThrowsContaining { Assert-ReefVisionUpgradeVersion -PreviousVersion '1.0.2' -TargetVersion '1.0.2.1' } 'Invalid MSI ProductVersion'
Assert-ThrowsContaining { Assert-ReefVisionUpgradeVersion -PreviousVersion '1.0.2' -TargetVersion '256.0.0' } 'Windows Installer limits'
Assert-ThrowsContaining { Assert-ReefVisionUpgradeVersion -PreviousVersion '1.0.2' -TargetVersion '1.256.0' } 'Windows Installer limits'
Assert-ThrowsContaining { Assert-ReefVisionUpgradeVersion -PreviousVersion '1.0.2' -TargetVersion '1.0.65536' } 'Windows Installer limits'
Assert-ThrowsContaining { Assert-ReefVisionUpgradeVersion -PreviousVersion 'not-an-msi-version' -TargetVersion '1.0.2' } 'Invalid MSI ProductVersion'

$uninstall = New-ReefVisionMsiArguments -Action Uninstall -PackageOrProduct '{00000000-0000-0000-0000-000000000000}' -LogPath 'C:\rv-test\uninstall.log'
Assert-True ($uninstall[0] -eq '/x') 'Uninstall command does not use /x.'

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
Assert-True ($acceptanceScript.Contains('Assert-ReefVisionUpgradeVersion -PreviousVersion $PreviousProductVersion -TargetVersion $ProductVersion')) 'Upgrade must check strict MSI version ordering before any install.'
Assert-True ($acceptanceScript.Contains("MSI returned success; post-upgrade checks pending.")) 'msiexec exit alone must not mark upgrade PASS.'
Assert-True ($acceptanceScript.Contains('$upgradedMigration.current_schema_revision -ne $upgradedMigration.expected_schema_revision')) 'Upgrade must verify migrated schema after restart.'
Assert-True ($acceptanceScript.Contains('$registrations[0].DisplayVersion -ne $ProductVersion')) 'Upgrade must verify registered MSI version.'
Assert-True ($acceptanceScript.Contains('Verified version $PreviousProductVersion -> $ProductVersion')) 'Upgrade PASS must follow installed version and scientific-data checks.'
$libraryTokens = $null
$libraryParseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PSScriptRoot 'lib\windows-clean-acceptance.ps1'),
    [ref]$libraryTokens,
    [ref]$libraryParseErrors
)
Assert-True (@($libraryParseErrors).Count -eq 0) "Windows acceptance helper syntax invalid: $($libraryParseErrors -join '; ')"

# The disposable installed-MSI test must exercise 1.6 QC coordination through
# HTTP and verify persisted audit/review state after a second desktop restart.
Assert-True ($acceptanceScript.Contains('qc_review_coordination = New-ReefVisionEvidenceResult')) 'Installed QC acceptance evidence field is missing.'
Assert-True ($acceptanceScript.Contains('"$api/projects/$projectId/review-queues"')) 'Installed QC acceptance must generate a real scoped review queue.'
Assert-True ($acceptanceScript.Contains('requires_researcher_review -ne $true')) 'Installed QC acceptance must assert researcher-review gating.'
Assert-True ($acceptanceScript.Contains('qcComment.id -ne $qcCommentRetry.id')) 'Installed QC comment idempotence regression is missing.'
Assert-True ($acceptanceScript.Contains('qcSkipRetry.changed_count -ne 0')) 'Installed QC bulk retry regression is missing.'
Assert-True ($acceptanceScript.Contains('qcPersistedEvents.total -ne 5')) 'Installed QC audit history must be checked after desktop restart.'
Assert-True ($acceptanceScript.Contains('qcPersistedAnnotations.annotations')) 'Installed QC acceptance must preserve the original annotation.'

# Regression: a port file may exist before Uvicorn binds. Every installed
# desktop launch (initial, post-upgrade/restart, and QC persistence restart)
# must wait for real loopback HTTP version + migrated schema readiness.
Assert-True ($acceptanceScript.Contains('function Wait-BackendApiReady(')) 'Packaged API readiness helper is missing.'
Assert-True (([regex]::Matches($acceptanceScript, 'Wait-BackendApiReady -ApiBaseUrl \$api -DesktopProcess \$desktop -BackendLogPath')).Count -eq 3) 'All three desktop launches must wait for packaged HTTP readiness.'
Assert-True ($acceptanceScript.Contains('Invoke-RestMethod -Uri "$ApiBaseUrl/system/version" -TimeoutSec 3')) 'Readiness must probe the packaged version endpoint with a bounded timeout.'
Assert-True ($acceptanceScript.Contains('Invoke-RestMethod -Uri "$ApiBaseUrl/system/migrations/status" -TimeoutSec 3')) 'Readiness must probe migrated schema status.'
Assert-True ($acceptanceScript.Contains('$migration.current_schema_revision -eq $migration.expected_schema_revision')) 'Readiness must not accept an out-of-date schema.'
Assert-True ($acceptanceScript.Contains('$DesktopProcess.HasExited')) 'Readiness must fail if the desktop exits.'
Assert-True ($acceptanceScript.Contains('Packaged API was not ready after $Seconds seconds')) 'Readiness timeout must report a bounded failure.'

# Verify packaged class visibility is exercised against the installed API and
# checked after the first restart (or real MSI upgrade), not only TestClient.
Assert-True ($acceptanceScript.Contains('class_visibility_persistence = New-ReefVisionEvidenceResult')) 'Packaged class visibility acceptance evidence field is missing.'
Assert-True ($acceptanceScript.Contains('"$api/projects/$projectId/class-visibility"')) 'Packaged class visibility must use the isolated project API.'
Assert-True ($acceptanceScript.Contains('"$visibilityUrl/defaults/annotations"')) 'Packaged project class visibility default is not persisted.'
Assert-True ($acceptanceScript.Contains('"$visibilityUrl/preferences/annotations"')) 'Packaged local-user visibility override is not persisted.'
Assert-True ($acceptanceScript.Contains('hidden_class_ids = @()')) 'Packaged class visibility must test an explicit empty override.'
# Regression from Windows acceptance run 40147705506: the desktop restarts
# on a new ephemeral port. The old cached visibility URL targets a dead API.
$visibilityReload = '$persistedVisibility = Invoke-RestMethod "$api/projects/$projectId/class-visibility"'
Assert-True ($acceptanceScript.Contains($visibilityReload)) 'Packaged class visibility must use the current API port after restart.'
Assert-True (-not $acceptanceScript.Contains('$persistedVisibility = Invoke-RestMethod $visibilityUrl')) 'Packaged visibility reloaded through the first launch stale port.'
$apiReadinessCalls = [regex]::Matches($acceptanceScript, 'Wait-BackendApiReady -ApiBaseUrl \\$api -DesktopProcess \\$desktop -BackendLogPath')
Assert-True ($apiReadinessCalls.Count -eq 3) 'Expected three independently ready desktop launches.'
Assert-True ($acceptanceScript.IndexOf($visibilityReload, [System.StringComparison]::Ordinal) -gt $apiReadinessCalls[1].Index) 'Visibility reload must follow readiness of the restarted API.'
Assert-True ($acceptanceScript.Contains('$persistedVisibility.user_identity -ne $visibilityIdentity')) 'Packaged local-user identity stability is not checked.'
Assert-True ($acceptanceScript.Contains('$persistedVisibility.project_defaults.annotations.hidden_class_ids[0] -ne $testClass.id')) 'Packaged project visibility default is not checked after restart.'
Assert-True ($acceptanceScript.Contains('@($persistedVisibility.user_preferences.annotations.hidden_class_ids).Count -ne 0')) 'Packaged explicit empty preference is not checked after restart.'

# Guard the packaged acceptance request against retired project templates and
# legacy model catalog selectors. Production API supports blank projects only.
Assert-True ($acceptanceScript.Contains("template='blank'")) 'Acceptance project must use the supported blank template.'
Assert-True (-not $acceptanceScript.Contains("template='octocoral'")) 'Retired octocoral template must not be used.'
Assert-True ($acceptanceScript.Contains('"$api/projects/$projectId/classes"')) 'Blank acceptance project must seed a label class explicitly.'
Assert-True ($acceptanceScript.Contains("selection_kind -eq 'builtin_architecture'")) 'Catalog selection_kind must match the current API.'
Assert-True (-not $acceptanceScript.Contains("selection_kind -eq 'architecture'")) 'Legacy architecture selection kind must not be used.'
Assert-True ($acceptanceScript.Contains('external_annotation_imports = New-ReefVisionEvidenceResult')) 'Installed backend COCO/YOLO evidence must be reported.'
Assert-True ($acceptanceScript.Contains('function Import-AcceptanceAnnotations')) 'Windows acceptance must use a real multipart annotation import.'
Assert-True ($acceptanceScript.Contains('cocoResult.boxes_imported -ne 1')) 'COCO imported box acceptance is missing.'
Assert-True ($acceptanceScript.Contains('yoloResult.boxes_imported -ne 1')) 'YOLO imported box acceptance is missing.'
Assert-True ($acceptanceScript.Contains('LiveSam2Acceptance')) 'Live SAM mode must be declared.'
Assert-True ($acceptanceScript.Contains('if ($LiveSam2Acceptance -and -not $ApprovedCheckpointDownload)')) 'Network checkpoint acquisition must require explicit researcher approval.'
$buildWorkflow = Get-Content -LiteralPath (Join-Path $Root '.github\workflows\build-desktop.yml') -Raw
Assert-True (-not $buildWorkflow.Contains('-LiveSam2Acceptance')) 'Automated Windows PR acceptance must never download pretrained weights.'
# This must fail before resolving an MSI, creating a test data root, or
# downloading any checkpoint; no actual installer or network is required.
try {
    & $acceptancePath -InstallerPath 'C:\reefvision-unapproved-checkpoint-test.msi' -AcceptanceRoot $safeRoot -PlanOnly -LiveSam2Acceptance
    throw 'Expected approval refusal'
} catch {
    if ($_.Exception.Message -eq 'Expected approval refusal') { throw }
    Assert-True ($_.Exception.Message -like '*-ApprovedCheckpointDownload*') 'Unapproved live SAM acceptance did not fail closed before installer access.'
}
Assert-True ($acceptanceScript.Contains("HF_HUB_OFFLINE'] = '0'")) 'Opt-in live SAM must allow a real network download.'
Assert-True ($acceptanceScript.Contains('samAcceptedMaskId')) 'Live SAM acceptance must validate mask preservation.'
Assert-True ($acceptanceScript.Contains("'api.log', 'api.log.1'")) 'Failed SAM2 acceptance must archive API logs, not only startup backend.log.'
Assert-True ($acceptanceScript.Contains('api.log.tail.log') -or $acceptanceScript.Contains('$logName.tail.log')) 'SAM2 API log archive name must match the uploaded *.log evidence pattern.'
Assert-True ($acceptanceScript -match 'Stop-AcceptanceDesktop\s+\$desktop\s*\r?\n\s*\$projectChecksum\s*=\s*\(Get-FileHash\s+-LiteralPath\s+\(Join-Path\s+\$DataRoot\s+''reefvision\.db''\)') 'Desktop shutdown must occur before hashing reefvision.db.'
Assert-True ($acceptanceScript -match 'Where-Object\s+FullName\s+-eq\s+''reefvision-exchange-manifest\.json''') 'Project Exchange validation does not require the canonical manifest name.'
Assert-True ($acceptanceScript -notmatch 'Where-Object\s+FullName\s+-eq\s+''manifest\.json''') 'Project Exchange validation still accepts the incorrect manifest.json name.'

$reportPath = Join-Path $env:TEMP ('reefvision-evidence-' + [guid]::NewGuid().ToString('N') + '.json')
$report = [ordered]@{ upgrade = New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'previous installer not supplied'; failure_reason = $null }
Write-ReefVisionEvidenceReport -Report $report -Path $reportPath
$roundTrip = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
Assert-True ($roundTrip.upgrade.status -eq 'SKIPPED') 'Report did not preserve skip semantics.'
Assert-True ($null -eq $roundTrip.failure_reason) 'Report did not preserve an empty failure reason.'
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
