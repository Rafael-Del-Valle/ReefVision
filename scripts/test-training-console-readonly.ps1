# Exercise the actual embedded PowerShell monitor with a fake local read-only API.
# No training job, network request, process launch, or user data is required.
$ErrorActionPreference = 'Stop'
$main = Join-Path $PSScriptRoot '../apps/web/src-tauri/src/main.rs'
$source = Get-Content -LiteralPath $main -Raw
$match = [regex]::Match(
  $source,
  '(?ms)^\s*let script = format!\("\$url = ''\{\}''; ", url\)\s*\+\s*r#"\s*(?<body>.*?)\s*"#;'
)
if (-not $match.Success) {
  throw 'Cannot extract the embedded PowerShell training monitor.'
}

$url = 'http://127.0.0.1:48765/api/v1/training-runs/run-1'
$script:requests = [System.Collections.Generic.List[string]]::new()
$script:messages = [System.Collections.Generic.List[string]]::new()
$script:pollCount = 0
$script:sleeps = 0
$script:scenario = 'completed'

# Summary values deliberately lag the per-epoch history. The live monitor
# must display the latest actual box/cls/dfl epoch values, not stale summaries.
$script:active = @'
{
  "run_name": "Coral\u001b]0;spoofed console title\u0007 model",
  "status": "training",
  "stage": "fit",
  "progress_epoch": 2,
  "progress_total_epochs": 3,
  "metrics": {"train/box_loss": 0.99, "metrics/mAP50(B)": 0.75},
  "metrics_history": {
    "train/box_loss": [0.50, 0.25, null],
    "train/cls_loss": [0.60, 0.30, null],
    "train/dfl_loss": [0.20, 0.10, null]
  }
}
'@ | ConvertFrom-Json
$script:completed = @'
{
  "run_name": "Coral model",
  "status": "completed",
  "stage": "done",
  "progress_epoch": 3,
  "progress_total_epochs": 3,
  "metrics": {"train/box_loss": 0.99},
  "metrics_history": {
    "train/box_loss": [0.50, 0.25, 0.20, null],
    "train/cls_loss": [0.60, 0.30, 0.24, null],
    "train/dfl_loss": [0.20, 0.10, 0.08, null]
  }
}
'@ | ConvertFrom-Json
# A failed run must remain inspectable even when the optional persisted log
# endpoint is unavailable; cancellation must also terminate monitoring.
$script:terminalFailures = @{
  failed = [pscustomobject]@{
    run_name = 'Coral failure'
    status = 'failed'
    stage = 'fit'
    progress_epoch = 1
    progress_total_epochs = 3
    metrics = @{ 'train/box_loss' = 0.40 }
    metrics_history = @{}
    error_message = ('GPU out of memory ' + [char]0x001B + ']0;spoofed error title' + [char]0x0007 + ' training stopped')
  }
  cancelled = [pscustomobject]@{
    run_name = 'Coral cancelled'
    status = 'cancelled'
    stage = 'stopping'
    progress_epoch = 1
    progress_total_epochs = 3
    metrics = @{}
    metrics_history = @{}
    error_message = $null
  }
}
$script:logText = ('epoch=2', 'train/box_loss=0.25', 'train/cls_loss=0.30') -join [char]10
$script:logText += ([string][char]10) + ([string][char]0x001B) + ']0;spoofed log title' + ([string][char]0x0007) + 'train/dfl_loss=0.10'

function Invoke-RestMethod {
  param([string]$Uri, [string]$Method, [int]$TimeoutSec)
  if ($Method -cne 'Get') {
    throw "Monitor attempted a non-read-only API method: $Method"
  }
  [void]$script:requests.Add("$Method $Uri")
  if ($Uri -ceq $url) {
    $script:pollCount++
    if ($script:scenario -eq 'transient') {
      if ($script:pollCount -eq 1) {
        throw ('Temporary loopback outage ' + [char]0x001B + ']0;spoofed outage title' + [char]0x0007 + ' reconnecting')
      }
      if ($script:pollCount -eq 2) { return $script:active }
      if ($script:pollCount -eq 3) { return $script:completed }
      throw 'Monitor polled after recovering and observing completion.'
    }
    if ($script:scenario -ne 'completed') {
      if ($script:pollCount -eq 1) { return $script:terminalFailures[$script:scenario] }
      throw 'Monitor polled after a failed or cancelled training job.'
    }
    if ($script:pollCount -eq 1) { return $script:active }
    if ($script:pollCount -eq 2) { return $script:completed }
    throw 'Monitor polled after the training job ended.'
  }
  if ($Uri -ceq ($url + '/logs/tail')) {
    if ($script:scenario -eq 'failed') { throw 'Simulated persisted log outage.' }
    if ($script:scenario -eq 'cancelled') {
      return [pscustomobject]@{ available = $false; text = '' }
    }
    return [pscustomobject]@{ available = $true; text = $script:logText }
  }
  throw "Monitor requested an unexpected API endpoint: $Uri"
}

function Clear-Host {}
function Write-Host {
  param([Parameter(ValueFromRemainingArguments = $true)] [object[]]$Object)
  [void]$script:messages.Add(($Object -join ' '))
}
function Start-Sleep {
  param([int]$Seconds)
  if ($Seconds -ne 2) { throw "Unexpected polling interval: $Seconds" }
  $script:sleeps++
  $maxSleeps = if ($script:scenario -eq 'transient') { 2 } else { 1 }
  if ($script:sleeps -gt $maxSleeps) { throw 'Monitor failed to stop after completion.' }
}

