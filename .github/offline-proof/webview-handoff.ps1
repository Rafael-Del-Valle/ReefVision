function Get-OfflineWebViewProcessKey($Process) {
    return '{0}:{1}' -f $Process.ProcessId, $Process.CreationDate.ToUniversalTime().Ticks
}

function Test-OfflineWebViewProfile($Process, [string]$Profile) {
    if (-not $Process.CommandLine) { return $false }
    $argument = [regex]::Match($Process.CommandLine, '(?i)(?:^|\s)--user-data-dir=(?:"(?<path>[^"]+)"|(?<path>[^\s"]+))(?=\s|$)')
    return $argument.Success -and $argument.Groups['path'].Value.Replace('/', '\') -ieq $Profile
}

function Get-OfflineWebViewProcesses($Scope) {
    $webViews = @(Get-CimInstance Win32_Process -Filter "Name = 'msedgewebview2.exe'" |
        Where-Object { $_.CreationDate })
    $families = [Collections.Generic.HashSet[int]]::new()
    foreach ($process in $webViews) {
        if ($Scope.ProcessKeys.Contains((Get-OfflineWebViewProcessKey $process))) { $null = $families.Add($process.ProcessId) }
    }
    $previous = -1
    while ($families.Count -ne $previous) {
        $previous = $families.Count
        foreach ($process in $webViews) {
            if ($families.Contains($process.ParentProcessId)) { $null = $families.Add($process.ProcessId) }
        }
    }
    foreach ($process in $webViews) {
        if (-not $families.Contains($process.ProcessId) -and -not (Test-OfflineWebViewProfile $process $Scope.Profile)) { continue }
        try {
            $owner = Invoke-CimMethod -InputObject $process -MethodName GetOwnerSid -ErrorAction Stop
        } catch [Microsoft.Management.Infrastructure.CimException] {
            if (Get-CimInstance Win32_Process -Filter "ProcessId = $($process.ProcessId)") { throw }
            continue
        }
        if ($owner.ReturnValue -eq 0 -and $owner.Sid -ceq $Scope.Sid) {
            $null = $Scope.ProcessKeys.Add((Get-OfflineWebViewProcessKey $process))
            [int]$process.ProcessId
        }
    }
}

function New-OfflineWebViewScope([int]$Port, [int]$DesktopProcessId, [string]$Sid, [string]$Root) {
    $browserPids = @(Get-NetTCPConnection -LocalPort $Port -State Listen |
        Where-Object LocalAddress -eq '127.0.0.1' | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($browserPids.Count -ne 1) { throw 'Expected the exact first-launch loopback WebView2 browser.' }
    $browser = Get-CimInstance Win32_Process -Filter "ProcessId = $($browserPids[0]) AND Name = 'msedgewebview2.exe'"
    if (-not $browser -or -not $browser.CreationDate -or $browser.ParentProcessId -ne $DesktopProcessId) {
        throw 'The browser is not an identifiable child of the first installed desktop.'
    }
    $owner = Invoke-CimMethod -InputObject $browser -MethodName GetOwnerSid
    if ($owner.ReturnValue -ne 0 -or $owner.Sid -cne $Sid) { throw 'The first-launch browser is not owned by the expected ordinary account.' }
    $scope = [pscustomobject]@{
        Profile=[IO.Path]::GetFullPath((Join-Path $Root 'profile-webview2')); Sid=$Sid; BrowserPid=[int]$browser.ProcessId
        ProcessKeys=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    }
    $null = $scope.ProcessKeys.Add((Get-OfflineWebViewProcessKey $browser))
    return $scope
}

function Move-OfflineWebViewCache([string]$Root, [scriptblock]$GetLivePids, [int]$TimeoutSeconds = 25) {
    $cache = Join-Path $Root 'profile-webview2'
    $archive = Join-Path $Root 'first-profile-webview2'
    if (-not [IO.Directory]::Exists($cache) -or (Test-Path -LiteralPath $archive)) { throw 'Expected only the first disposable WebView2 cache directory.' }
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $sharingViolations = 0
    do {
        $remaining = @(& $GetLivePids)
        if (-not $remaining.Count) {
            try {
                # The PowerShell file provider can leave a partial destination on
                # failure. This same-directory atomic rename leaves both paths intact.
                [IO.Directory]::Move($cache,$archive)
                return [ordered]@{owned_browser_processes_exited=$true; cache_archived=$true; wait_seconds=$timer.Elapsed.TotalSeconds; sharing_violations=$sharingViolations}
            } catch {
                $cause = $_.Exception
                while ($cause.InnerException) { $cause = $cause.InnerException }
                $win32 = $cause.HResult -band 0xffff
                # Windows can return ACCESS_DENIED for an open descendant even
                # when the disposable directory ACL permits the eventual rename.
                $shareViolation = $cause -is [IO.IOException] -and $win32 -in @(5,32,33)
                $accessDenied = $cause -is [UnauthorizedAccessException] -and $win32 -eq 5
                if ((-not $shareViolation -and -not $accessDenied) -or -not [IO.Directory]::Exists($cache) -or
                    (Test-Path -LiteralPath $archive)) { throw }
                $sharingViolations++
            }
        }
        Start-Sleep -Milliseconds 200
    } while ($timer.Elapsed.TotalSeconds -lt $TimeoutSeconds)
    throw "The first disposable WebView2 cache still has owned browser processes or a file-share lock ($($remaining.Count) live, $sharingViolations sharing failures)."
}
