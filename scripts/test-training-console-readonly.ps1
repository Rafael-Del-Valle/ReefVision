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
    "train/box_loss": [0.50, 0.25],
    "train/cls_loss": [0.60, 0.30],
    "train/dfl_loss": [0.20, 0.10]
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
    "train/box_loss": [0.50, 0.25, 0.20],
    "train/cls_loss": [0.60, 0.30, 0.24],
    "train/dfl_loss": [0.20, 0.10, 0.08]
  }
}
'@ | ConvertFrom-Json
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
    if ($script:pollCount -eq 1) { return $script:active }
    if ($script:pollCount -eq 2) { return $script:completed }
    throw 'Monitor polled after the training job ended.'
  }
  if ($Uri -ceq ($url + '/logs/tail')) {
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
  if ($script:sleeps -gt 1) { throw 'Monitor failed to stop after completion.' }
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
foreach ($expected in @(
  'Epoch: 2 / 3',
  'Epoch: 3 / 3',
  'train/box_loss\s+0\.25',
  'train/cls_loss\s+0\.30',
  'train/dfl_loss\s+0\.10',
  'train/box_loss\s+0\.20',
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
Write-Output 'PowerShell training monitor read-only polling and loss regression passed.'
