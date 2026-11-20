function Get-HostedRunnerPrograms {
    $p = @(Get-CimInstance Win32_Process -Filter "Name = 'Runner.Listener.exe' OR Name = 'Runner.Worker.exe'")
    if ($p.Count -ne 2 -or @($p | Where-Object Name -eq 'Runner.Listener.exe').Count -ne 1 -or
        @($p | Where-Object Name -eq 'Runner.Worker.exe').Count -ne 1 -or @($p | Where-Object { -not $_.ExecutablePath }).Count) {
        throw 'Expected one authentic Actions listener and worker on the disposable runner.'
    }
    $bin = @($p | ForEach-Object { Split-Path -Parent $_.ExecutablePath } | Sort-Object -Unique)
    if ($bin.Count -ne 1 -or (Split-Path -Leaf $bin[0]) -ine 'bin') { throw 'The Actions process executables do not share their runner binary directory.' }
    return $p
}

function Save-OriginalFirewallAndHosts([string]$Root) {
    $originalHosts = Join-Path $Root 'original-hosts'
    $originalFirewall = Join-Path $Root 'original-firewall.wfw'
    Copy-Item -LiteralPath (Join-Path $env:SystemRoot 'System32/drivers/etc/hosts') -Destination $originalHosts
    & (Join-Path $env:SystemRoot 'System32/netsh.exe') advfirewall export $originalFirewall | Out-Host
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $originalFirewall -PathType Leaf)) { throw 'Could not back up the Windows Firewall policy.' }
    return [ordered]@{hosts_sha256=(Get-FileHash -LiteralPath $originalHosts).Hash; firewall_sha256=(Get-FileHash -LiteralPath $originalFirewall).Hash}
}

function Add-RunnerControlNameResolution {
    # Only Actions control-plane names are made static. Public DNS egress has no firewall exception.
    $known = @('broker.actions.githubusercontent.com','pipelines.actions.githubusercontent.com')
    foreach ($entry in 'ACTIONS_RUNTIME_URL','ACTIONS_RESULTS_URL','ACTIONS_CACHE_URL','ACTIONS_ID_TOKEN_REQUEST_URL') {
        $value = [Environment]::GetEnvironmentVariable($entry)
        if ($value) { $known += ([uri]$value).DnsSafeHost }
    }
    $known += @(Get-DnsClientCache | Where-Object { $_.Entry -match '\.actions\.githubusercontent\.com$' } | ForEach-Object Entry)
    $entries = @(foreach ($name in ($known | Sort-Object -Unique)) {
        if ($name -notmatch '^[a-z0-9.-]+\.actions\.githubusercontent\.com$') { continue }
        $addresses = @([Net.Dns]::GetHostAddresses($name) | Where-Object AddressFamily -eq 'InterNetwork')
        foreach ($address in $addresses) { "$($address.IPAddressToString) $name" }
    })
    if (-not $entries.Count) { throw 'Could not resolve any Actions control-plane name before measurement.' }
    Add-Content -LiteralPath (Join-Path $env:SystemRoot 'System32/drivers/etc/hosts') -Value (@('', '# Disposable Actions qualification') + $entries)
    Clear-DnsClientCache
    return $entries
}

function Set-ProofFirewall($Programs, [string]$Group) {
    $priorAllows = @(Get-NetFirewallRule -PolicyStore PersistentStore -Enabled True -Direction Outbound -Action Allow)
    foreach ($program in $Programs) {
        New-NetFirewallRule -PolicyStore PersistentStore -Name "$Group-$($program.Name)" -DisplayName "$Group $($program.Name)" `
            -Group $Group -Direction Outbound -Action Allow -Enabled True -Profile Any -Program $program.ExecutablePath `
            -Protocol TCP -RemotePort 443 | Out-Null
    }
    if ($priorAllows.Count) { $priorAllows | Disable-NetFirewallRule | Out-Null }
    Set-NetFirewallProfile -Profile Domain,Private,Public -Enabled True -DefaultOutboundAction Block
}

function Assert-ProofFirewall($Programs, [string]$Group) {
    $profiles = @(Get-NetFirewallProfile -PolicyStore ActiveStore)
    if ($profiles.Count -ne 3 -or @($profiles | Where-Object { $_.Enabled -ne 'True' -or $_.DefaultOutboundAction -ne 'Block' }).Count) {
        throw 'An effective Windows Firewall profile is not enabled with outbound denied by default.'
    }
    $rules = @(Get-NetFirewallRule -PolicyStore ActiveStore -Enabled True -Direction Outbound -Action Allow)
    if ($rules.Count -ne $Programs.Count -or @($rules | Where-Object Group -ne $Group).Count) {
        throw 'The effective outbound policy has an unexpected allow exception.'
    }
    foreach ($program in $Programs) {
        $rule = @($rules | Where-Object Name -ceq "$Group-$($program.Name)")
        if ($rule.Count -ne 1 -or ($rule[0] | Get-NetFirewallApplicationFilter).Program -ine $program.ExecutablePath) {
            throw 'The active outbound exception is not scoped to the exact authenticated Actions executable.'
        }
        $port = $rule[0] | Get-NetFirewallPortFilter
        if ($port.Protocol -ne 'TCP' -or @($port.RemotePort).Count -ne 1 -or $port.RemotePort -ne '443') {
            throw 'The Actions-only outbound exception is not scoped to TCP 443.'
        }
    }
    $connections = @(Get-NetTCPConnection -State Established -RemotePort 443 | Where-Object OwningProcess -in $Programs.ProcessId)
    if (-not $connections.Count) { throw 'Neither actual Actions process retained an external TLS control connection.' }
    return [ordered]@{profiles=3; default_outbound='Block'; allow_rules=@($rules.Name); github_tls_connections=$connections.Count}
}

function Get-ProofFirewallEvents([string]$Channel, [DateTimeOffset]$Start, [DateTimeOffset]$End) {
    try {
        Get-WinEvent -FilterHashtable @{
            LogName=$Channel; StartTime=$Start.LocalDateTime; EndTime=$End.LocalDateTime
        } -ErrorAction Stop | Where-Object { $_.Id -ge 2000 -and $_.Id -le 2105 -and $_.Id -ne 2011 }
    } catch {
        if ($_.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound,*') { throw }
    }
}

function Test-FirewallJournalSetup([string]$Channel, [DateTimeOffset]$Start, [string]$Group) {
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(8)
    do {
        $events = @(Get-ProofFirewallEvents $Channel $Start ([DateTimeOffset]::UtcNow))
        $rules = @(foreach ($event in ($events | Where-Object Id -in @(2004,2071,2097))) {
            $xml = [xml]$event.ToXml()
            $ruleName = ($xml.Event.EventData.Data | Where-Object Name -eq 'RuleName').'#text'
            if ($ruleName -in @("$Group Runner.Listener.exe", "$Group Runner.Worker.exe")) { $event }
        })
        if ($rules.Count -eq 2) { return $rules }
        Start-Sleep -Milliseconds 250
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw 'The firewall event journal did not record both deliberate setup rule additions.'
}
