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
# Caller-supplied variables must not bypass offline model policy or redirect
# disposable model caches into a researcher's real environment. Rejections
# must happen before executing the acceptance action.
$script:isolationOverrideActionRan = $false
Assert-Throws { Invoke-ReefVisionIsolatedEnvironment -DataRoot 'C:\isolated-acceptance' -AdditionalEnvironment @{ HF_HUB_OFFLINE = '0' } -Action { $script:isolationOverrideActionRan = $true } } 'Offline model policy override must be rejected.'
Assert-Throws { Invoke-ReefVisionIsolatedEnvironment -DataRoot 'C:\isolated-acceptance' -AdditionalEnvironment @{ hf_home = 'C:\researcher-cache' } -Action { $script:isolationOverrideActionRan = $true } } 'Case-insensitive disposable cache override must be rejected.'
# Neither Python startup injection nor legacy cache/configuration redirection
# may bypass the disposable acceptance environment (including mixed-case keys).
foreach ($unsafeOverrides in @(
    @{ pythonpath = 'C:\developer-python' },
    @{ PYTHONHOME = 'C:\developer-python' },
    @{ transformers_cache = 'C:\researcher-models' },
    @{ reefvision_config_dir = 'C:\researcher-config' },
    @{ REEFVISION_DATA_DIR = 'C:\researcher-data' },
    @{ REEFVISION_ACCEPTANCE_DATA_DIR = 'C:\researcher-data' },
    @{ REEFVISION_WINDOWS_ACCEPTANCE = '0' }
)) {
    Assert-Throws {
        Invoke-ReefVisionIsolatedEnvironment -DataRoot 'C:\isolated-acceptance' -AdditionalEnvironment $unsafeOverrides -Action {
            $script:isolationOverrideActionRan = $true
        }
    } "Unsafe environment override $(@($unsafeOverrides.Keys) -join ',') must be rejected."
}
Assert-True (-not $script:isolationOverrideActionRan) 'Rejected isolation override executed its action.'
# Existing Hugging Face and remote experiment-tracking credentials must
# never reach a disposable installer/sidecar process, including opt-in SAM.
# Synthetic sentinels only: no real credentials, network or MSI are used.
$credentialNames = @(
    'HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN', 'HF_ENDPOINT',
    'WANDB_API_KEY', 'COMET_API_KEY', 'MLFLOW_TRACKING_URI',
    'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'AZURE_OPENAI_API_KEY',
    'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN',
    'AWS_PROFILE', 'AWS_DEFAULT_PROFILE',
    'AWS_SHARED_CREDENTIALS_FILE', 'AWS_CONFIG_FILE', 'AWS_ENDPOINT_URL',
    'GOOGLE_APPLICATION_CREDENTIALS', 'GOOGLE_API_KEY',
    'AZURE_CLIENT_ID', 'AZURE_TENANT_ID', 'AZURE_CLIENT_SECRET'
)
$previousCredentials = @{}
$credentialSentinel = 'SYNTHETIC_ACCEPTANCE_CREDENTIAL_DO_NOT_USE'
try {
    foreach ($name in $credentialNames) {
        $previousCredentials[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $credentialSentinel, 'Process')
    }
    foreach ($name in $credentialNames) {
        $injected = @{}
        $injected[$name] = $credentialSentinel
        Assert-Throws {
            Invoke-ReefVisionIsolatedEnvironment -DataRoot 'C:\isolated-acceptance' -AdditionalEnvironment $injected -Action {
                $script:isolationOverrideActionRan = $true
            }
        } "Credential or tracking override $name must be rejected before execution."
    }
    Invoke-ReefVisionIsolatedEnvironment -DataRoot 'C:\isolated-acceptance' -Action {
        foreach ($name in $credentialNames) {
            Assert-True ($null -eq [Environment]::GetEnvironmentVariable($name, 'Process')) "Inherited $name leaked into offline acceptance."
        }
    }
    Invoke-ReefVisionIsolatedEnvironment -DataRoot 'C:\isolated-acceptance' -AllowLiveSam2Network -AdditionalEnvironment @{
        HF_HUB_OFFLINE = '0'; TRANSFORMERS_OFFLINE = '0'
    } -Action {
        foreach ($name in $credentialNames) {
            Assert-True ($null -eq [Environment]::GetEnvironmentVariable($name, 'Process')) "Inherited $name leaked into live SAM acceptance."
        }
    }
    Assert-Throws {
        Invoke-ReefVisionIsolatedEnvironment -DataRoot 'C:\isolated-acceptance' -Action {
            throw 'Synthetic sidecar startup failure for credential restoration'
        }
    } 'Synthetic sidecar failure must propagate without leaking credentials.'
    foreach ($name in $credentialNames) {
        Assert-True ([Environment]::GetEnvironmentVariable($name, 'Process') -ceq $credentialSentinel) "Caller $name was not restored after success and failure."
    }
} finally {
    foreach ($name in $credentialNames) {
        [Environment]::SetEnvironmentVariable($name, $previousCredentials[$name], 'Process')
    }
}
Assert-True (-not $script:isolationOverrideActionRan) 'Rejected credential override executed its action.'

# Opt-in live SAM must not weaken the default offline policy or cache isolation.
# This is a mocked environment test: it performs no network requests.
$script:liveSamOptInActionRan = $false
Assert-Throws { Invoke-ReefVisionIsolatedEnvironment -DataRoot 'C:\isolated-acceptance' -AllowLiveSam2Network -AdditionalEnvironment @{ HF_HUB_OFFLINE = '0' } -Action { $script:liveSamOptInActionRan = $true } } 'Live SAM opt-in must require both offline flags.'
Assert-Throws { Invoke-ReefVisionIsolatedEnvironment -DataRoot 'C:\isolated-acceptance' -AllowLiveSam2Network -AdditionalEnvironment @{ HF_HUB_OFFLINE = '0'; TRANSFORMERS_OFFLINE = '1' } -Action { $script:liveSamOptInActionRan = $true } } 'Live SAM opt-in must reject partial offline-policy changes.'
Assert-Throws { Invoke-ReefVisionIsolatedEnvironment -DataRoot 'C:\isolated-acceptance' -AllowLiveSam2Network -AdditionalEnvironment @{ HF_HUB_OFFLINE = '0'; TRANSFORMERS_OFFLINE = '0'; hf_home = 'C:\researcher-cache' } -Action { $script:liveSamOptInActionRan = $true } } 'Live SAM opt-in must never redirect protected model caches.'
Assert-True (-not $script:liveSamOptInActionRan) 'Rejected live SAM opt-in executed its action.'
$previousTransformersOffline = [Environment]::GetEnvironmentVariable('TRANSFORMERS_OFFLINE', 'Process')
$previousLiveHfOffline = [Environment]::GetEnvironmentVariable('HF_HUB_OFFLINE', 'Process')
$previousLiveTelemetry = [Environment]::GetEnvironmentVariable('HF_HUB_DISABLE_TELEMETRY', 'Process')
Invoke-ReefVisionIsolatedEnvironment -DataRoot 'C:\isolated-acceptance' -AllowLiveSam2Network -AdditionalEnvironment @{ HF_HUB_OFFLINE = '0'; TRANSFORMERS_OFFLINE = '0'; HF_HUB_DISABLE_TELEMETRY = '1' } -Action {
    $script:liveSamOptInActionRan = $true
    Assert-True ($env:HF_HUB_OFFLINE -ceq '0' -and $env:TRANSFORMERS_OFFLINE -ceq '0') 'Explicit live SAM opt-in did not reach its isolated action.'
    Assert-True ($env:HF_HOME -eq 'C:\isolated-acceptance\cache\huggingface') 'Live SAM opt-in escaped the disposable model cache.'
    Assert-True ($env:HF_HUB_DISABLE_TELEMETRY -ceq '1') 'Live SAM opt-in did not disable telemetry.'
}
Assert-True ($script:liveSamOptInActionRan) 'Valid live SAM opt-in never executed its isolated action.'
Assert-True ([Environment]::GetEnvironmentVariable('HF_HUB_DISABLE_TELEMETRY', 'Process') -ceq $previousLiveTelemetry) 'Live SAM opt-in did not restore telemetry settings.'
Assert-True ([Environment]::GetEnvironmentVariable('TRANSFORMERS_OFFLINE', 'Process') -ceq $previousTransformersOffline) 'Live SAM opt-in did not restore TRANSFORMERS_OFFLINE.'
Assert-True ([Environment]::GetEnvironmentVariable('HF_HUB_OFFLINE', 'Process') -ceq $previousLiveHfOffline) 'Live SAM opt-in did not restore HF_HUB_OFFLINE.'
$previousAcceptanceMarker = [Environment]::GetEnvironmentVariable('REEFVISION_WINDOWS_ACCEPTANCE', 'Process')
$previousAcceptanceData = [Environment]::GetEnvironmentVariable('REEFVISION_ACCEPTANCE_DATA_DIR', 'Process')
$previousThreads = [Environment]::GetEnvironmentVariable('OMP_NUM_THREADS', 'Process')
Invoke-ReefVisionIsolatedEnvironment -DataRoot 'C:\isolated-acceptance' -AdditionalEnvironment @{
    REEFVISION_WINDOWS_ACCEPTANCE = '1'
    REEFVISION_ACCEPTANCE_DATA_DIR = 'C:\isolated-acceptance'
    OMP_NUM_THREADS = '2'
} -Action {
    Assert-True ($env:REEFVISION_WINDOWS_ACCEPTANCE -ceq '1') 'Windows acceptance marker was not applied.'
    Assert-True ($env:REEFVISION_ACCEPTANCE_DATA_DIR -eq 'C:\isolated-acceptance') 'Disposable acceptance data root was not applied.'
    Assert-True ($env:OMP_NUM_THREADS -ceq '2') 'Safe thread limit was not applied.'
    Assert-True ($env:HF_HUB_OFFLINE -eq '1') 'Safe additional environment variable disabled offline policy.'
}
Assert-True ([Environment]::GetEnvironmentVariable('REEFVISION_WINDOWS_ACCEPTANCE', 'Process') -ceq $previousAcceptanceMarker) 'Windows acceptance marker was not restored.'
Assert-True ([Environment]::GetEnvironmentVariable('REEFVISION_ACCEPTANCE_DATA_DIR', 'Process') -ceq $previousAcceptanceData) 'Disposable acceptance data root was not restored.'
Assert-True ([Environment]::GetEnvironmentVariable('OMP_NUM_THREADS', 'Process') -ceq $previousThreads) 'Safe thread limit was not restored.'

