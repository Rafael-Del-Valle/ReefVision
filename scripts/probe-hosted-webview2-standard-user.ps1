param(
    [Parameter(Mandatory)][string]$InstallerDirectory,
    [Parameter(Mandatory)][string]$EvidenceRoot
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

function Set-ProbeRestrictedPath {
    $env:PATH = @((Join-Path $env:SystemRoot 'System32'),$env:SystemRoot,(Join-Path $env:SystemRoot 'System32\Wbem'),(Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0')) -join ';'
}

if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or
    $env:GITHUB_REF_NAME -ne 'codex/reefvision-webview2-host-probe-20261120') {
    throw 'The temporary Windows test account is available only in its designated GitHub-hosted diagnostic job.'
}

. (Join-Path $PSScriptRoot 'lib/windows-clean-acceptance.ps1')
. (Join-Path $PSScriptRoot 'lib/windows-spatial-webview2-acceptance.ps1')
. (Join-Path $PSScriptRoot 'lib/windows-standard-user-webview2.ps1')
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
public static class ReefVisionProbeProcessToken {
    [DllImport("advapi32", SetLastError=true)] static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
    [DllImport("advapi32", SetLastError=true)] static extern bool GetTokenInformation(IntPtr token, int kind, IntPtr data, int size, out int required);
    [DllImport("advapi32")] static extern IntPtr GetSidSubAuthorityCount(IntPtr sid);
    [DllImport("advapi32")] static extern IntPtr GetSidSubAuthority(IntPtr sid, uint index);
    [DllImport("kernel32")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("user32")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
    [DllImport("user32")] static extern IntPtr GetThreadDesktop(uint thread);
    [DllImport("user32", CharSet=CharSet.Unicode)] static extern bool GetUserObjectInformation(IntPtr handle, int kind, StringBuilder value, uint length, out uint needed);
    public static string DesktopName(IntPtr window) {
        uint pid, needed;
        uint thread = GetWindowThreadProcessId(window, out pid);
        var name = new StringBuilder(256);
        IntPtr desktop = GetThreadDesktop(thread);
        return desktop != IntPtr.Zero && GetUserObjectInformation(desktop, 2, name, 512, out needed) ? name.ToString() : null;
    }
    public static int Integrity(IntPtr process) {
        const uint query = 8;
        const int tokenIntegrityLevel = 25;
        IntPtr token, buffer = IntPtr.Zero;
        if (!OpenProcessToken(process, query, out token)) throw new Win32Exception(Marshal.GetLastWin32Error());
        try {
            int len;
            GetTokenInformation(token, tokenIntegrityLevel, IntPtr.Zero, 0, out len);
            if (len <= 0) throw new Win32Exception(Marshal.GetLastWin32Error());
            buffer = Marshal.AllocHGlobal(len);
            if (!GetTokenInformation(token, tokenIntegrityLevel, buffer, len, out len)) throw new Win32Exception(Marshal.GetLastWin32Error());
            IntPtr sid = Marshal.ReadIntPtr(buffer);
            uint last = (uint)(Marshal.ReadByte(GetSidSubAuthorityCount(sid)) - 1);
            return Marshal.ReadInt32(GetSidSubAuthority(sid, last));
        } finally {
            if (buffer != IntPtr.Zero) Marshal.FreeHGlobal(buffer);
            CloseHandle(token);
        }
    }
}
'@

function Write-Probe([string]$Name, $Value) {
    $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $EvidenceRoot $Name)
}
function Run-ProbeMsi([string[]]$Arguments) {
    $process = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32/msiexec.exe') -ArgumentList $Arguments -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -notin @(0, 3010)) {
        throw "Windows installer probe operation failed with exit code $($process.ExitCode)."
    }
}
function Wait-ProbeFile([string]$Path, [int]$Seconds) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ([DateTime]::UtcNow -lt $deadline -and -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Start-Sleep -Milliseconds 250
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Missing probe completion file: $(Split-Path -Leaf $Path)." }
}
function Read-ProbeBrowserContext([int]$DesktopProcessId,[int]$DebugPort,[string]$UserSid,[string]$BrowserData) {
    $shell = Get-Process -Id $DesktopProcessId -ErrorAction Stop
    $browsers = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $DesktopProcessId AND Name = 'msedgewebview2.exe'")
    $rendererTypes = @('renderer','gpu-process','utility','other')
    $processes = @(foreach ($browser in $browsers) {
        $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($browser.ProcessId) AND Name = 'msedgewebview2.exe'")
        $typed = @($children | ForEach-Object {
            $kind = if ($_.CommandLine -match '(?:^|\s)--type=(renderer|gpu-process|utility)(?=$|\s)') { $Matches[1] } else { 'other' }
            [pscustomobject]@{kind=$kind;id=$_.ProcessId}
        })
        $counts = [ordered]@{}
        foreach ($kind in $rendererTypes) { $counts[$kind] = @($typed | Where-Object kind -EQ $kind).Count }
        [ordered]@{
            browser_pid=$browser.ProcessId; browser_path=$browser.ExecutablePath
            uses_isolated_user_data=$browser.CommandLine -match [regex]::Escape($BrowserData)
            arguments=Get-ReefVisionWebView2DiagnosticArguments $browser.CommandLine
            child_process_counts=$counts
        }
    })
    $policy = @(foreach ($base in @('HKLM:\SOFTWARE\Policies\Microsoft\Edge', "Registry::HKEY_USERS\$UserSid\Software\Policies\Microsoft\Edge")) {
        foreach ($scope in @($base,(Join-Path $base 'WebView2'))) {
            $settings = Get-ItemProperty -LiteralPath $scope -ErrorAction SilentlyContinue
            $presence = [ordered]@{}
            foreach ($name in 'DeveloperToolsAvailability','RemoteDebuggingAllowed','DownloadRestrictions','PromptForDownloadLocation','DefaultDownloadDirectory','DownloadDirectory') {
                $value = if ($settings) { $settings.PSObject.Properties[$name] } else { $null }
                $presence[$name] = if ($value -and $value.Value -is [int]) { $value.Value } elseif ($value) { 'configured' } else { $null }
            }
            $overrides = [ordered]@{}
            foreach ($name in 'AdditionalBrowserArguments','UserDataFolder','BrowserExecutableFolder') {
                $key = Get-Item -LiteralPath (Join-Path $scope $name) -ErrorAction SilentlyContinue
                $overrides[$name] = if ($key) { @($key.GetValueNames() | Where-Object { $_ -in @('*','ReefVision.exe') }) } else { @() }
            }
            [ordered]@{scope=$scope;settings=$presence;application_or_global_override_names=$overrides}
        }
    })
    $tcp = [System.Net.Sockets.TcpClient]::new()
    $tcpConnected = $false
    try { $tcpConnected = $tcp.ConnectAsync('127.0.0.1',$DebugPort).Wait(1500) -and $tcp.Connected } catch {} finally { $tcp.Dispose() }
    $netstat = & (Join-Path $env:SystemRoot 'System32/netstat.exe') -ano -p tcp
    return [ordered]@{
        runner_image=$env:ImageOS; runner_image_version=$env:ImageVersion
        desktop_session=$shell.SessionId; local_thread_desktop=[ReefVisionProbeProcessToken]::DesktopName($shell.MainWindowHandle)
        hosted_browser_processes=$processes; read_only_browser_policy=$policy
        independent_loopback_connection=$tcpConnected
        netstat_expected_loopback_rows=@($netstat | Where-Object { $_ -match "^\s*TCP\s+127[.]0[.]0[.]1:${DebugPort}\s" })
    }
}

$expectedCommit='72254d9a021e31f02329146a949f3b5958ec7cdc'
$msi = Join-Path $InstallerDirectory 'ReefVision_1.4.0_x64_en-US.msi'
$receipt = & (Join-Path $PSScriptRoot 'verify-windows-installer-payload.ps1') -InstallerDirectory $InstallerDirectory -Version '1.4.0' -ExpectedFilename 'ReefVision_1.4.0_x64_en-US.msi' -SourceCommit $expectedCommit -RequireProvenance
$sha = (Get-FileHash -LiteralPath $msi -Algorithm SHA256).Hash.ToLowerInvariant()
if ($sha -cne '8ed1bd13462bf21c97348e2ff8b802a1cbf64a2192518e8eaa5e1b2ad77b3a54') { throw 'Unexpected retained 1.4 candidate MSI.' }
$node = (Get-Command node.exe -ErrorAction Stop).Source
$repo = Split-Path -Parent $PSScriptRoot

$token = [guid]::NewGuid().ToString('N').Substring(0,10)
$root = Join-Path $env:SystemDrive "rv-web-probe-$token"
$install = Join-Path $root 'app'
$profile = Join-Path $root 'data'
$webview2 = Join-Path $root 'data-webview2'
New-Item -ItemType Directory -Path $EvidenceRoot,$root,$profile | Out-Null
Set-Content -LiteralPath (Join-Path $root '.reefvision-acceptance-run') -Value $token
Set-Content -LiteralPath (Join-Path $profile '.reefvision-clean-install-acceptance') -Value $token
$productCode = [string]$receipt.identity.ProductCode
foreach ($key in @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$productCode",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$productCode"
)) {
    if (Test-Path -LiteralPath $key) { throw 'The retained probe candidate must not already be installed.' }
}
$installLog = Join-Path $root 'msi-install.log'
$uninstallLog = Join-Path $root 'msi-uninstall.log'
$desktopPath = Join-Path $install 'ReefVision.exe'
$account = $null
$desktop = $null
$debugPort = $null
$registered = $false
$cleanup = [ordered]@{desktop_closed=$false;debug_port_closed=$false;uninstalled=$false;temporary_account_removed=$false;temporary_user_profile_removed=$false}
$driver = Get-Process -Id $PID
$driverIntegrity = [ReefVisionProbeProcessToken]::Integrity($driver.Handle)
if ($driverIntegrity -lt 12288) { throw 'The hosted installer and driver must be elevated for this experiment.' }
Write-Probe 'runner.json' ([ordered]@{ source_commit=$expectedCommit; msi_sha256=$sha; elevated_driver_integrity=$driverIntegrity; driver_session=$driver.SessionId })