# The production script runs unchanged; only its loopback GET responses,
# terminal display, and timer are mocked. It must exit on terminal status.
Invoke-Expression $match.Groups['body'].Value
$output = $script:messages -join [char]10
$expectedRequests = @(
  "Get $url",
  "Get $url/logs/tail",
  "Get $url",
  "Get $url/logs/tail"
)
if (($script:requests -join [char]10) -cne ($expectedRequests -join [char]10)) {
  throw "Unexpected monitor requests: $($script:requests -join ', ')"
}
if ($script:pollCount -ne 2 -or $script:sleeps -ne 1) {
  throw 'Monitor did not poll an active run and then stop after completion.'
}
# ConvertFrom-Json parses JSON numbers as numeric values, so PowerShell may
# display 0.30 as 0.3. Match equivalent values without accepting 0.31/0.21.
foreach ($expected in @(
  'Epoch: 2 / 3',
  'Epoch: 3 / 3',
  'train/box_loss\s+0\.25',
  'train/cls_loss\s+0\.3(?:0)?(?!\d)',
  'train/dfl_loss\s+0\.1(?:0)?(?!\d)',
  'train/box_loss\s+0\.2(?:0)?(?!\d)',
  'train/cls_loss\s+0\.24',
  'train/dfl_loss\s+0\.08',
  'metrics/mAP50\(B\)\s+0\.75',
  'Training job log \(last 20 lines, read-only\)',
  'Run ended\. This window can now be closed\.'
)) {
  if ($output -notmatch $expected) {
    throw "Missing live training monitor output: $expected"
  }
}
if ($output -match 'train/box_loss\s+0\.99') {
  throw 'Stale summary loss overrode the latest persisted epoch history.'
}
if ($output.Contains('spoofed console title') -or $output.Contains('spoofed log title')) {
  throw 'Untrusted run metadata or persisted logs escaped display sanitization.'
}
# Both terminal error states must stop polling immediately. A missing log tail
# must not hide the failure status or the sanitized diagnostic message.
foreach ($terminalStatus in @('failed', 'cancelled')) {
  $script:scenario = $terminalStatus
  $script:requests.Clear()
  $script:messages.Clear()
  $script:pollCount = 0
  $script:sleeps = 0
  Invoke-Expression $match.Groups['body'].Value
  $terminalOutput = $script:messages -join [char]10
  $expectedTerminalRequests = @("Get $url", "Get $url/logs/tail")
  if (($script:requests -join [char]10) -cne ($expectedTerminalRequests -join [char]10)) {
    throw "Unexpected $terminalStatus monitor requests: $($script:requests -join ', ')"
  }
  if ($script:pollCount -ne 1 -or $script:sleeps -ne 0) {
    throw "Monitor did not stop immediately after $terminalStatus."
  }
  if (-not $terminalOutput.Contains("Status: $terminalStatus") -or
      -not $terminalOutput.Contains('Run ended. This window can now be closed.')) {
    throw "Missing $terminalStatus terminal-state monitor output."
  }
  if ($terminalStatus -eq 'failed') {
    if (-not $terminalOutput.Contains('Training job log unavailable (status/metrics remain live).') -or
        -not $terminalOutput.Contains('GPU out of memory') -or
        -not $terminalOutput.Contains('training stopped') -or
        $terminalOutput.Contains('spoofed error title')) {
      throw 'Failed-run diagnostics were hidden or terminal escape text was not sanitized.'
    }
  } elseif (-not $terminalOutput.Contains('No persisted training job log available yet.')) {
    throw 'Cancelled-run monitor did not handle an unavailable persisted log.'
  }
}
# A temporary loopback/API outage must never cancel or interrupt the
# training worker. Reconnect with GET-only requests and stop after observing
# the worker's actual terminal state. Sanitize errors before displaying them.
$script:scenario = 'transient'
$script:requests.Clear()
$script:messages.Clear()
$script:pollCount = 0
$script:sleeps = 0
Invoke-Expression $match.Groups['body'].Value
$recoveryOutput = $script:messages -join [char]10
$expectedRecoveryRequests = @(
  "Get $url",
  "Get $url",
  "Get $url/logs/tail",
  "Get $url",
  "Get $url/logs/tail"
)
if (($script:requests -join [char]10) -cne ($expectedRecoveryRequests -join [char]10)) {
  throw "Unexpected monitor requests during transient API recovery: $($script:requests -join ', ')"
}
if ($script:pollCount -ne 3 -or $script:sleeps -ne 2) {
  throw 'Monitor failed to recover from an API outage and stop after completion.'
}
foreach ($expected in @(
  'Waiting for ReefVision training status:',
  'Temporary loopback outage',
  'Status: training',
  'Status: completed',
  'train/box_loss\s+0\.25',
  'train/dfl_loss\s+0\.08',
  'Run ended\. This window can now be closed\.'
)) {
  if ($recoveryOutput -notmatch $expected) {
    throw "Missing transient-recovery monitor output: $expected"
  }
}
if ($recoveryOutput.Contains('spoofed outage title')) {
  throw 'Untrusted API outage diagnostics escaped console sanitization.'
}

Write-Output 'PowerShell training monitor read-only polling, terminal-state, loss, and transient-recovery regressions passed.'