# The packaged MSI sidecar self-test must inherit only disposable offline
# caches, and the verifier must restore the caller environment even if the
# sidecar cannot start. No process or MSI is launched by these assertions.
$previousHfHome = [Environment]::GetEnvironmentVariable('HF_HOME', 'Process')
$previousOffline = [Environment]::GetEnvironmentVariable('HF_HUB_OFFLINE', 'Process')
$previousYoloConfig = [Environment]::GetEnvironmentVariable('YOLO_CONFIG_DIR', 'Process')
try {
    $env:HF_HOME = 'C:\developer-cache-must-not-leak'
    $env:HF_HUB_OFFLINE = '0'
    $env:YOLO_CONFIG_DIR = 'C:\developer-yolo-must-not-leak'
    Invoke-ReefVisionIsolatedEnvironment -DataRoot 'C:\disposable-msi-self-test' -Action {
        Assert-True ($env:HF_HOME -eq 'C:\disposable-msi-self-test\cache\huggingface') 'Packaged sidecar inherited developer Hugging Face cache.'
        Assert-True ($env:YOLO_CONFIG_DIR -eq 'C:\disposable-msi-self-test\cache\ultralytics') 'Packaged sidecar inherited developer Ultralytics cache.'
        Assert-True ($env:HF_HUB_OFFLINE -eq '1') 'Packaged sidecar could access online model downloads.'
    }
    Assert-True ($env:HF_HOME -eq 'C:\developer-cache-must-not-leak') 'MSI self-test did not restore caller Hugging Face cache.'
    Assert-True ($env:YOLO_CONFIG_DIR -eq 'C:\developer-yolo-must-not-leak') 'MSI self-test did not restore caller Ultralytics cache.'
    Assert-True ($env:HF_HUB_OFFLINE -eq '0') 'MSI self-test did not restore caller offline setting.'
    Assert-Throws { Invoke-ReefVisionIsolatedEnvironment -DataRoot 'C:\disposable-msi-self-test' -Action { throw 'Simulated packaged sidecar startup failure' } } 'Failed packaged sidecar startup must propagate an error.'
    Assert-True ($env:HF_HOME -eq 'C:\developer-cache-must-not-leak' -and $env:HF_HUB_OFFLINE -eq '0') 'Failed packaged sidecar startup leaked acceptance environment.'
} finally {
    if ($null -eq $previousHfHome) { Remove-Item Env:HF_HOME -ErrorAction SilentlyContinue } else { $env:HF_HOME = $previousHfHome }
    if ($null -eq $previousOffline) { Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue } else { $env:HF_HUB_OFFLINE = $previousOffline }
    if ($null -eq $previousYoloConfig) { Remove-Item Env:YOLO_CONFIG_DIR -ErrorAction SilentlyContinue } else { $env:YOLO_CONFIG_DIR = $previousYoloConfig }
}
$safeRoot = Join-Path $env:SystemDrive 'reefvision-clean-acceptance-tests'
Assert-True ((Assert-ReefVisionSafeAcceptanceRoot -Path $safeRoot -RepositoryRoot $Root -DefaultDataRoot $defaultData) -eq (Resolve-ReefVisionAcceptancePath $safeRoot)) 'Safe temp root was rejected.'
# A disposable directory under C:\ must be allowed, but C:\ itself and
# Windows/Program Files/repository/user-data directories must stay protected.
$driveRoot = [System.IO.Path]::GetPathRoot($safeRoot)
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path $driveRoot -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Drive root must be rejected.'
# Containing a protected directory is unsafe even if the proposed root is
# outside that directory. Use synthetic paths to exercise the ancestor case
# without creating or removing any real research data.
$nestedRepository = Join-Path $safeRoot 'existing-repository'
$nestedData = Join-Path $safeRoot 'scientific-data'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path $safeRoot -RepositoryRoot $nestedRepository -DefaultDataRoot $defaultData } 'Acceptance root containing a repository must be rejected.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path $safeRoot -RepositoryRoot $Root -DefaultDataRoot $nestedData } 'Acceptance root containing scientific app data must be rejected.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path (Split-Path -Parent $env:USERPROFILE) -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Shared user-profile parent must be rejected.'
# The acceptance root must not target another user's Documents or shared
# Public data even though those paths are outside the current USERPROFILE.
$profilesRoot = Split-Path -Parent $env:USERPROFILE
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path (Join-Path $profilesRoot 'Public\reefvision-unsafe-test') -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Shared Public profile content must be rejected.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path (Join-Path $profilesRoot 'another-profile\Documents\reefvision-unsafe-test') -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Another user profile must be rejected.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path (Join-Path $env:windir 'reefvision-unsafe-test') -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Windows directory descendants must be rejected.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path (Join-Path $env:ProgramFiles 'reefvision-unsafe-test') -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Program Files descendants must be rejected.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path (Join-Path $Root 'reefvision-unsafe-test') -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Repository descendants must be rejected.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path $Root -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Repository root must be rejected.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path $defaultData -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Normal app-data root must be rejected.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path (Split-Path -Parent $defaultData) -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Parent of normal app-data root must be rejected.'

