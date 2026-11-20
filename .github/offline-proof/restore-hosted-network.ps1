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
$record.mode = 'restore_original_up_adapters'
try {
    foreach ($original in $plan.adapters) {
        $adapter = @(Get-NetAdapter -IncludeHidden | Where-Object { [string]$_.InterfaceGuid -eq $original.guid })
        if ($adapter.Count -ne 1 -or $adapter[0].Name -cne $original.name) { throw 'Recovery could not identify an original adapter.' }
        if ($adapter[0].Status -eq 'Disabled') { Enable-NetAdapter -InputObject $adapter[0] -Confirm:$false }
    }
    $record.enabled = $true
} catch {
    $record.error = $_.Exception.Message
    throw
} finally {
    $record.completed_utc = [DateTimeOffset]::UtcNow.ToString('o')
    $record | ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $root 'evidence/watchdog.jsonl')
}
