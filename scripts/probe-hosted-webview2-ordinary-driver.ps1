param([Parameter(Mandatory)][string]$ContextFile,[switch]$FreshOrdinaryChild)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$context = Get-Content -LiteralPath $ContextFile -Raw | ConvertFrom-Json
$stage = Join-Path $context.output 'ordinary-driver-stage.txt'
Set-Content -LiteralPath $stage -Value 'entered'
$driverTemp = Join-Path $context.output 'driver-temp'
New-Item -ItemType Directory -Path $driverTemp -Force | Out-Null
$env:TEMP = $driverTemp
$env:TMP = $driverTemp
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
if ($identity.User.Value -ne $context.user_sid -or
    ([System.Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'The diagnostic driver did not run as the ordinary browser account.'
}
. (Join-Path $PSScriptRoot 'windows-standard-user-webview2.ps1')
Set-Content -LiteralPath $stage -Value 'verified-ordinary-user'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ReefVisionOrdinaryKnownFolder {
    [DllImport("shell32")] static extern int SHGetKnownFolderPath(ref Guid id, uint flags, IntPtr token, out IntPtr path);
    public static string Get(string folderId, IntPtr token) {
        Guid id = new Guid(folderId);
        IntPtr path;
        int result = SHGetKnownFolderPath(ref id, 0x4000, token, out path);
        if (result != 0) Marshal.ThrowExceptionForHR(result);
        try { return Marshal.PtrToStringUni(path); }
        finally { Marshal.FreeCoTaskMem(path); }
    }
}
'@
$downloadsId = '374DE290-123F-4565-9164-39C4925E467B'
$documentsId = 'FDD39AD0-238F-46AF-ADB4-6C85480369C7'
$launchRecordPath = Join-Path $context.output 'ordinary-driver-environment.json'
if (-not $FreshOrdinaryChild) {
    $inheritedProfile = $env:USERPROFILE
    $inheritedDownloads = [ReefVisionOrdinaryKnownFolder]::Get($downloadsId,[IntPtr]::Zero)
    $inheritedDocuments = [ReefVisionOrdinaryKnownFolder]::Get($documentsId,[IntPtr]::Zero)
    $ordinaryProfile = Set-ReefVisionHostedUserProfile $identity
    $registryPath = 'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders'
    $ordinaryShell = [Microsoft.Win32.Registry]::Users.OpenSubKey("$($identity.User.Value)\$registryPath")
    try {
        $registryDownloads = if ($ordinaryShell) {
            $ordinaryShell.GetValue("{$downloadsId}",$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        }
    } finally {
        if ($ordinaryShell) { $ordinaryShell.Dispose() }
    }
    [ordered]@{
        inherited_user_profile=$inheritedProfile; inherited_known_downloads=$inheritedDownloads
        inherited_known_documents=$inheritedDocuments; ordinary_user_profile=$ordinaryProfile
        ordinary_shell_downloads_raw_value=$registryDownloads
    } | ConvertTo-Json | Set-Content -LiteralPath $launchRecordPath
    & (Get-Process -Id $PID).Path -NoProfile -NonInteractive -File $PSCommandPath -ContextFile $ContextFile -FreshOrdinaryChild
    exit $LASTEXITCODE
}
$ordinaryProfile = $env:USERPROFILE
$downloads = [ReefVisionOrdinaryKnownFolder]::Get($downloadsId,[IntPtr]::Zero)
$documents = [ReefVisionOrdinaryKnownFolder]::Get($documentsId,[IntPtr]::Zero)
$tokenDownloads = $null
$tokenDownloadsError = $null
try { $tokenDownloads = [ReefVisionOrdinaryKnownFolder]::Get($downloadsId,$identity.Token) } catch { $tokenDownloadsError = $_.Exception.Message }
Set-Content -LiteralPath $stage -Value 'resolved-downloads'
$knownFolderInProfile = $downloads.StartsWith($ordinaryProfile + '\',[System.StringComparison]::OrdinalIgnoreCase)
$candidateFolder = if ($knownFolderInProfile) { $downloads } else { Join-Path $ordinaryProfile 'Downloads' }
$knownFolderExists = Test-Path -LiteralPath $candidateFolder -PathType Container
$knownFolderWritable = $false
if ($knownFolderExists) {
    $knownFolderProbe = Join-Path $candidateFolder ('reefvision-probe-' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        Set-Content -LiteralPath $knownFolderProbe -Value 'synthetic test'
        $knownFolderWritable = (Get-Content -LiteralPath $knownFolderProbe -Raw).Trim() -eq 'synthetic test'
    } catch {
        $knownFolderWritable = $false
    } finally {
        if (Test-Path -LiteralPath $knownFolderProbe -PathType Leaf) { Remove-Item -LiteralPath $knownFolderProbe }
    }
}
$sentinel = Join-Path $context.browser_artifacts 'standard-account-write-test.txt'
$artifactsWritable = $false
try {
    Set-Content -LiteralPath $sentinel -Value 'synthetic test'
    $artifactsWritable = (Get-Content -LiteralPath $sentinel -Raw).Trim() -eq 'synthetic test'
} catch {}
[ordered]@{
    driver_pid=$PID
    user_sid=$identity.User.Value
    integrity=Get-ReefVisionProcessIntegrity (Get-Process -Id $PID)
    ordinary_user_profile=$ordinaryProfile
    known_documents=$documents
    known_downloads=$downloads
    known_downloads_in_ordinary_profile=$knownFolderInProfile
    token_downloads=$tokenDownloads
    token_downloads_error=$tokenDownloadsError
    ordinary_download_folder_checked=$candidateFolder
    known_downloads_exists=$knownFolderExists
    known_downloads_writable=$knownFolderWritable
    dedicated_browser_artifacts=$context.browser_artifacts
    dedicated_browser_artifacts_writable=$artifactsWritable
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $context.output 'ordinary-driver-identity.json')
Set-Content -LiteralPath $stage -Value 'starting-playwright'
$env:REEFVISION_GUIDED_TEST_API=$context.api
$env:REEFVISION_SPATIAL_WEBVIEW2_ENDPOINT=$context.endpoint
$env:REEFVISION_SPATIAL_WEBVIEW2_ARTIFACTS_DIR=$context.browser_artifacts
$env:REEFVISION_PROBE_ORDINARY_DOWNLOADS=$candidateFolder
$env:PLAYWRIGHT_JSON_OUTPUT_FILE=Join-Path $context.output 'ordinary-project-playwright.json'
$env:DEBUG='pw:protocol'
Push-Location -LiteralPath $context.web
try {
    & $context.node ./node_modules/@playwright/test/cli.js test ordinary-project-live.spec.ts --workers=1 --retries=0 --reporter=list,json --trace=off "--output=$($context.output)/playwright"
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