# A disposable root in the local Temp folder is supported, but the Windows
# user profile is not a blanket exception: accepting Documents/Downloads
# would allow an install or cleanup run to overlap unrelated researcher data.
$localTempRoot = Join-Path $env:LOCALAPPDATA 'Temp\reefvision-disposable-acceptance'
Assert-True ((Assert-ReefVisionSafeAcceptanceRoot -Path $localTempRoot -RepositoryRoot $Root -DefaultDataRoot $defaultData) -eq (Resolve-ReefVisionAcceptancePath $localTempRoot)) 'Disposable local Temp acceptance root was rejected.'
# The shared Temp folder itself is not disposable: it can contain unrelated
# user files, and installer cleanup must never target it directly.
$sharedLocalTemp = Join-Path $env:LOCALAPPDATA 'Temp'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path $sharedLocalTemp -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'Shared local Temp folder must not be an acceptance root.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path (Join-Path $env:USERPROFILE 'Documents\reefvision-unsafe-test') -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'User Documents acceptance root must be rejected.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path (Join-Path $env:USERPROFILE 'Downloads\reefvision-unsafe-test') -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'User Downloads acceptance root must be rejected.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path (Join-Path $env:USERPROFILE 'Desktop\reefvision-unsafe-test') -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'User Desktop acceptance root must be rejected.'
Assert-Throws { Assert-ReefVisionSafeAcceptanceRoot -Path (Join-Path $env:LOCALAPPDATA 'reefvision-unsafe-test') -RepositoryRoot $Root -DefaultDataRoot $defaultData } 'User AppData Local outside Temp must be rejected.'


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

# The MSI verification script also creates disposable extraction/self-test
# roots. Prove it cannot authorize deletion after an ownership-marker swap or
# nested junction substitution. No MSI is installed by this regression.
$msiGuardParent = Join-Path $env:TEMP ('reefvision-msi-guard-' + [guid]::NewGuid().ToString('N'))
$msiGuardToken = 'abcdef12'
$msiGuardRun = Join-Path $msiGuardParent "rv1-$msiGuardToken"
$msiGuardMarker = Join-Path $msiGuardRun '.reefvision-msi-verification-run'
$msiGuardOutside = Join-Path $msiGuardParent 'research-data'
$msiGuardLink = Join-Path $msiGuardRun 'linked-data'
New-Item -ItemType Directory -Path $msiGuardRun -Force | Out-Null
New-Item -ItemType Directory -Path $msiGuardOutside -Force | Out-Null
$msiGuardSentinel = Join-Path $msiGuardOutside 'do-not-delete.txt'
Set-Content -LiteralPath $msiGuardSentinel -Value 'preserve' -Encoding Ascii
Set-Content -LiteralPath $msiGuardMarker -Value 'rv1:abcdef12' -Encoding Ascii
try {
    Assert-True (@(Assert-ReefVisionOwnedMsiVerificationRun -RunRoot $msiGuardRun -ParentRoot $msiGuardParent -Kind rv1 -Token $msiGuardToken).Count -eq 0) 'Owned MSI verification run was rejected.'
    Assert-Throws { Assert-ReefVisionOwnedMsiVerificationRun -RunRoot $msiGuardOutside -ParentRoot $msiGuardParent -Kind rv1 -Token $msiGuardToken } 'MSI verification cleanup must reject an unrelated directory.'
    Assert-Throws { Assert-ReefVisionOwnedMsiVerificationRun -RunRoot $msiGuardRun -ParentRoot $msiGuardParent -Kind rv1 -Token 'bad-token' } 'MSI verification cleanup must reject an invalid token.'
    Assert-Throws { Assert-ReefVisionOwnedMsiVerificationRun -RunRoot $msiGuardRun -ParentRoot $msiGuardParent -Kind rvd -Token $msiGuardToken } 'MSI verification cleanup must reject the wrong run kind.'
    Set-Content -LiteralPath $msiGuardMarker -Value 'rv1:wrong' -Encoding Ascii
    Assert-Throws { Assert-ReefVisionOwnedMsiVerificationRun -RunRoot $msiGuardRun -ParentRoot $msiGuardParent -Kind rv1 -Token $msiGuardToken } 'MSI verification cleanup must reject an altered ownership marker.'
    Remove-Item -LiteralPath $msiGuardMarker -Force
    Assert-Throws { Assert-ReefVisionOwnedMsiVerificationRun -RunRoot $msiGuardRun -ParentRoot $msiGuardParent -Kind rv1 -Token $msiGuardToken } 'MSI verification cleanup must reject a missing marker.'
    Set-Content -LiteralPath $msiGuardMarker -Value 'rv1:abcdef12' -Encoding Ascii
    New-Item -ItemType Junction -Path $msiGuardLink -Target $msiGuardOutside -ErrorAction Stop | Out-Null
    Assert-Throws { Assert-ReefVisionOwnedMsiVerificationRun -RunRoot $msiGuardRun -ParentRoot $msiGuardParent -Kind rv1 -Token $msiGuardToken } 'MSI verification cleanup must reject a nested junction.'
    Assert-True (Test-Path -LiteralPath $msiGuardSentinel -PathType Leaf) 'MSI verification junction guard altered external research data.'
} finally {
    if ([System.IO.Directory]::Exists($msiGuardLink)) { [System.IO.Directory]::Delete($msiGuardLink) }
    if ([System.IO.Directory]::Exists($msiGuardParent)) { [System.IO.Directory]::Delete($msiGuardParent, $true) }
}
# The verifier must invoke the ownership check immediately before deletion,
# rather than relying on a pre-extraction path check or a filename prefix.
$msiVerifierSource = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'verify-windows-msi.ps1') -Raw
# Reject ambiguous extracted payloads before checking the first matching file.
# These synthetic records do not invoke msiexec or touch installed software.
$packagedDesktop = [pscustomobject]@{ Name = 'ReefVision.exe'; FullName = 'C:\rv-test\ReefVision.exe' }
$duplicateDesktop = [pscustomobject]@{ Name = 'REEFVISION.EXE'; FullName = 'C:\rv-test\shadow\REEFVISION.EXE' }
$uniqueDesktop = Get-ReefVisionUniquePackagedFile -Candidates @($packagedDesktop) -Description 'ReefVision.exe'
Assert-True ($uniqueDesktop.FullName -ceq $packagedDesktop.FullName) 'Unique MSI payload was not selected.'
Assert-Throws { $null = Get-ReefVisionUniquePackagedFile -Candidates @() -Description 'ReefVision.exe' } 'Missing critical MSI payload must fail.'
Assert-Throws { $null = Get-ReefVisionUniquePackagedFile -Candidates @($packagedDesktop, $duplicateDesktop) -Description 'ReefVision.exe' } 'Duplicate critical MSI payload must fail.'
Assert-Throws { $null = Get-ReefVisionUniquePackagedFile -Candidates @($packagedDesktop) -Description ' ' } 'Blank MSI payload description must fail.'
Assert-True ([regex]::Matches($msiVerifierSource, 'Get-ReefVisionUniquePackagedFile -Candidates').Count -eq 6) 'MSI verifier must enforce uniqueness for all six critical payload types.'

