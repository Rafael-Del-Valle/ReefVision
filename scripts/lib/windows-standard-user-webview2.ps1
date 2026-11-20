param([string]$LaunchContext)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-ReefVisionHostedStandardUserMode {
    if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
        throw 'The temporary WebView2 account requires a disposable GitHub-hosted Windows runner.'
    }
}

function Invoke-ReefVisionCredentialDesktop([string]$ContextFile) {
    $context = Get-Content -LiteralPath $ContextFile -Raw | ConvertFrom-Json
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    if ($identity.User.Value -ne $context.user_sid -or
        $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'The hosted GUI launcher did not use its designated standard Windows account.'
    }
    # The credential process independently declares its PATH; it need not inherit the driver's.
    $env:PATH = @((Join-Path $env:SystemRoot 'System32'), $env:SystemRoot,
        (Join-Path $env:SystemRoot 'System32\Wbem'), (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0')) -join ';'
    foreach ($runtime in 'node','npm','python','python3','rustc','cargo') {
        if (Get-Command $runtime -ErrorAction SilentlyContinue) { throw 'A developer runtime leaked into the standard-user PATH.' }
    }
    . (Join-Path $PSScriptRoot 'windows-clean-acceptance.ps1')
    $desktop = Invoke-ReefVisionIsolatedEnvironment -DataRoot $context.profile -AdditionalEnvironment @{
        REEFVISION_WINDOWS_ACCEPTANCE = '1'
        REEFVISION_ACCEPTANCE_DATA_DIR = $context.profile
        WEBVIEW2_USER_DATA_FOLDER = $context.browser_data
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-address=127.0.0.1 --remote-debugging-port=$($context.debug_port)"
        YOLO_OFFLINE = 'true'
    } -Action {
        Start-Process -FilePath $context.executable -PassThru -WindowStyle Hidden -WorkingDirectory (Split-Path -Parent $context.executable)
    }
    $receipt = [ordered]@{
        launcher_pid=$PID; desktop_pid=$desktop.Id; user_sid=$identity.User.Value
        windows_user_profile=$env:USERPROFILE
    }
    $pending = $context.receipt + '.tmp'
    $receipt | ConvertTo-Json | Set-Content -LiteralPath $pending
    Move-Item -LiteralPath $pending -Destination $context.receipt
    # Keep the temporary user's profile loaded while its native GUI is active.
    $desktop.WaitForExit()
}

if ($LaunchContext) {
    Invoke-ReefVisionCredentialDesktop -ContextFile $LaunchContext
    exit
}

function Get-ReefVisionProcessIntegrity([System.Diagnostics.Process]$Process) {
    if (-not ('ReefVisionAcceptanceProcessToken' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class ReefVisionAcceptanceProcessToken
{
    [DllImport("advapi32", SetLastError = true)]
    private static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);

    [DllImport("advapi32", SetLastError = true)]
    private static extern bool GetTokenInformation(IntPtr token, int type, IntPtr buffer, int size, out int required);

    [DllImport("advapi32")]
    private static extern IntPtr GetSidSubAuthorityCount(IntPtr sid);

    [DllImport("advapi32")]
    private static extern IntPtr GetSidSubAuthority(IntPtr sid, uint index);

    [DllImport("kernel32")]
    private static extern bool CloseHandle(IntPtr handle);

    public static int Integrity(IntPtr process)
    {
        const uint tokenQuery = 8;
        const int tokenIntegrityLevel = 25;
        IntPtr token, buffer = IntPtr.Zero;
        if (!OpenProcessToken(process, tokenQuery, out token))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        try
        {
            int size;
            GetTokenInformation(token, tokenIntegrityLevel, IntPtr.Zero, 0, out size);
            if (size <= 0) throw new Win32Exception(Marshal.GetLastWin32Error());
            buffer = Marshal.AllocHGlobal(size);
            if (!GetTokenInformation(token, tokenIntegrityLevel, buffer, size, out size))
                throw new Win32Exception(Marshal.GetLastWin32Error());

            IntPtr sid = Marshal.ReadIntPtr(buffer);
            uint last = (uint)(Marshal.ReadByte(GetSidSubAuthorityCount(sid)) - 1);
            return Marshal.ReadInt32(GetSidSubAuthority(sid, last));
        }
        finally
        {
            if (buffer != IntPtr.Zero) Marshal.FreeHGlobal(buffer);
            CloseHandle(token);
        }
    }
}
'@
    }
    return [ReefVisionAcceptanceProcessToken]::Integrity($Process.Handle)
}

function New-ReefVisionHostedGuiAccount([string]$RunRoot) {
    Assert-ReefVisionHostedStandardUserMode
    if (-not (Test-Path -LiteralPath (Join-Path $RunRoot '.reefvision-acceptance-run') -PathType Leaf)) {
        throw 'The temporary WebView2 account requires the current marked disposable acceptance root.'
    }
    $hostProcess = Get-Process -Id $PID
    if ((Get-ReefVisionProcessIntegrity $hostProcess) -lt 12288) {
        throw 'The installer and driver must remain elevated for the hosted clean test.'
    }
    $name = 'rvweb-' + [guid]::NewGuid().ToString('N').Substring(0, 10)
    $password = ConvertTo-SecureString ('xRv!7' + [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')) -AsPlainText -Force
    $user = New-LocalUser -Name $name -Password $password -Description 'Disposable ReefVision WebView2 test'
    try {
        Add-LocalGroupMember -SID 'S-1-5-32-545' -Member $user
        return [pscustomobject]@{
            name=$name; sid=$user.SID; run_root=$RunRoot
            credential=[System.Management.Automation.PSCredential]::new("$env:COMPUTERNAME\$name",$password)
            launcher=$null; desktop=$null; executable=$null; launcher_errors=$null; browser_artifacts=''
        }
    } catch {
        Remove-LocalUser -SID $user.SID
        throw
    }
}

function Grant-ReefVisionHostedGuiAccess([string]$Path,[System.Security.Principal.SecurityIdentifier]$Sid,[string]$Rights) {
    & (Join-Path $env:SystemRoot 'System32/icacls.exe') $Path /grant ("*{0}:(OI)(CI){1}" -f $Sid.Value,$Rights) | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not grant the standard account access to the disposable GUI path.' }
}

function Start-ReefVisionHostedGui {
    param(
        [Parameter(Mandatory)]$Account,
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string]$Profile,
        [Parameter(Mandatory)][int]$DebugPort,
        [Parameter(Mandatory)][string]$EvidenceRoot,
        [ValidatePattern('^[a-z][a-z-]{0,29}$')][string]$LaunchLabel = 'spatial'
    )
    Assert-ReefVisionHostedStandardUserMode
    $installerDirectory = Split-Path -Parent $Executable
    if (-not (Test-ReefVisionPathWithin -Path $Executable -Parent $Account.run_root) -or
        -not (Test-ReefVisionPathWithin -Path $Profile -Parent $Account.run_root) -or
        (Split-Path -Leaf $Executable) -ine 'ReefVision.exe') {
        throw 'Hosted WebView2 can only launch the candidate inside its disposable acceptance root.'
    }
    Assert-ReefVisionNoReparseAncestors -Path $Executable
    Assert-ReefVisionNoReparseAncestors -Path $Profile
    if (($Account.desktop -and -not $Account.desktop.HasExited) -or
        ($Account.launcher -and -not $Account.launcher.HasExited)) {
        throw 'The previous desktop and its standard-user launcher must close before another launch.'
    }
    $Account.desktop = $null
    $Account.launcher = $null
    $Account.executable = $Executable
    $browserName = if ($LaunchLabel -eq 'spatial') { (Split-Path -Leaf $Profile) + '-webview2' } else { "$LaunchLabel-webview2" }
    $bootstrapName = if ($LaunchLabel -eq 'spatial') { 'ordinary-user-launch' } else { "$LaunchLabel-launch" }
    $browserData = Join-Path $Account.run_root $browserName
    $bootstrap = Join-Path $Account.run_root $bootstrapName
    $handshake = Join-Path $bootstrap 'handshake'
    $Account.browser_artifacts = Join-Path $bootstrap 'browser-artifacts'
    New-Item -ItemType Directory -Path $browserData,$handshake,$Account.browser_artifacts | Out-Null
    $launcherSource = Join-Path $bootstrap 'launch.ps1'
    Copy-Item -LiteralPath $PSCommandPath -Destination $launcherSource
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'windows-clean-acceptance.ps1') -Destination $bootstrap
    Grant-ReefVisionHostedGuiAccess -Path $Account.run_root -Sid $Account.sid -Rights 'RX'
    Grant-ReefVisionHostedGuiAccess -Path $installerDirectory -Sid $Account.sid -Rights 'RX'
    foreach ($path in @($Profile,$browserData,$handshake,$Account.browser_artifacts)) {
        Grant-ReefVisionHostedGuiAccess -Path $path -Sid $Account.sid -Rights 'M'
    }

    $context = Join-Path $bootstrap 'context.json'
    $receipt = Join-Path $handshake 'launcher.json'
    [ordered]@{
        executable=$Executable; profile=$Profile; browser_data=$browserData
        debug_port=$DebugPort; user_sid=$Account.sid.Value; receipt=$receipt
    } | ConvertTo-Json | Set-Content -LiteralPath $context
    $hostProcess = Get-Process -Id $PID
    $launchArgs = '-NoProfile -NonInteractive -File "{0}" -LaunchContext "{1}"' -f $launcherSource,$context
    $Account.launcher_errors = Join-Path $handshake 'launcher.stderr'
    # Let Windows populate the temporary account environment so its shell
    # folders and browser downloads resolve under the actual ordinary profile.
    $Account.launcher = Start-Process -FilePath $hostProcess.Path -ArgumentList $launchArgs -Credential $Account.credential `
        -LoadUserProfile -UseNewEnvironment -PassThru -WindowStyle Hidden -WorkingDirectory $bootstrap `
        -RedirectStandardOutput (Join-Path $handshake 'launcher.stdout') -RedirectStandardError $Account.launcher_errors
    $deadline = [DateTime]::UtcNow.AddSeconds(35)
    do {
        if (Test-Path -LiteralPath $receipt -PathType Leaf) { break }
        if ($Account.launcher.HasExited -or [DateTime]::UtcNow -ge $deadline) {
            throw 'The hosted standard-user launcher did not publish a native desktop process ID.'
        }
        Start-Sleep -Milliseconds 250
    } while ($true)

    $launch = Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json
    $child = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$launch.desktop_pid) AND Name = 'ReefVision.exe'"
    if (-not $child -or $launch.launcher_pid -ne $Account.launcher.Id -or
        $launch.user_sid -ne $Account.sid.Value -or $child.ExecutablePath -ine $Executable -or
        $child.ParentProcessId -ne $Account.launcher.Id -or $child.SessionId -ne $hostProcess.SessionId) {
        throw 'The standard-user launcher did not own the exact installed desktop in the runner session.'
    }
    $owner = Invoke-CimMethod -InputObject $child -MethodName GetOwnerSid
    if ($owner.ReturnValue -ne 0 -or $owner.Sid -ne $Account.sid.Value) {
        throw 'The exact installed desktop did not run as the designated Windows standard user.'
    }
    $windowsProfile = Get-CimInstance Win32_UserProfile -Filter "SID = '$($Account.sid.Value)'"
    if (-not $windowsProfile -or -not $windowsProfile.Loaded -or $launch.windows_user_profile -ine $windowsProfile.LocalPath) {
        throw 'The desktop launcher did not use the loaded Windows profile for the designated standard user.'
    }
    $desktop = Get-Process -Id $child.ProcessId -ErrorAction Stop
    $Account.desktop = $desktop
    $integrity = Get-ReefVisionProcessIntegrity $desktop
    if ($integrity -ne 8192) { throw 'The exact installed desktop did not run at medium integrity.' }

    [ordered]@{
        desktop_pid=$desktop.Id; launcher_pid=$Account.launcher.Id; windows_session=$child.SessionId
        desktop_owner_sid=$owner.Sid; desktop_integrity=$integrity; driver_integrity=Get-ReefVisionProcessIntegrity $hostProcess
        desktop_sha256=(Get-FileHash -LiteralPath $Executable).Hash.ToLowerInvariant()
        desktop_windows_user_profile=$launch.windows_user_profile
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $EvidenceRoot "$LaunchLabel-standard-user-identity.log")
    return $desktop
}

function Remove-ReefVisionHostedGuiAccount($Account,[string]$EvidenceRoot,[string]$Label = 'spatial') {
    Assert-ReefVisionHostedStandardUserMode
    $cleanup = [ordered]@{desktop_closed=$false; launch_process_closed=$false; profile_removed=$false; account_removed=$false}
    try {
        try {
            if (-not $Account.desktop -and $Account.launcher) {
                $candidate = Get-CimInstance Win32_Process -Filter "ParentProcessId = $($Account.launcher.Id) AND Name = 'ReefVision.exe'" |
                    Where-Object ExecutablePath -EQ $Account.executable | Select-Object -First 1
                if ($candidate -and (Invoke-CimMethod -InputObject $candidate -MethodName GetOwnerSid).Sid -eq $Account.sid.Value) {
                    $Account.desktop = Get-Process -Id $candidate.ProcessId -ErrorAction SilentlyContinue
                }
            }
            if ($Account.desktop -and -not $Account.desktop.HasExited) {
                $null = $Account.desktop.CloseMainWindow()
                if (-not $Account.desktop.WaitForExit(15000)) { $Account.desktop.Kill($true); $null=$Account.desktop.WaitForExit(15000) }
            }
            $cleanup.desktop_closed = -not $Account.desktop -or $Account.desktop.HasExited
        } finally {
            if ($Account.launcher -and -not $Account.launcher.WaitForExit(10000)) {
                $Account.launcher.Kill()
                $null = $Account.launcher.WaitForExit(10000)
            }
            $cleanup.launch_process_closed = -not $Account.launcher -or $Account.launcher.HasExited
            $deadline = [DateTime]::UtcNow.AddSeconds(15)
            do {
                $profile = Get-CimInstance Win32_UserProfile -Filter "SID = '$($Account.sid.Value)'"
                if (-not $profile -or -not $profile.Loaded) { break }
                Start-Sleep -Milliseconds 500
            } while ([DateTime]::UtcNow -lt $deadline)
            if ($profile -and -not $profile.Loaded) { Remove-CimInstance -InputObject $profile -ErrorAction Continue }
            $cleanup.profile_removed = -not (Get-CimInstance Win32_UserProfile -Filter "SID = '$($Account.sid.Value)'")
        }
    } finally {
        Remove-LocalUser -SID $Account.sid
        $cleanup.account_removed = -not (Get-LocalUser -Name $Account.name -ErrorAction SilentlyContinue)
        if ($Account.launcher_errors -and (Test-Path -LiteralPath $Account.launcher_errors -PathType Leaf)) {
            Get-Content -LiteralPath $Account.launcher_errors -Tail 25 | Set-Content -LiteralPath (Join-Path $EvidenceRoot "$Label-standard-user-launch.log")
        }
        $cleanup | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $EvidenceRoot "$Label-standard-user-cleanup.log")
    }
    if ($cleanup.Values -contains $false) { throw 'Could not verify temporary WebView2 process and account cleanup.' }
}
