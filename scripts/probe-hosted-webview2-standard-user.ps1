[CmdletBinding(DefaultParameterSetName='Probe')]
param(
    [Parameter(Mandatory, ParameterSetName='Probe')][string]$InstallerDirectory,
    [Parameter(Mandatory, ParameterSetName='Probe')][string]$EvidenceRoot,
    [Parameter(Mandatory, ParameterSetName='Launch')][string]$LaunchContext
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

function Set-ProbeRestrictedPath {
    $env:PATH = @((Join-Path $env:SystemRoot 'System32'),$env:SystemRoot,(Join-Path $env:SystemRoot 'System32\Wbem'),(Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0')) -join ';'
}

if ($PSCmdlet.ParameterSetName -eq 'Launch') {
    $params = Get-Content -LiteralPath $LaunchContext -Raw | ConvertFrom-Json
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    if ($identity.User.Value -ne $params.user_sid -or $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'The credential launcher must run under the designated standard user.'
    }
    . (Join-Path $PSScriptRoot 'lib/windows-clean-acceptance.ps1')
    Set-ProbeRestrictedPath
    foreach ($runtime in 'node','npm','python','python3','rustc','cargo') {
        if (Get-Command $runtime -ErrorAction SilentlyContinue) { throw 'A development runtime reached the standard-user PATH.' }
    }
    $desktop = Invoke-ReefVisionIsolatedEnvironment -DataRoot $params.profile -AdditionalEnvironment @{
        REEFVISION_WINDOWS_ACCEPTANCE = '1'
        REEFVISION_ACCEPTANCE_DATA_DIR = $params.profile
        WEBVIEW2_USER_DATA_FOLDER = $params.webview2
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-address=127.0.0.1 --remote-debugging-port=$($params.port)"
        YOLO_OFFLINE = 'true'
    } -Action {
        Start-Process -FilePath $params.executable -WorkingDirectory (Split-Path -Parent $params.executable) -PassThru -WindowStyle Hidden
    }
    $identityReport = [ordered]@{
        launcher_pid=$PID
        launcher_sid=$identity.User.Value
        launcher_session=(Get-Process -Id $PID).SessionId
        launcher_is_admin=$false
        desktop_pid=$desktop.Id
    }
    $pending = $params.receipt + '.tmp'
    $identityReport | ConvertTo-Json | Set-Content -LiteralPath $pending
    Move-Item -LiteralPath $pending -Destination $params.receipt
    # The credential-launched helper holds the temporary user's registry hive
    # loaded while the GUI and its browser child use it.
    $desktop.WaitForExit()
    exit
}

if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or
    $env:GITHUB_REF_NAME -ne 'codex/reefvision-webview2-host-probe-20261120') {
    throw 'The temporary Windows test account is available only in its designated GitHub-hosted diagnostic job.'
}

. (Join-Path $PSScriptRoot 'lib/windows-clean-acceptance.ps1')
. (Join-Path $PSScriptRoot 'lib/windows-spatial-webview2-acceptance.ps1')
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
function Grant-ProbeAccess([string]$Path,[string]$Sid,[string]$Permission) {
    & (Join-Path $env:SystemRoot 'System32/icacls.exe') $Path /grant ("*{0}:{1}" -f $Sid,$Permission) | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not grant only the probe user access to the exact scratch location.' }
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
            foreach ($name in 'DeveloperToolsAvailability','RemoteDebuggingAllowed') {
                $value = if ($settings) { $settings.PSObject.Properties[$name] } else { $null }
                $presence[$name] = if ($value -and $value.Value -is [int]) { $value.Value } else { $null }
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
$webview2 = Join-Path $root 'webview'
$handshake = Join-Path $root 'handshake'
$bootstrap = Join-Path $root 'bootstrap'
New-Item -ItemType Directory -Path $EvidenceRoot,$root,$profile,$webview2,$handshake,(Join-Path $bootstrap 'lib') | Out-Null
Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $bootstrap 'launch.ps1')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'lib/windows-clean-acceptance.ps1') -Destination (Join-Path $bootstrap 'lib')
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
$userName = "rvweb-$token"
$user = $null
$launcher = $null
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

    $password = ConvertTo-SecureString ('xRv!7' + [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')) -AsPlainText -Force
    $user = New-LocalUser -Name $userName -Password $password -Description 'Disposable ReefVision WebView2 probe'
    Add-LocalGroupMember -SID 'S-1-5-32-545' -Member $user
    $sid = $user.SID.Value
    $cred = [System.Management.Automation.PSCredential]::new("$env:COMPUTERNAME\$userName",$password)
    foreach ($path in @($root,$install)) { Grant-ProbeAccess $path $sid '(OI)(CI)RX' }
    foreach ($path in @($profile,$webview2,$handshake)) { Grant-ProbeAccess $path $sid '(OI)(CI)M' }
    $credentialShell = $driver.Path
    $debugPort = Get-ReefVisionLoopbackDebugPort
    $ack = Join-Path $handshake 'launcher.json'
    $context = Join-Path $root 'context.json'
    [ordered]@{
        executable=$desktopPath; profile=$profile; webview2=$webview2; port=$debugPort; user_sid=$sid; receipt=$ack
    } | ConvertTo-Json | Set-Content -LiteralPath $context

    # Use absolute executables; only the Playwright driver has access to Node.
    Set-ProbeRestrictedPath
    $argsLine = '-NoLogo -NoProfile -NonInteractive -File "{0}" -LaunchContext "{1}"' -f (Join-Path $bootstrap 'launch.ps1'),$context
    $launcher = Start-Process -FilePath $credentialShell -ArgumentList $argsLine -Credential $cred -LoadUserProfile -PassThru -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $handshake 'launcher.stdout') -RedirectStandardError (Join-Path $handshake 'launcher.stderr')
    Wait-ProbeFile -Path $ack -Seconds 35
    $launch = Get-Content -LiteralPath $ack -Raw | ConvertFrom-Json
    $desktop = Get-Process -Id $launch.desktop_pid -ErrorAction Stop
    $child = Get-CimInstance Win32_Process -Filter "ProcessId = $($desktop.Id)"
    $owner = Invoke-CimMethod -InputObject $child -MethodName GetOwnerSid
    $integrity = [ReefVisionProbeProcessToken]::Integrity($desktop.Handle)
    Write-Probe 'desktop-identity.json' ([ordered]@{
        source_commit=$expectedCommit; msi_sha256=$sha; executable_sha256=(Get-FileHash -LiteralPath $desktopPath).Hash.ToLowerInvariant()
        driver_integrity=$driverIntegrity; desktop_integrity=$integrity; desktop_owner=$owner.Sid; observed_pid=$desktop.Id
        parent_pid=$child.ParentProcessId; session=$child.SessionId; launch=$launch
    })
    if ($launch.launcher_pid -ne $launcher.Id -or $launch.launcher_sid -ne $sid -or $launch.launcher_is_admin -or
        $child.ExecutablePath -ine $desktopPath -or $child.ParentProcessId -ne $launcher.Id -or
        $owner.ReturnValue -ne 0 -or $owner.Sid -ne $sid -or $integrity -ne 8192 -or
        $child.SessionId -ne $driver.SessionId -or $child.SessionId -ne $launch.launcher_session) {
        throw 'The running exact desktop did not use the designated ordinary Windows user and interactive session.'
    }

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
    try {
        $env:REEFVISION_SPATIAL_WEBVIEW2_ENDPOINT = Wait-ReefVisionWebView2DebugEndpoint -Port $debugPort -DesktopProcessId $desktop.Id -FailureEvidencePath (Join-Path $EvidenceRoot 'spatial-webview2-startup.log')
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
    $env:PLAYWRIGHT_JSON_OUTPUT_FILE = Join-Path $EvidenceRoot 'ordinary-project-playwright.json'
    Push-Location -LiteralPath (Join-Path $repo 'apps/web')
    try {
        & $node ./node_modules/@playwright/test/cli.js test ordinary-project-live.spec.ts --workers=1 --retries=0 --reporter=list,json --trace=off --output="$root/playwright"
        if ($LASTEXITCODE -ne 0) { throw 'The genuine standard-user WebView2 journey failed.' }
    } finally { Pop-Location }
    $stats = (Get-Content -LiteralPath $env:PLAYWRIGHT_JSON_OUTPUT_FILE -Raw | ConvertFrom-Json).stats
    if ($stats.expected -ne 1 -or $stats.unexpected -ne 0 -or $stats.skipped -ne 0) { throw 'Expected one physical WebView2 Playwright journey.' }
} finally {
    try {
        if (-not $desktop -and $user -and $launcher) {
            $candidate = Get-CimInstance Win32_Process -Filter "ParentProcessId = $($launcher.Id) AND Name = 'ReefVision.exe'" |
                Where-Object ExecutablePath -EQ $desktopPath | Select-Object -First 1
            if ($candidate -and (Invoke-CimMethod -InputObject $candidate -MethodName GetOwnerSid).Sid -eq $user.SID.Value) {
                $desktop = Get-Process -Id $candidate.ProcessId -ErrorAction SilentlyContinue
            }
        }
        if ($desktop) {
            $desktop.Refresh()
            if (-not $desktop.HasExited) {
                $null = $desktop.CloseMainWindow()
                if (-not $desktop.WaitForExit(15000)) { $desktop.Kill($true); $null = $desktop.WaitForExit(15000) }
            }
            $cleanup.desktop_closed = $desktop.HasExited
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
        if ($launcher -and -not $launcher.HasExited) { $launcher.Kill($true); $null = $launcher.WaitForExit(10000) }
        if ($user) {
            $timeout = [DateTime]::UtcNow.AddSeconds(15)
            do {
                $userProfile = Get-CimInstance Win32_UserProfile -Filter "SID = '$($user.SID.Value)'"
                if (-not $userProfile -or -not $userProfile.Loaded) { break }
                Start-Sleep -Milliseconds 500
            } while ([DateTime]::UtcNow -lt $timeout)
            if ($userProfile -and -not $userProfile.Loaded) {
                Remove-CimInstance -InputObject $userProfile -ErrorAction Continue
            }
            $cleanup.temporary_user_profile_removed = -not (Get-CimInstance Win32_UserProfile -Filter "SID = '$($user.SID.Value)'")
            Remove-LocalUser -SID $user.SID
            $cleanup.temporary_account_removed = -not (Get-LocalUser -Name $userName -ErrorAction SilentlyContinue)
        }
        foreach ($pair in @{
            'launcher.stderr' = (Join-Path $handshake 'launcher.stderr')
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