# Missing JSON fields previously cast to zero, allowing incomplete model
# manifests to pass the weight-free MSI gate. Exercise the parsed JSON types.
$weightFreeJson = '{"model_policy":"architecture_first_no_pretrained_weights","asset_count":0,"provider_asset_count":0,"total_size_bytes":0}'
$weightFreeManifest = $weightFreeJson | ConvertFrom-Json
Assert-True (@(Assert-ReefVisionWeightFreeManifest -Manifest $weightFreeManifest).Count -eq 0) 'Valid weight-free model manifest was rejected.'
foreach ($missingField in @('model_policy', 'asset_count', 'provider_asset_count', 'total_size_bytes')) {
    $missing = [pscustomobject]@{}
    foreach ($property in $weightFreeManifest.PSObject.Properties) {
        if ($property.Name -cne $missingField) {
            $missing | Add-Member -NotePropertyName $property.Name -NotePropertyValue $property.Value
        }
    }
    Assert-Throws { Assert-ReefVisionWeightFreeManifest -Manifest $missing } "Missing bundled-model manifest field $missingField must fail."
}
foreach ($invalidValue in @('0', 0.5, -1, $true, $null)) {
    $invalid = $weightFreeJson | ConvertFrom-Json
    $invalid.asset_count = $invalidValue
    Assert-Throws { Assert-ReefVisionWeightFreeManifest -Manifest $invalid } 'Invalid bundled-model asset count must fail.'
}
$wrongPolicy = $weightFreeJson | ConvertFrom-Json
$wrongPolicy.model_policy = 'pretrained_weights_allowed'
Assert-Throws { Assert-ReefVisionWeightFreeManifest -Manifest $wrongPolicy } 'Non-weight-free model policy must fail.'
Assert-Throws { Assert-ReefVisionWeightFreeManifest -Manifest @{} } 'Non-JSON-object manifest must fail.'
Assert-True ($msiVerifierSource.Contains('Assert-ReefVisionWeightFreeManifest -Manifest $Manifest')) 'MSI verifier must enforce strict manifest schema before the model audit.'


$msiCleanupGuard = $msiVerifierSource.IndexOf('Assert-ReefVisionOwnedMsiVerificationRun -RunRoot $entry.Path')
$msiCleanupDelete = $msiVerifierSource.IndexOf('Remove-Item -LiteralPath $entry.Path -Recurse -Force')
Assert-True ($msiCleanupGuard -ge 0 -and $msiCleanupDelete -gt $msiCleanupGuard) 'MSI verifier must check disposable ownership before recursive deletion.'
Assert-True (-not $msiVerifierSource.Contains('Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $ExtractRoot')) 'MSI verifier still has unguarded extraction cleanup.'

# A Windows Installer reboot-required result is not a completed clean install.
# The harness must not report PASS or remove its evidence while a reboot is
# pending. Exercise both installation and uninstallation without running MSI.
foreach ($msiAction in @('Install', 'Uninstall', 'Extract')) {
    $successOutput = @(Assert-ReefVisionMsiCompletedWithoutReboot -Action $msiAction -ExitCode 0 -LogPath 'C:\\rv-test\\msi.log')
    Assert-True ($successOutput.Count -eq 0) "Successful $msiAction must emit no spurious pipeline output."
    foreach ($pendingCode in @(3010, 1641)) {
        $rebootMessage = $null
        try {
            Assert-ReefVisionMsiCompletedWithoutReboot -Action $msiAction -ExitCode $pendingCode -LogPath 'C:\\rv-test\\msi.log'
        } catch {
            $rebootMessage = $_.Exception.Message
        }
        Assert-True ($null -ne $rebootMessage -and $rebootMessage.Contains('requires a Windows reboot') -and $rebootMessage.Contains([string]$pendingCode)) "Reboot-pending $msiAction ($pendingCode) must fail closed with an explicit reason."
    }
    Assert-Throws { Assert-ReefVisionMsiCompletedWithoutReboot -Action $msiAction -ExitCode 1603 -LogPath 'C:\\rv-test\\msi.log' } "MSI $msiAction failure 1603 must be rejected."
}

$arguments = New-ReefVisionMsiArguments -Action Install -PackageOrProduct 'C:\build\ReefVision.msi' -InstallRoot 'C:\rv-test\install' -LogPath 'C:\rv-test\install.log'
Assert-True ($arguments[0] -eq '/i') 'Install command does not use /i.'
Assert-True (($arguments -join ' ') -match 'INSTALLDIR=') 'Install command omitted isolated INSTALLDIR.'
$uninstall = New-ReefVisionMsiArguments -Action Uninstall -PackageOrProduct '{00000000-0000-0000-0000-000000000000}' -LogPath 'C:\rv-test\uninstall.log'
Assert-True ($uninstall[0] -eq '/x') 'Uninstall command does not use /x.'

