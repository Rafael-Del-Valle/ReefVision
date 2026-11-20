param([Parameter(Mandatory)][string]$Scratch)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (Test-Path -LiteralPath $Scratch) { throw 'Use a fresh test directory.' }
. (Join-Path $PSScriptRoot 'webview-handoff.ps1')

$cache = Join-Path $Scratch 'profile-webview2'
New-Item -ItemType Directory -Path $cache | Out-Null
$file = Join-Path $cache 'synthetic-browser-cache'
Set-Content -LiteralPath $file -Value 'fixture'
$stream = [IO.File]::Open($file,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::Read)
$clock = [Diagnostics.Stopwatch]::StartNew()
try {
    $handoff = Move-OfflineWebViewCache -Root $Scratch -TimeoutSeconds 5 -GetLivePids {
        if ($clock.ElapsedMilliseconds -lt 400) { return 8123 }
        if ($clock.ElapsedMilliseconds -ge 1100) { $stream.Dispose() }
    }
} finally { $stream.Dispose() }
if ($handoff.sharing_violations -lt 1 -or $handoff.wait_seconds -lt 1 -or -not $handoff.cache_archived -or
    -not (Test-Path -LiteralPath (Join-Path $Scratch 'first-profile-webview2/synthetic-browser-cache'))) {
    throw 'A real Windows file-share lock was not retried after the owned process wait.'
}

$timeoutRoot = Join-Path $Scratch 'bounded-timeout'
New-Item -ItemType Directory (Join-Path $timeoutRoot 'profile-webview2') | Out-Null
try {
    Move-OfflineWebViewCache -Root $timeoutRoot -TimeoutSeconds 1 -GetLivePids { 1124 }
    throw 'Moved the cache while an owned process was still running.'
} catch {
    if ($_.Exception.Message -notmatch '1 live, 0 sharing failures') { throw }
}

# Test process identity without enumerating or terminating apps on the host.
$ordinarySid = 'S-1-5-21-1-2-3-4'
$profile = [IO.Path]::GetFullPath((Join-Path $Scratch 'profile-webview2'))
$birth = [DateTime]::UtcNow
function New-MockWebView($PidValue,$Parent,$Owner,$Arguments,$Birth) {
    [pscustomobject]@{
        Name='msedgewebview2.exe'; ProcessId=$PidValue; ParentProcessId=$Parent
        CreationDate=$Birth; CommandLine=$Arguments; Owner=$Owner
    }
}
$mock = @(
    (New-MockWebView 8100 8000 $ordinarySid "--user-data-dir=$profile" $birth)
    (New-MockWebView 8101 8100 $ordinarySid '--type=renderer' $birth)
    (New-MockWebView 8102 8300 $ordinarySid "--user-data-dir=`"$profile-other`"" $birth)
    (New-MockWebView 8103 0 $ordinarySid "--user-data-dir=`"$profile`"" $birth)
    (New-MockWebView 8104 0 'S-1-5-18' "--user-data-dir=`"$profile`"" $birth)
)
function Get-NetTCPConnection { param($LocalPort,$State); [pscustomobject]@{LocalAddress='127.0.0.1';OwningProcess=8100} }
function Get-CimInstance {
    param($Class,$Filter)
    if ($Filter -match 'ProcessId = (\d+)') { $mock | Where-Object ProcessId -eq ([int]$Matches[1]); return }
    $mock
}
function Invoke-CimMethod { [CmdletBinding()]param($InputObject,$MethodName); [pscustomobject]@{ReturnValue=0;Sid=$InputObject.Owner} }
$scope = New-OfflineWebViewScope -Port 8888 -DesktopProcessId 8000 -Sid $ordinarySid -Root $Scratch
if ((@(Get-OfflineWebViewProcesses $scope) -join ',') -cne '8100,8101,8103') { throw 'Owned child or exact profile scope incorrectly recognized.' }
$mock = @((New-MockWebView 8100 0 $ordinarySid '--unrelated' ($birth.AddSeconds(4))))
if (@(Get-OfflineWebViewProcesses $scope).Count) { throw 'A recycled PID was treated as first-launch ownership.' }
'Passed the Windows sharing-lock retry, bounded owned PID wait and exact profile/PID ownership checks.'
