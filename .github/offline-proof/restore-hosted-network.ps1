param([Parameter(Mandatory)][string]$State)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value -cne 'S-1-5-18' -or
    $State -cnotmatch '^[A-Z]:\\rv-offline-\d+-\d+\\network-restore-state\.json$') {
    throw 'Network recovery is owned by the hosted proof SYSTEM task.'
}
$root = Split-Path -Parent $State
$plan = Get-Content -LiteralPath $State -Raw | ConvertFrom-Json
if ($plan.computer -cne $env:COMPUTERNAME -or [DateTimeOffset]::Parse($plan.expires_utc) -lt [DateTimeOffset]::UtcNow) {
    throw 'Network recovery plan does not belong to this disposable run.'
}
$armed = Join-Path $root 'network-armed'
$record = [ordered]@{observed_utc=[DateTimeOffset]::UtcNow.ToString('o'); system_sid='S-1-5-18'; pid=$PID}
if (-not (Test-Path -LiteralPath $armed -PathType Leaf)) {
    $record.mode = 'preflight_only'
    $record | ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $root 'evidence/watchdog.jsonl')
    exit 0
}
$record.mode = 'restore_original_firewall_and_hosts'
try {
    & (Join-Path $env:SystemRoot 'System32/netsh.exe') advfirewall import (Join-Path $root 'original-firewall.wfw')
    if ($LASTEXITCODE -ne 0) { throw 'Could not restore the original Windows Firewall policy.' }
    $hosts = Join-Path $env:SystemRoot 'System32/drivers/etc/hosts'
    Copy-Item -LiteralPath (Join-Path $root 'original-hosts') -Destination $hosts -Force
    Clear-DnsClientCache
    $record.restored = $true
} catch {
    $record.error = $_.Exception.Message
    throw
} finally {
    $record.completed_utc = [DateTimeOffset]::UtcNow.ToString('o')
    $record | ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $root 'evidence/watchdog.jsonl')
}