# Never allow an acceptance install to fall back to the real default path,
# or allow command-line metacharacters to escape msiexec argument boundaries.
$spacedInstall = @(New-ReefVisionMsiArguments -Action Install -PackageOrProduct 'C:\camera dataset\ReefVision.msi' -InstallRoot 'C:\rv validation\install' -LogPath 'C:\User Name\Temp\install.log')
Assert-True ($spacedInstall[1] -ceq '"C:\camera dataset\ReefVision.msi"') 'MSI install package with spaces was not quoted.'
Assert-True ($spacedInstall[5] -ceq '"C:\User Name\Temp\install.log"') 'MSI install log with spaces was not quoted.'
Assert-True ($spacedInstall[6] -ceq 'INSTALLDIR="C:\rv validation\install"') 'Disposable MSI install root with spaces was not quoted.'
Assert-Throws { New-ReefVisionMsiArguments -Action Install -PackageOrProduct 'C:\build\ReefVision.msi' -LogPath 'C:\install.log' | Out-Null } 'MSI install without isolated INSTALLDIR must fail.'
Assert-Throws { New-ReefVisionMsiArguments -Action Install -PackageOrProduct 'C:\build\ReefVision.msi' -InstallRoot 'C:\safe" /x unsafe' -LogPath 'C:\install.log' | Out-Null } 'Quoted INSTALLDIR injection must fail.'
Assert-Throws { New-ReefVisionMsiArguments -Action Install -PackageOrProduct 'C:\build" /x unsafe' -InstallRoot 'C:\rv-test' -LogPath 'C:\install.log' | Out-Null } 'Quoted MSI package injection must fail.'
Assert-Throws { New-ReefVisionMsiArguments -Action Uninstall -PackageOrProduct '{00000000-0000-0000-0000-000000000000}' -InstallRoot 'C:\rv-test' -LogPath 'C:\uninstall.log' | Out-Null } 'Uninstall must not accept INSTALLDIR.'
Assert-Throws { New-ReefVisionMsiArguments -Action Install -PackageOrProduct "C:\build\`nReefVision.msi" -InstallRoot 'C:\rv-test' -LogPath 'C:\install.log' | Out-Null } 'Newline in MSI package argument must fail.'
Assert-Throws { New-ReefVisionMsiArguments -Action Uninstall -PackageOrProduct '{00000000-0000-0000-0000-000000000000}' -LogPath "C:\logs\`r`nuninstall.log" | Out-Null } 'Newline in MSI log argument must fail.'
# Windows command-line parsers can treat a backslash immediately before a
# closing quote as an escape, so reject trailing separators in quoted arguments.
Assert-Throws { New-ReefVisionMsiArguments -Action Install -PackageOrProduct 'C:\build\ReefVision.msi' -InstallRoot 'C:\rv-test\' -LogPath 'C:\install.log' | Out-Null } 'Trailing slash in INSTALLDIR must fail.'
Assert-Throws { New-ReefVisionMsiArguments -Action Install -PackageOrProduct 'C:\build\ReefVision.msi' -InstallRoot 'C:\rv-test' -LogPath 'C:\logs\' | Out-Null } 'Trailing slash in MSI log path must fail.'
Assert-True ((ConvertTo-ReefVisionVersionString ' 1.0.3 ') -eq '1.0.3') 'MSI version comparison did not normalize COM padding.'


# Start-Process does not preserve argument boundaries when paths contain spaces.
# Verify the exact MSI command-line tokens without invoking msiexec.
$adminArgs = @(New-ReefVisionMsiAdministrativeArguments -PackagePath 'C:\camera dataset\ReefVision.msi' -ExtractRoot 'C:\rv validation\extract' -LogPath 'C:\User Name\Temp\msi.log')
Assert-True ($adminArgs.Count -eq 6) 'MSI administrative extraction must supply six arguments.'
Assert-True ($adminArgs[0] -ceq '/a') 'MSI administrative extraction must use /a.'
Assert-True ($adminArgs[1] -ceq '"C:\camera dataset\ReefVision.msi"') 'MSI path containing spaces must be quoted.'
Assert-True ($adminArgs[3] -ceq 'TARGETDIR="C:\rv validation\extract"') 'Administrative extraction root containing spaces must be quoted.'
Assert-True ($adminArgs[5] -ceq '"C:\User Name\Temp\msi.log"') 'MSI log path containing spaces must be quoted.'
Assert-Throws { New-ReefVisionMsiAdministrativeArguments -PackagePath 'C:\unsafe"payload.msi' -ExtractRoot 'C:\rv-test' -LogPath 'C:\msi.log' | Out-Null } 'MSI path containing quotes must be rejected.'
Assert-Throws { New-ReefVisionMsiAdministrativeArguments -PackagePath ([string]::Concat('C:\build', [char]10, 'ReefVision.msi')) -ExtractRoot 'C:\rv-test' -LogPath 'C:\msi.log' | Out-Null } 'Administrative MSI path containing newline must fail.'
Assert-Throws { New-ReefVisionMsiAdministrativeArguments -PackagePath 'C:\build\ReefVision.msi' -ExtractRoot 'C:\rv-test\' -LogPath 'C:\msi.log' | Out-Null } 'Administrative extraction root with trailing slash must fail.'
Assert-Throws { New-ReefVisionMsiAdministrativeArguments -PackagePath 'C:\build\ReefVision.msi' -ExtractRoot 'C:\rv-test' -LogPath ([string]::Concat('C:\logs', [char]13, [char]10, 'msi.log')) | Out-Null } 'Administrative MSI log containing newline must fail.'

# MSI Media table CAB contract: fail closed on missing, unexpected, duplicate,
# or path-traversing payloads before any administrative extraction is attempted.
$validCabinets = Assert-ReefVisionMsiCabinetSet -DeclaredCabinets @('#embedded.cab', 'rv1.cab', 'RV2.CAB') -AvailableCabinets @('RV1.CAB', 'rv2.cab')
Assert-True ($validCabinets.Count -eq 2) 'Embedded MSI cabinets must not require external files.'
Assert-Throws { Assert-ReefVisionMsiCabinetSet -DeclaredCabinets @('rv1.cab', 'rv2.cab') -AvailableCabinets @('rv1.cab') | Out-Null } 'Missing MSI-declared CAB must fail.'
Assert-Throws { Assert-ReefVisionMsiCabinetSet -DeclaredCabinets @('rv1.cab') -AvailableCabinets @('rv1.cab', 'rv2.cab') | Out-Null } 'Unexpected CAB must fail.'
Assert-Throws { Assert-ReefVisionMsiCabinetSet -DeclaredCabinets @('rv1.cab') -AvailableCabinets @('rv1.cab', 'RV1.CAB') | Out-Null } 'Duplicate CAB names must fail case-insensitively.'
Assert-Throws { Assert-ReefVisionMsiCabinetSet -DeclaredCabinets @('../rv1.cab') -AvailableCabinets @('rv1.cab') | Out-Null } 'MSI Media path traversal must fail.'
Assert-Throws { Assert-ReefVisionMsiCabinetSet -DeclaredCabinets @('#embedded.cab') -AvailableCabinets @() | Out-Null } 'An installer with no external CAB declarations must not pass.'
Assert-Throws { Assert-ReefVisionMsiCabinetSet -DeclaredCabinets @('rv1.cab') -AvailableCabinets @('../rv1.cab') | Out-Null } 'External CAB path traversal must fail.'
Assert-Throws { Assert-ReefVisionMsiCabinetSet -DeclaredCabinets @('rv1.cab', 'RV1.CAB') -AvailableCabinets @('rv1.cab') | Out-Null } 'Duplicate Media cabinet declarations must fail case-insensitively.'
Assert-Throws { Assert-ReefVisionMsiCabinetSet -DeclaredCabinets @('#../embedded.cab', 'rv1.cab') -AvailableCabinets @('rv1.cab') | Out-Null } 'Malformed embedded cabinet names must fail.'
Assert-Throws { Assert-ReefVisionMsiCabinetSet -DeclaredCabinets @('#', 'rv1.cab') -AvailableCabinets @('rv1.cab') | Out-Null } 'Empty embedded cabinet names must fail.'
# Windows reserves DOS device basenames even when an extension is present.
# Reject those names from both the MSI Media table and the external payload;
# harmless longer basenames such as CONSOLE.cab must still be accepted.
# Windows also resolves reserved device names before *any* extension.
# A CAB named CON.backup.cab or COM1.logs.cab is still unsafe.
foreach ($deviceCab in @('CON.cab', 'prn.CAB', 'AUX.cab', 'nul.cab', 'com1.cab', 'LPT9.CAB', 'CON.backup.cab', 'prn.extra.CAB', 'COM1.logs.cab', 'LPT9..cab')) {
    Assert-Throws { Assert-ReefVisionMsiCabinetSet -DeclaredCabinets @($deviceCab) -AvailableCabinets @($deviceCab) | Out-Null } "Reserved MSI cabinet basename $deviceCab must fail."
    Assert-Throws { Assert-ReefVisionMsiCabinetSet -DeclaredCabinets @('rv1.cab') -AvailableCabinets @('rv1.cab', $deviceCab) | Out-Null } "Reserved external cabinet basename $deviceCab must fail."
}
$ordinaryCab = Assert-ReefVisionMsiCabinetSet -DeclaredCabinets @('CONSOLE.cab') -AvailableCabinets @('console.CAB')
Assert-True ($ordinaryCab.Count -eq 1) 'Non-device cabinet basename must remain valid.'
# Verification must reject symlinked MSI/CAB inputs before opening or extracting
# any package, without actually installing software in this harness.
$msiVerifier = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'verify-windows-msi.ps1') -Raw
Assert-True ($msiVerifier.Contains('$SidecarProcess = Invoke-ReefVisionIsolatedEnvironment -DataRoot $SelfTestData -Action {')) 'MSI verifier must launch the packaged sidecar inside the disposable offline environment.'
$isolatedLaunch = $msiVerifier.IndexOf('$SidecarProcess = Invoke-ReefVisionIsolatedEnvironment -DataRoot $SelfTestData -Action {')
$sidecarLaunch = $msiVerifier.IndexOf('Start-Process -FilePath $SidecarExe.FullName')
$sidecarCheck = $msiVerifier.IndexOf('if ($SidecarProcess.ExitCode -ne 0)')
Assert-True ($isolatedLaunch -ge 0 -and $sidecarLaunch -gt $isolatedLaunch -and $sidecarCheck -gt $sidecarLaunch) 'MSI sidecar launch and exit-code check must follow offline isolation.'
Assert-True ($msiVerifier.Contains('New-ReefVisionMsiAdministrativeArguments')) 'MSI verifier must quote extraction and log paths using the tested helper.'
Assert-True ($msiVerifier.Contains('Assert-ReefVisionMsiCompletedWithoutReboot -Action Extract -ExitCode $MsiExitCode -LogPath $MsiLog')) 'MSI verifier must reject reboot-required administrative extraction before inspecting files.'
Assert-True ($msiVerifier.Contains('Assert-ReefVisionNoReparseAncestors -Path $Msi.FullName')) 'MSI verifier does not reject reparse-point MSI paths.'
Assert-True ($msiVerifier.Contains('Assert-ReefVisionNoReparseAncestors -Path $Cab.FullName')) 'MSI verifier does not reject reparse-point CAB paths.'
Assert-True ($msiVerifier.IndexOf('Assert-ReefVisionNoReparseAncestors -Path $Msi.FullName') -lt $msiVerifier.IndexOf('OpenDatabase($Msi.FullName, 0)')) 'MSI reparse-point guard must run before opening the database.'


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
$acceptanceScript = Get-Content -LiteralPath $acceptancePath -Raw
Assert-True ($acceptanceScript.Contains('Assert-ReefVisionMsiCompletedWithoutReboot -Action $Action -ExitCode $process.ExitCode -LogPath $log')) 'MSI runner must reject reboot-required exit codes before recording PASS.'
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
Assert-True ($acceptanceScript.Contains('-AllowLiveSam2Network:$LiveSam2Acceptance')) 'Live SAM network opt-in must be explicitly scoped to the requested acceptance mode.'
Assert-True ($acceptanceScript.Contains('samAcceptedMaskId')) 'Live SAM acceptance must validate mask preservation.'
Assert-True ($acceptanceScript.Contains("'api.log', 'api.log.1'")) 'Failed SAM2 acceptance must archive API logs, not only startup backend.log.'
Assert-True ($acceptanceScript.Contains('api.log.tail.log') -or $acceptanceScript.Contains('$logName.tail.log')) 'SAM2 API log archive name must match the uploaded *.log evidence pattern.'
Assert-True ($acceptanceScript.Contains('$expectedInitialVersion')) 'Acceptance must verify which MSI version launched before upgrade.'
Assert-True ($acceptanceScript.Contains('$postUpgradeVersion')) 'Acceptance must read the packaged API version after upgrade.'
Assert-True ($acceptanceScript.Contains('Post-upgrade API version')) 'Upgrade must fail when the packaged API version did not change to the candidate.'
Assert-True ($acceptanceScript -match 'Stop-AcceptanceDesktop\s+\$desktop\s*\r?\n\s*\$projectChecksum\s*=\s*\(Get-FileHash\s+-LiteralPath\s+\(Join-Path\s+\$DataRoot\s+''reefvision\.db''\)') 'Desktop shutdown must occur before hashing reefvision.db.'
Assert-True ($acceptanceScript -match 'Where-Object\s+FullName\s+-eq\s+''reefvision-exchange-manifest\.json''') 'Project Exchange validation does not require the canonical manifest name.'
Assert-True ($acceptanceScript -notmatch 'Where-Object\s+FullName\s+-eq\s+''manifest\.json''') 'Project Exchange validation still accepts the incorrect manifest.json name.'

# Release evidence must not turn skipped upgrade, real-camera, or uninstall
# checks into a false clean-install PASS. No installer is launched here.
$requiredAcceptanceFields = @(
    'install', 'shortcuts', 'first_launch', 'frontend_backend_connectivity',
    'model_policy', 'external_annotation_imports', 'camera_jpeg',
    'project_persistence', 'restart', 'project_exchange',
    'upgrade', 'uninstall', 'data_retention'
)
$installerDigest = ('A' * 64) # Synthetic digest; never represents a tested MSI.
$completeEvidence = @{ installer_sha256 = $installerDigest }
foreach ($name in $requiredAcceptanceFields) {
    $completeEvidence[$name] = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Recorded observation for $name"
}
Assert-True (@(Get-ReefVisionAutomatedAcceptanceGaps -Report $completeEvidence).Count -eq 0) 'All required automated MSI gates should permit a complete report.'
# Automated installer smoke evidence must never imply physical release
# readiness. Require separately timestamped WebView2, read-only live training,
# GPU/scientific, Canon EOS and Sony A7R observations; skipped/missing gates fail closed.
$releaseGaps = @(Get-ReefVisionReleaseAcceptanceGaps -Report $completeEvidence)
Assert-True ($releaseGaps.Count -eq 5) 'Automated MSI PASS alone must not certify release readiness.'
foreach ($name in @('webview2_gui', 'training_console', 'gpu_scientific', 'canon_camera', 'sony_camera')) {
    Assert-True ($releaseGaps -ccontains "${name}: MISSING") "Release readiness must require $name evidence."
    $completeEvidence[$name] = New-ReefVisionEvidenceResult -Status 'PASS' -Detail "Physical acceptance observation for $name" -InstallerSha256 $installerDigest
}
Assert-True (@(Get-ReefVisionReleaseAcceptanceGaps -Report $completeEvidence).Count -eq 0) 'Complete timestamped release evidence should satisfy all release gates.'
# One tested camera cannot substitute for the other; each needs independent evidence.
$completeEvidence['sony_camera'] = New-ReefVisionEvidenceResult -Status 'NOT RUN' -Detail 'Sony camera not physically available'
Assert-True (@(Get-ReefVisionReleaseAcceptanceGaps -Report $completeEvidence) -ccontains 'sony_camera: NOT RUN') 'Canon PASS must not certify untested Sony hardware.'
$completeEvidence['sony_camera'] = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Observed Sony A7R JPEG orientation and unchanged original hash' -InstallerSha256 $installerDigest
$completeEvidence['canon_camera'].timestamp_utc = '2026-11-01T12:00:00.0000000-06:00'
Assert-True (@(Get-ReefVisionReleaseAcceptanceGaps -Report $completeEvidence) -ccontains 'canon_camera: INVALID TIMESTAMP') 'Non-UTC Canon evidence must not certify release.'
$completeEvidence['canon_camera'] = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Observed Canon EOS JPEG orientation and unchanged original hash' -InstallerSha256 $installerDigest
Assert-True (@(Get-ReefVisionReleaseAcceptanceGaps -Report $completeEvidence).Count -eq 0) 'Restored independent camera evidence should satisfy release gates.'
$completeEvidence['training_console'].status = 'NOT RUN'
Assert-True (@(Get-ReefVisionReleaseAcceptanceGaps -Report $completeEvidence) -ccontains 'training_console: NOT RUN') 'Unobserved live training must block release readiness.'
$completeEvidence['training_console'] = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Observed live box/cls/dfl losses without interruption' -InstallerSha256 $installerDigest
$completeEvidence['webview2_gui'].detail = ' '
Assert-True (@(Get-ReefVisionReleaseAcceptanceGaps -Report $completeEvidence) -ccontains 'webview2_gui: MISSING DETAIL') 'WebView2 PASS without observations must not certify release readiness.'
$completeEvidence['webview2_gui'] = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Observed installed image navigation and annotation' -InstallerSha256 $installerDigest
$completeEvidence['gpu_scientific'].timestamp_utc = [DateTime]::UtcNow.AddDays(1).ToString('o')
Assert-True (@(Get-ReefVisionReleaseAcceptanceGaps -Report $completeEvidence) -ccontains 'gpu_scientific: INVALID TIMESTAMP') 'Future GPU/scientific acceptance evidence must be rejected.'
$completeEvidence['gpu_scientific'] = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Observed local GPU scientific workflow' -InstallerSha256 $installerDigest
Assert-True (@(Get-ReefVisionReleaseAcceptanceGaps -Report $completeEvidence).Count -eq 0) 'Restored release evidence should satisfy release gates.'

# Physical observations from another MSI cannot certify this candidate.
# These are synthetic report records only; no hardware is exercised.
$completeEvidence['webview2_gui'].installer_sha256 = ('B' * 64)
Assert-True (@(Get-ReefVisionReleaseAcceptanceGaps -Report $completeEvidence) -ccontains 'webview2_gui: INSTALLER SHA256 MISMATCH') 'Physical WebView2 PASS from another installer must not certify this MSI.'
$completeEvidence['webview2_gui'].Remove('installer_sha256')
Assert-True (@(Get-ReefVisionReleaseAcceptanceGaps -Report $completeEvidence) -ccontains 'webview2_gui: MISSING OR INVALID INSTALLER SHA256') 'Physical PASS without a candidate MSI hash must fail closed.'
$completeEvidence['webview2_gui'] = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Observed installed image navigation and annotation' -InstallerSha256 $installerDigest
$completeEvidence['installer_sha256'] = ('B' * 64)
Assert-True (@(Get-ReefVisionReleaseAcceptanceGaps -Report $completeEvidence) -ccontains 'canon_camera: INSTALLER SHA256 MISMATCH') 'Reusing physical Canon evidence against a new candidate MSI must fail.'
$completeEvidence['installer_sha256'] = 'not-a-sha256'
Assert-True (@(Get-ReefVisionReleaseAcceptanceGaps -Report $completeEvidence) -ccontains 'installer_sha256: MISSING OR INVALID') 'Malformed candidate MSI hash must block release readiness.'
$completeEvidence['installer_sha256'] = $installerDigest
$completeEvidence['sony_camera'].installer_sha256 = $installerDigest.ToLowerInvariant()
Assert-True (@(Get-ReefVisionReleaseAcceptanceGaps -Report $completeEvidence).Count -eq 0) 'SHA-256 case differences must not invalidate the same MSI.'
$completeEvidence['sony_camera'].installer_sha256 = $installerDigest
$persistedRelease = $completeEvidence | ConvertTo-Json -Depth 8 | ConvertFrom-Json
Assert-True (@(Get-ReefVisionReleaseAcceptanceGaps -Report $persistedRelease).Count -eq 0) 'JSON-persisted physical evidence must retain candidate MSI provenance.'
$persistedRelease.PSObject.Properties.Remove('installer_sha256')
Assert-True (@(Get-ReefVisionReleaseAcceptanceGaps -Report $persistedRelease) -ccontains 'installer_sha256: MISSING OR INVALID') 'Missing installer hash in persisted JSON must fail closed.'
$persistedRelease = $completeEvidence | ConvertTo-Json -Depth 8 | ConvertFrom-Json
$persistedRelease.canon_camera.PSObject.Properties.Remove('installer_sha256')
Assert-True (@(Get-ReefVisionReleaseAcceptanceGaps -Report $persistedRelease) -ccontains 'canon_camera: MISSING OR INVALID INSTALLER SHA256') 'Missing physical camera hash in persisted JSON must fail closed.'

Assert-True ($acceptanceScript.Contains('release_acceptance_complete = $false')) 'Acceptance report must initialize release readiness as false.'
Assert-True ($acceptanceScript.Contains('training_console = New-ReefVisionEvidenceResult')) 'Acceptance report must explicitly track live training telemetry.'
Assert-True ($acceptanceScript.Contains('canon_camera = New-ReefVisionEvidenceResult')) 'Acceptance report must initialize unverified Canon physical-camera evidence.'
Assert-True ($acceptanceScript.Contains('sony_camera = New-ReefVisionEvidenceResult')) 'Acceptance report must initialize unverified Sony physical-camera evidence.'
Assert-True ($acceptanceScript.Contains('Get-ReefVisionReleaseAcceptanceGaps -Report $report')) 'Acceptance must calculate physical release gaps separately from automated MSI smoke checks.'
# Evidence survives JSON persistence; a naked PASS, missing time, or malformed
# record must never be accepted as verified clean-install evidence.
$persistedEvidence = $completeEvidence | ConvertTo-Json -Depth 8 | ConvertFrom-Json
Assert-True (@(Get-ReefVisionAutomatedAcceptanceGaps -Report $persistedEvidence).Count -eq 0) 'Persisted JSON evidence should retain valid gate provenance.'
# ConvertFrom-Json can turn ISO-8601 text into DateTime objects. Require
# explicit UTC kind, and never infer UTC from a local or unspecified time.
$typedUtcEvidence = $completeEvidence | ConvertTo-Json -Depth 8 | ConvertFrom-Json
$typedUtcEvidence.camera_jpeg.timestamp_utc = [DateTime]::UtcNow
Assert-True (@(Get-ReefVisionAutomatedAcceptanceGaps -Report $typedUtcEvidence).Count -eq 0) 'Typed UTC DateTime must retain valid persisted evidence.'
$typedUtcEvidence.camera_jpeg.timestamp_utc = [DateTimeOffset]::UtcNow
Assert-True (@(Get-ReefVisionAutomatedAcceptanceGaps -Report $typedUtcEvidence).Count -eq 0) 'Typed UTC DateTimeOffset must retain valid evidence.'
foreach ($nonUtcKind in @([DateTimeKind]::Local, [DateTimeKind]::Unspecified)) {
    $typedUtcEvidence.camera_jpeg.timestamp_utc = [DateTime]::SpecifyKind([DateTime]::UtcNow, $nonUtcKind)
    Assert-True (@(Get-ReefVisionAutomatedAcceptanceGaps -Report $typedUtcEvidence) -ccontains 'camera_jpeg: INVALID TIMESTAMP') "Typed $nonUtcKind DateTime cannot prove UTC evidence."
}
$typedUtcEvidence.camera_jpeg.timestamp_utc = [DateTimeOffset]::new(2026, 11, 1, 12, 0, 0, [TimeSpan]::FromHours(5))
Assert-True (@(Get-ReefVisionAutomatedAcceptanceGaps -Report $typedUtcEvidence) -ccontains 'camera_jpeg: INVALID TIMESTAMP') 'Typed non-UTC DateTimeOffset must be rejected.'
# UTC DateTime ('Z') and UTC DateTimeOffset ('+00:00') are both legitimate
# serialized acceptance evidence. Other offsets and offsetless strings must
# not be silently interpreted as UTC scientific/installation provenance.
$completeEvidence['camera_jpeg'].timestamp_utc = [DateTimeOffset]::UtcNow.ToString('o')
Assert-True (@(Get-ReefVisionAutomatedAcceptanceGaps -Report $completeEvidence).Count -eq 0) 'Canonical +00:00 UTC evidence must be accepted.'
# A report cannot certify an installation before its observation time.
# Tolerate minor host clock drift, but reject fabricated future PASS evidence.
$completeEvidence['camera_jpeg'].timestamp_utc = [DateTime]::UtcNow.AddDays(1).ToString('o')
Assert-True (@(Get-ReefVisionAutomatedAcceptanceGaps -Report $completeEvidence) -ccontains 'camera_jpeg: INVALID TIMESTAMP') 'Future-dated string acceptance evidence must fail.'
$completeEvidence['camera_jpeg'].timestamp_utc = [DateTimeOffset]::UtcNow.AddDays(1)
Assert-True (@(Get-ReefVisionAutomatedAcceptanceGaps -Report $completeEvidence) -ccontains 'camera_jpeg: INVALID TIMESTAMP') 'Future-dated typed UTC acceptance evidence must fail.'
$completeEvidence['camera_jpeg'].timestamp_utc = [DateTime]::UtcNow.AddMinutes(2).ToString('o')
Assert-True (@(Get-ReefVisionAutomatedAcceptanceGaps -Report $completeEvidence).Count -eq 0) 'Small acceptance host clock skew should be tolerated.'
foreach ($badTimestamp in @(
    '2026-11-01T12:00:00.0000000+05:00',
    '2026-11-01T12:00:00.0000000',
    '2026-02-30T12:00:00.0000000Z',
    '2026-11-01T12:00:00.0000000z'
)) {
    $completeEvidence['camera_jpeg'].timestamp_utc = $badTimestamp
    Assert-True (@(Get-ReefVisionAutomatedAcceptanceGaps -Report $completeEvidence) -ccontains 'camera_jpeg: INVALID TIMESTAMP') "Noncanonical or invalid UTC acceptance timestamp must be rejected: $badTimestamp"
}
$completeEvidence['camera_jpeg'].timestamp_utc = [DateTime]::UtcNow.ToString('o')
$completeEvidence['camera_jpeg'].detail = '  '
Assert-True (@(Get-ReefVisionAutomatedAcceptanceGaps -Report $completeEvidence) -ccontains 'camera_jpeg: MISSING DETAIL') 'PASS without an observation must not count as camera acceptance.'
$completeEvidence['camera_jpeg'].detail = 'Recorded camera import and original hash'
$completeEvidence['camera_jpeg'].timestamp_utc = 'not-a-time'
Assert-True (@(Get-ReefVisionAutomatedAcceptanceGaps -Report $completeEvidence) -ccontains 'camera_jpeg: INVALID TIMESTAMP') 'PASS without a valid timestamp must not count as camera acceptance.'
$completeEvidence['camera_jpeg'].timestamp_utc = [DateTime]::UtcNow.ToString('o')
$completeEvidence['camera_jpeg'] = [ordered]@{ status = 'PASS' }
$missingProvenance = @(Get-ReefVisionAutomatedAcceptanceGaps -Report $completeEvidence)
Assert-True ($missingProvenance -ccontains 'camera_jpeg: MISSING DETAIL') 'Missing observation field must fail closed.'
Assert-True ($missingProvenance -ccontains 'camera_jpeg: INVALID TIMESTAMP') 'Missing timestamp field must fail closed.'
$completeEvidence['camera_jpeg'] = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Recorded camera import and original hash'
$completeEvidence['upgrade'] = New-ReefVisionEvidenceResult -Status 'SKIPPED'
$completeEvidence['camera_jpeg'] = New-ReefVisionEvidenceResult -Status 'SKIPPED'
$completeEvidence['uninstall'] = New-ReefVisionEvidenceResult -Status 'NOT RUN'
$gaps = @(Get-ReefVisionAutomatedAcceptanceGaps -Report $completeEvidence)
Assert-True ($gaps.Count -eq 3) 'Skipped camera, upgrade and uninstall evidence must each block automated acceptance.'
foreach ($expectedGap in @('camera_jpeg: SKIPPED', 'upgrade: SKIPPED', 'uninstall: NOT RUN')) {
    Assert-True ($gaps -ccontains $expectedGap) "Missing release evidence gap: $expectedGap"
}
$completeEvidence.Remove('model_policy')
Assert-True (@(Get-ReefVisionAutomatedAcceptanceGaps -Report $completeEvidence) -ccontains 'model_policy: MISSING') 'Missing model-policy evidence must fail closed.'
Assert-True ($acceptanceScript.Contains('webview2_gui = New-ReefVisionEvidenceResult')) 'Acceptance must explicitly record untested installed WebView2 GUI.'
Assert-True ($acceptanceScript.Contains('gpu_scientific = New-ReefVisionEvidenceResult')) 'Acceptance must explicitly record untested physical GPU/scientific workflows.'
Assert-True ($acceptanceScript.Contains('automated_acceptance_complete')) 'Acceptance report must distinguish full automated evidence from partial tests.'

$reportPath = Join-Path $Root ('.artifacts\reefvision-evidence-' + [guid]::NewGuid().ToString('N') + '.json')
$report = [ordered]@{ upgrade = New-ReefVisionEvidenceResult -Status 'SKIPPED' -Detail 'previous installer not supplied'; failure_reason = $null }
Write-ReefVisionEvidenceReport -Report $report -Path $reportPath
$roundTrip = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
Assert-True ($roundTrip.upgrade.status -eq 'SKIPPED') 'Report did not preserve skip semantics.'
Assert-True ($null -eq $roundTrip.failure_reason) 'Report did not preserve an empty failure reason.'
if (-not (Test-ReefVisionPathWithin -Path $reportPath -Parent (Join-Path $Root '.artifacts'))) { throw 'Unsafe harness report cleanup path.' }
Remove-Item -LiteralPath $reportPath -Force

$cleanupRoot = Join-Path $Root ('.artifacts\harness-cleanup-' + [guid]::NewGuid().ToString('N'))
$token = [guid]::NewGuid().ToString('N').Substring(0, 12)
$ownedRun = Join-Path $cleanupRoot "reefvision-clean-$token"
$foreign = Join-Path $cleanupRoot 'foreign'
New-Item -ItemType Directory -Path $ownedRun,$foreign -Force | Out-Null
$marker = Join-Path $ownedRun '.reefvision-acceptance-run'
Set-Content -LiteralPath $marker -Value $token
Assert-Throws { Assert-ReefVisionOwnedAcceptanceRun -RunRoot $foreign -AcceptanceRoot $cleanupRoot -Token $token } 'Cleanup must reject an unrelated directory.'
Assert-Throws { Assert-ReefVisionOwnedAcceptanceRun -RunRoot $ownedRun -AcceptanceRoot $cleanupRoot -Token 'not-a-token' } 'Cleanup must reject malformed ownership tokens.'
Set-Content -LiteralPath $marker -Value 'foreign-owner'
Assert-Throws { Assert-ReefVisionOwnedAcceptanceRun -RunRoot $ownedRun -AcceptanceRoot $cleanupRoot -Token $token } 'Cleanup must reject a mismatched ownership marker.'
Remove-Item -LiteralPath $marker -Force
Assert-Throws { Assert-ReefVisionOwnedAcceptanceRun -RunRoot $ownedRun -AcceptanceRoot $cleanupRoot -Token $token } 'Cleanup must reject a missing ownership marker.'
Set-Content -LiteralPath $marker -Value $token
Add-Content -LiteralPath $marker -Value 'unexpected-extra-line'
Assert-Throws { Assert-ReefVisionOwnedAcceptanceRun -RunRoot $ownedRun -AcceptanceRoot $cleanupRoot -Token $token } 'Cleanup must reject a marker with additional content.'
Set-Content -LiteralPath $marker -Value $token
$junctionToken = [guid]::NewGuid().ToString('N').Substring(0, 12)
$junctionRun = Join-Path $cleanupRoot "reefvision-clean-$junctionToken"
Set-Content -LiteralPath (Join-Path $foreign '.reefvision-acceptance-run') -Value $junctionToken
try {
    New-Item -ItemType Junction -Path $junctionRun -Target $foreign -ErrorAction Stop | Out-Null
    Assert-Throws { Assert-ReefVisionOwnedAcceptanceRun -RunRoot $junctionRun -AcceptanceRoot $cleanupRoot -Token $junctionToken } 'Cleanup must reject a swapped-in junction even when its marker matches.'
} finally {
    if ([System.IO.Directory]::Exists($junctionRun)) { [System.IO.Directory]::Delete($junctionRun) }
}
# A valid ownership marker must not authorize recursive deletion through a
# junction planted deeper in the disposable run after initial validation.
$nestedDir = Join-Path $ownedRun 'nested'
New-Item -ItemType Directory -Path $nestedDir -Force | Out-Null
$nestedJunction = Join-Path $nestedDir 'external-data'
$foreignSentinel = Join-Path $foreign 'must-survive.txt'
Set-Content -LiteralPath $foreignSentinel -Value 'outside the disposable run'
try {
    New-Item -ItemType Junction -Path $nestedJunction -Target $foreign -ErrorAction Stop | Out-Null
    Assert-Throws { Assert-ReefVisionOwnedAcceptanceRun -RunRoot $ownedRun -AcceptanceRoot $cleanupRoot -Token $token } 'Cleanup must reject a nested junction even with a valid run marker.'
} finally {
    if ([System.IO.Directory]::Exists($nestedJunction)) { [System.IO.Directory]::Delete($nestedJunction) }
}
Assert-True (Test-Path -LiteralPath $foreignSentinel -PathType Leaf) 'Nested-junction guard must not modify external data.'
Assert-ReefVisionOwnedAcceptanceRun -RunRoot $ownedRun -AcceptanceRoot $cleanupRoot -Token $token
Assert-True (Test-Path -LiteralPath $ownedRun -PathType Container) 'Ownership validation must not delete the run.'
if (-not (Test-ReefVisionPathWithin -Path $ownedRun -Parent (Join-Path $Root '.artifacts'))) { throw 'Unsafe harness test cleanup path.' }
Remove-Item -LiteralPath $ownedRun -Recurse -Force
Assert-True (-not (Test-Path $ownedRun)) 'Owned run was not removed.'
Assert-True (Test-Path $foreign) 'Cleanup crossed the owned-run boundary.'
if (-not (Test-ReefVisionPathWithin -Path $cleanupRoot -Parent (Join-Path $Root '.artifacts'))) { throw 'Unsafe harness test cleanup root.' }
Remove-Item -LiteralPath $cleanupRoot -Recurse -Force

Write-Host "Windows clean-install harness unit tests passed: $passed assertions." -ForegroundColor Green
