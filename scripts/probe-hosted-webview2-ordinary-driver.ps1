param([Parameter(Mandatory)][string]$ContextFile)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$context = Get-Content -LiteralPath $ContextFile -Raw | ConvertFrom-Json
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
if ($identity.User.Value -ne $context.user_sid -or
    ([System.Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'The diagnostic driver did not run as the ordinary browser account.'
}
. (Join-Path $PSScriptRoot 'windows-standard-user-webview2.ps1')
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ReefVisionOrdinaryKnownFolder {
    [DllImport("shell32")] static extern int SHGetKnownFolderPath(ref Guid id, uint flags, IntPtr token, out IntPtr path);
    public static string Downloads() {
        Guid id = new Guid("FDD39AD0-238F-46AF-ADB4-6C85480369C7");
        IntPtr path;
        int result = SHGetKnownFolderPath(ref id, 0x4000, IntPtr.Zero, out path);
        if (result != 0) Marshal.ThrowExceptionForHR(result);
        try { return Marshal.PtrToStringUni(path); }
        finally { Marshal.FreeCoTaskMem(path); }
    }
}
'@
$downloads = [ReefVisionOrdinaryKnownFolder]::Downloads()
$knownFolderExists = Test-Path -LiteralPath $downloads -PathType Container
$knownFolderWritable = $false
if ($knownFolderExists) {
    $knownFolderProbe = Join-Path $downloads ('reefvision-probe-' + [guid]::NewGuid().ToString('N') + '.tmp')
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
    known_downloads=$downloads
    known_downloads_exists=$knownFolderExists
    known_downloads_writable=$knownFolderWritable
    dedicated_browser_artifacts=$context.browser_artifacts
    dedicated_browser_artifacts_writable=$artifactsWritable
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $context.output 'ordinary-driver-identity.json')
$env:REEFVISION_GUIDED_TEST_API=$context.api
$env:REEFVISION_SPATIAL_WEBVIEW2_ENDPOINT=$context.endpoint
$env:REEFVISION_SPATIAL_WEBVIEW2_ARTIFACTS_DIR=$context.browser_artifacts
$env:PLAYWRIGHT_JSON_OUTPUT_FILE=Join-Path $context.output 'ordinary-project-playwright.json'
$env:DEBUG='pw:protocol'
Push-Location -LiteralPath $context.web
try {
    & $context.node ./node_modules/@playwright/test/cli.js test ordinary-project-live.spec.ts --workers=1 --retries=0 --reporter=list,json --trace=off "--output=$($context.output)/playwright"
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