try {
    Run-ProbeMsi -Arguments @('/i', ('"{0}"' -f $msi), '/qn', '/norestart', ('INSTALLDIR="{0}"' -f $install), '/l*v', ('"{0}"' -f $installLog))
    $registered = $true
    if (-not (Test-Path -LiteralPath $desktopPath -PathType Leaf)) { throw 'The exact probe MSI did not install ReefVision.exe in its disposable path.' }

    Set-ProbeRestrictedPath
    $account = New-ReefVisionHostedGuiAccount -RunRoot $root
    $sid = $account.sid.Value
    $debugPort = Get-ReefVisionLoopbackDebugPort
    $desktop = Start-ReefVisionHostedGui -Account $account -Executable $desktopPath -Profile $profile -DebugPort $debugPort -EvidenceRoot $EvidenceRoot

    $portFile = Join-Path $profile 'runtime/backend-port.txt'
    Wait-ProbeFile -Path $portFile -Seconds 120
    $api = "http://127.0.0.1:$((Get-Content -LiteralPath $portFile -Raw).Trim())/api/v1"
    $version = Invoke-RestMethod "$api/system/version" -NoProxy
    Write-Probe 'version.json' $version
    if ($version.application_version -ne '1.4.0' -or $version.current_schema_revision -ne 'b14_condition_0041' -or
        (Resolve-ReefVisionAcceptancePath $version.data_dir) -ine (Resolve-ReefVisionAcceptancePath $profile)) {
        throw 'The exact packaged sidecar did not bind to the designated test profile.'
    }
    $env:REEFVISION_GUIDED_TEST_API = $api
    $env:REEFVISION_SPATIAL_WEBVIEW2_ARTIFACTS_DIR = $account.browser_artifacts
    try {
        $env:REEFVISION_SPATIAL_WEBVIEW2_ENDPOINT = Wait-ReefVisionWebView2DebugEndpoint -Port $debugPort -DesktopProcessId $desktop.Id -FailureEvidencePath (Join-Path $EvidenceRoot 'spatial-webview2-startup.log') -AttachmentEvidencePath (Join-Path $EvidenceRoot 'spatial-webview2-attached.log') -ExpectedBrowserSid $sid
    } catch {
        Write-Probe 'browser-context.json' (Read-ProbeBrowserContext -DesktopProcessId $desktop.Id -DebugPort $debugPort -UserSid $sid -BrowserData $webview2)
        $uiaLog = Join-Path $EvidenceRoot 'uia.log'
        $uiaOutput = Join-Path $EvidenceRoot 'uia-output.json'
        $uiaArgs = '-NoProfile -NonInteractive -STA -File "{0}" -DesktopProcessId {1} -Api "{2}" -Evidence "{3}" -Name "{4}"' -f (Join-Path $PSScriptRoot 'probe-hosted-webview2-uia.ps1'),$desktop.Id,$api,$uiaOutput,("Ordinary native UI $token")
        $uia = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe') -ArgumentList $uiaArgs -PassThru -WindowStyle Hidden -RedirectStandardOutput $uiaLog -RedirectStandardError (Join-Path $EvidenceRoot 'uia-error.log')
        if (-not $uia.WaitForExit(40000)) { $uia.Kill(); $null=$uia.WaitForExit(10000) }
        throw
    }
    $listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $debugPort -State Listen
    $browser = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    $browserOwner = Invoke-CimMethod -InputObject $browser -MethodName GetOwnerSid
    $usesIsolatedBrowserData = $browser.CommandLine -match [regex]::Escape($webview2)
    Write-Probe 'loopback.json' ([ordered]@{
        local_address=$listener.LocalAddress; port=$debugPort; browser_pid=$browser.ProcessId; browser_parent=$browser.ParentProcessId
        browser_executable=$browser.ExecutablePath; strict_endpoint_attachment=$true
        browser_owner=$browserOwner.Sid; isolated_browser_user_data=$usesIsolatedBrowserData
        arguments=Get-ReefVisionWebView2DiagnosticArguments $browser.CommandLine
    })
    if ($browserOwner.ReturnValue -ne 0 -or $browserOwner.Sid -ne $sid -or -not $usesIsolatedBrowserData) {
        throw 'The owned WebView2 listener did not use the standard account and isolated browser data.'
    }
    Write-Probe 'browser-context.json' (Read-ProbeBrowserContext -DesktopProcessId $desktop.Id -DebugPort $debugPort -UserSid $sid -BrowserData $webview2)
    $driverRoot=Join-Path $root 'ordinary-driver'
    $driverOutput=Join-Path $driverRoot 'output'
    New-Item -ItemType Directory -Path $driverOutput | Out-Null
    $driverScript=Join-Path $driverRoot 'driver.ps1'
    $driverNode=Join-Path $driverRoot 'node.exe'
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'probe-hosted-webview2-ordinary-driver.ps1') -Destination $driverScript
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'lib/windows-standard-user-webview2.ps1') -Destination $driverRoot
    Copy-Item -LiteralPath $node -Destination $driverNode
    $web=Join-Path $repo 'apps/web'
    Grant-ReefVisionHostedGuiAccess -Path $web -Sid $account.sid -Rights 'RX'
    Grant-ReefVisionHostedGuiAccess -Path $driverOutput -Sid $account.sid -Rights 'M'
    $driverContext=Join-Path $driverRoot 'context.json'
    [ordered]@{
        api=$api; endpoint=$env:REEFVISION_SPATIAL_WEBVIEW2_ENDPOINT; browser_artifacts=$account.browser_artifacts
        user_sid=$sid; node=$driverNode; output=$driverOutput; web=$web
    } | ConvertTo-Json | Set-Content -LiteralPath $driverContext
    $protocolLog=Join-Path $driverOutput 'raw-protocol.log'
    $driverArgs='-NoProfile -NonInteractive -File "{0}" -ContextFile "{1}"' -f $driverScript,$driverContext
    $ordinaryDriver=Start-Process -FilePath $driver.Path -ArgumentList $driverArgs -Credential $account.credential -LoadUserProfile -PassThru -WindowStyle Hidden -WorkingDirectory $driverRoot -RedirectStandardOutput (Join-Path $driverOutput 'driver.stdout') -RedirectStandardError $protocolLog
    $driverDeadline=[DateTime]::UtcNow.AddSeconds(120)
    $nativeSaveDialog=$false
    do {
        $ordinaryDriver.Refresh()
        if ($ordinaryDriver.HasExited) { break }
        foreach ($process in @(Get-Process -Id @($desktop.Id,$browser.ProcessId) -ErrorAction SilentlyContinue)) {
            if ($process.MainWindowTitle -match '(?i)^(Save As|Save|Downloads)$') { $nativeSaveDialog=$true }
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $driverDeadline)
    if (-not $ordinaryDriver.HasExited) { $ordinaryDriver.Kill($true); $null=$ordinaryDriver.WaitForExit(10000) }
    Write-Probe 'native-save-dialog.json' @{matching_main_window_observed=$nativeSaveDialog; observer='actual shell and owned browser main-window titles'}
    $trace = @(foreach ($line in (Get-Content -LiteralPath $protocolLog -ErrorAction SilentlyContinue)) {
        if ($line -notmatch '"method":"Browser[.](setDownloadBehavior|downloadWillBegin|downloadProgress)"') { continue }
        $first=$line.IndexOf('{')
        $last=$line.LastIndexOf('}')
        if ($first -lt 0 -or $last -le $first) { continue }
        try { $packet=$line.Substring($first,$last-$first+1) | ConvertFrom-Json -AsHashtable } catch { continue }
        $details=$packet['params']
        $url=if ($details['url']) { ([string]$details['url']).Split('?')[0] } else { $null }
        [ordered]@{
            method=$packet['method']; url=$url; filename=$details['suggestedFilename']; state=$details['state']
            received_bytes=$details['receivedBytes']; total_bytes=$details['totalBytes']; configured_path=$details['downloadPath']
            reported_path=$details['filePath']; behavior=$details['behavior']
        }
    })
    Write-Probe 'browser-download-events.json' @{events=$trace}
    $folderAcl=Get-Acl -LiteralPath $account.browser_artifacts
    Write-Probe 'browser-artifacts-acl.json' @{
        owner=$folderAcl.Owner; path=$account.browser_artifacts
        ordinary_user_rights=@($folderAcl.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier]) |
            Where-Object { $_.IdentityReference.Value -eq $sid } | ForEach-Object { $_.FileSystemRights.ToString() })
        ordinary_account_can_read_sentinel=(Test-Path -LiteralPath (Join-Path $account.browser_artifacts 'standard-account-write-test.txt'))
    }
    foreach ($name in 'ordinary-project-playwright.json','ordinary-driver-identity.json','ordinary-driver-environment.json','ordinary-2d-webview2.json','probe-native-viewport.json','probe-download-network.json') {
        Get-ChildItem -LiteralPath $driverOutput -File -Recurse -Filter $name | Copy-Item -Destination $EvidenceRoot
    }
    $identityPath=Join-Path $EvidenceRoot 'ordinary-driver-identity.json'
    if (-not (Test-Path -LiteralPath $identityPath -PathType Leaf)) {
        # This happens before starting Node, so no browser messages are present.
        Write-Probe 'ordinary-driver-startup-failure.json' @{
            exit_code=$ordinaryDriver.ExitCode
            stage=@(Get-Content -LiteralPath (Join-Path $driverOutput 'ordinary-driver-stage.txt') -ErrorAction SilentlyContinue)
            error=@(Get-Content -LiteralPath $protocolLog -Tail 20 -ErrorAction SilentlyContinue)
        }
        throw 'The ordinary driver exited before reporting its process identity.'
    }
    $ordinaryIdentity=Get-Content -LiteralPath $identityPath -Raw | ConvertFrom-Json
    if ($ordinaryIdentity.integrity -ne 8192 -or $ordinaryIdentity.user_sid -ne $sid) { throw 'Driver and app did not run as the same ordinary Windows user.' }
    if ($ordinaryDriver.ExitCode -ne 0) { throw 'The same-ordinary-account WebView2 download journey failed.' }
    $stats = (Get-Content -LiteralPath (Join-Path $EvidenceRoot 'ordinary-project-playwright.json') -Raw | ConvertFrom-Json).stats
    if ($stats.expected -ne 1 -or $stats.unexpected -ne 0 -or $stats.skipped -ne 0) { throw 'Expected one physical WebView2 Playwright journey.' }
} finally {
    try {
        if ($account) {
            Remove-ReefVisionHostedGuiAccount -Account $account -EvidenceRoot $EvidenceRoot
            $standardCleanup = Get-Content -LiteralPath (Join-Path $EvidenceRoot 'spatial-standard-user-cleanup.log') -Raw | ConvertFrom-Json
            $cleanup.desktop_closed = $standardCleanup.desktop_closed
            $cleanup.temporary_account_removed = $standardCleanup.account_removed
            $cleanup.temporary_user_profile_removed = $standardCleanup.profile_removed
        }
        if ($debugPort) {
            Wait-ReefVisionWebView2DebugClosure -Port $debugPort
            $cleanup.debug_port_closed = $true
        }
        if ($registered) {
            Run-ProbeMsi -Arguments @('/x', $productCode, '/qn', '/norestart', '/l*v', ('"{0}"' -f $uninstallLog))
            $cleanup.uninstalled = -not (Test-Path -LiteralPath $desktopPath)
        }
    } finally {
        foreach ($pair in @{
            'backend.log' = (Join-Path $profile 'logs/backend.log')
            'api.log' = (Join-Path $profile 'logs/api.log')
        }.GetEnumerator()) {
            if (Test-Path -LiteralPath $pair.Value -PathType Leaf) {
                Get-Content -LiteralPath $pair.Value -Tail 80 | Set-Content -LiteralPath (Join-Path $EvidenceRoot $pair.Key)
            }
        }
        Write-Probe 'cleanup.json' $cleanup
    }
}
if ($cleanup.Values -contains $false) { throw 'The standard-user probe did not verify all process/account/MSI cleanup.' }
