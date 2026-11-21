param(
    [Parameter(Mandatory)][string]$Plan,
    [Parameter(Mandatory)][ValidateSet('system','ordinary')][string]$Role,
    [ValidateSet('measurement','reconnect')][string]$Phase = 'measurement'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($Plan -cnotmatch '^[A-Z]:\\rv-offline-\d+-\d+\\firewall-probes\.json$') { throw 'Expected the disposable hosted probe plan.' }
$root = Split-Path -Parent $Plan
$config = Get-Content -LiteralPath $Plan -Raw | ConvertFrom-Json
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if (($Role -eq 'system' -and $sid -cne 'S-1-5-18') -or ($Role -eq 'ordinary' -and $sid -cne $config.ordinary_sid)) {
    throw 'Firewall control is running as an unexpected Windows principal.'
}
$leaf = if ($Phase -eq 'reconnect') { 'reconnect-tcp.jsonl' } else { 'tcp.jsonl' }
$destination = Join-Path $root "probe-$Role/$leaf"
$clock = [Diagnostics.Stopwatch]::StartNew()
$previousSampleEnd = $null
while (-not (Test-Path -LiteralPath (Join-Path $root 'stop-probes')) -and
    [DateTimeOffset]::UtcNow -lt [DateTimeOffset]$config.expires_utc) {
    $sampleStart = $clock.Elapsed.TotalMilliseconds
    $online = @(foreach ($item in $config.addresses) {
        $address = [Net.IPAddress]::Parse($item)
        $client = [Net.Sockets.TcpClient]::new($address.AddressFamily)
        try {
            if ($client.ConnectAsync($address,443).Wait(1200) -and $client.Connected) { $item }
        } catch { $null = $_ } finally { $client.Dispose() }
    })
    $sampleEnd = $clock.Elapsed.TotalMilliseconds
    @{
        utc=[DateTimeOffset]::UtcNow.ToString('o'); pid=$PID; sid=$sid; reachable=$online
        tcp_probe_ms=$sampleEnd-$sampleStart
        collector_idle_ms=if ($null -ne $previousSampleEnd) { $sampleStart-$previousSampleEnd } else { $null }
    } | ConvertTo-Json -Compress |
        Add-Content -LiteralPath $destination
    $previousSampleEnd = $sampleEnd
    Start-Sleep -Milliseconds 350
}
