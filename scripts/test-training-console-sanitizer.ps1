# Verify the actual PowerShell formatter embedded in the Tauri training monitor.
# This test runs on the existing Windows installer CI runner without a model,
# training process, network connection, or any write to user data.
$ErrorActionPreference = 'Stop'
$main = Join-Path $PSScriptRoot '../apps/web/src-tauri/src/main.rs'
$source = Get-Content -LiteralPath $main -Raw
$match = [regex]::Match($source, '(?ms)^function Format-SafeText \{.*?^\}')
if (-not $match.Success) {
  throw 'Training monitor must define Format-SafeText.'
}
Invoke-Expression $match.Value

$unsafe = 'Study' + [char]0x001B + '[2J' + [char]0x001B + ']0;fake terminal title' + [char]0x0007 + [char]0x202E + "`ntrain/dfl_loss=0.00"
$actual = Format-SafeText $unsafe
if ($actual -match '[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]') {
  throw 'A terminal or invisible control escaped sanitization.'
}
if ($actual.Contains('fake terminal title')) {
  throw 'An OSC title payload escaped sanitization.'
}
if (-not $actual.Contains('Study') -or -not $actual.Contains('train/dfl_loss=0.00')) {
  throw 'Safe visible content was unexpectedly discarded.'
}

$c1 = "Epoch" + [char]0x009D + '0;fake title' + [char]0x009C + ' 3'
if ((Format-SafeText $c1) -ne 'Epoch 3') {
  throw 'C1 control string was not removed.'
}

# Some workers terminate OSC/DCS strings with the 8-bit C1 ST character.
# The monitor must remove the control payload without hiding later real losses.
$c1St = [char]0x009C
$oscC1St = 'train/box_loss=0.25' + [char]0x001B + ']0;spoofed title' + $c1St + ' train/cls_loss=0.30'
if ((Format-SafeText $oscC1St) -cne 'train/box_loss=0.25 train/cls_loss=0.30') {
  throw 'C1 ST-terminated OSC concealed a real training loss.'
}
$dcsC1St = 'train/cls_loss=0.30' + [char]0x001B + 'Pgraphics payload' + $c1St + ' train/dfl_loss=0.10'
if ((Format-SafeText $dcsC1St) -cne 'train/cls_loss=0.30 train/dfl_loss=0.10') {
  throw 'C1 ST-terminated DCS concealed a real training loss.'
}

$scientific = 'train/box_loss=0.25; scale=10 µm; temp=24 °C'
if ((Format-SafeText $scientific) -cne $scientific) {
  throw 'Scientific units or loss values were altered.'
}
# Worker output may end mid-ANSI sequence. Its numeric parameters must never
# be appended to genuine box/cls/dfl losses in the external console.
$incompleteEscCsi = 'train/box_loss=0.25' + [char]0x001B + '[31'
if ((Format-SafeText $incompleteEscCsi) -cne 'train/box_loss=0.25') {
  throw 'Incomplete ESC CSI fabricated or contaminated a training loss.'
}
$incompleteC1Csi = 'train/cls_loss=0.30' + [char]0x009B + '31'
if ((Format-SafeText $incompleteC1Csi) -cne 'train/cls_loss=0.30') {
  throw 'Incomplete C1 CSI fabricated or contaminated a training loss.'
}
$incompleteBeforeNewline = 'train/dfl_loss=0.10' + [char]0x001B + '[31' + [char]10 + 'epoch=4'
if ((Format-SafeText $incompleteBeforeNewline) -cne 'train/dfl_loss=0.10 epoch=4') {
  throw 'Incomplete CSI before a newline altered scientific loss or epoch text.'
}
if ((Format-SafeText $null) -ne '') {
  throw 'Null metadata must render as empty text.'
}
# Imported filenames, model labels, and persisted worker log lines can be
# arbitrarily long. The monitor must bound only its rendered copy, leaving
# actual persisted training logs and scientific provenance untouched.
$oversized = ('X' * 5000) + 'hidden train/box_loss=0.00'
$bounded = Format-SafeText $oversized
if ($bounded.Length -gt 1040 -or -not $bounded.EndsWith(' [truncated]') -or
    $bounded.Contains('hidden train/box_loss=0.00')) {
  throw 'Oversized untrusted monitor fields were not bounded for display.'
}
# The initial 4096-character cap may split an ANSI OSC control sequence.
# The sanitizer must still discard its unterminated payload, not render it.
$unterminatedOsc = 'prefix ' + [char]0x001B + ']0;' + ('spoofed' * 800) + [char]0x0007 + 'real text'
if ((Format-SafeText $unterminatedOsc) -cne 'prefix ') {
  throw 'A truncated terminal-control payload escaped display sanitization.'
}
# The actual persisted log-tail rendering must sanitize untrusted log bytes,
# not only the run name and metric metadata. Keep this source assertion next
# to the executable formatter regression so removing the call fails Windows CI.
$tailLoop = [regex]::Match($source, '(?ms)foreach \(\$line in \(\$logLines \| Select-Object -Last 20\)\) \{(?<body>.*?)^\s*\}')
if (-not $tailLoop.Success -or $tailLoop.Groups['body'].Value -notmatch 'Write-Host\s+\(Format-SafeText\s+\$line\)') {
  throw 'Persisted training log tail must pass through Format-SafeText before Write-Host.'
}
$unsafeLog = 'train/box_loss=0.25' + [char]0x001B + '[2J' + [char]0x001B + ']0;spoofed log title' + [char]0x0007 + [char]0x202E + ' epoch 4'
$safeLog = Format-SafeText $unsafeLog
if ($safeLog -match '[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]' -or $safeLog.Contains('spoofed log title')) {
  throw 'Persisted training log control characters escaped display sanitization.'
}
if (-not $safeLog.Contains('train/box_loss=0.25') -or -not $safeLog.Contains('epoch 4')) {
  throw 'Sanitization removed valid training loss or epoch information.'
}

# A malicious imported run name can contain bidirectional isolate controls or
# terminal hyperlinks. Neither may change how the scientific loss line appears.
$bidi = 'train/box_loss=0.25' + [char]0x2066 + 'hidden' + [char]0x2069 + ' train/cls_loss=0.30'
$bidiSafe = Format-SafeText $bidi
if ($bidiSafe -match '[\p{Cf}]' -or -not $bidiSafe.Contains('train/box_loss=0.25') -or
    -not $bidiSafe.Contains('train/cls_loss=0.30')) {
  throw 'Bidirectional formatting controls corrupted scientific loss display.'
}
$hyperlink = 'epoch=4 ' + [char]0x001B + ']8;;https://example.invalid/unsafe' + [char]0x001B + '\\' +
  'train/dfl_loss=0.10' + [char]0x001B + ']8;;' + [char]0x001B + '\\'
$hyperlinkSafe = Format-SafeText $hyperlink
if ($hyperlinkSafe.Contains('example.invalid') -or
    -not $hyperlinkSafe.Contains('epoch=4') -or
    -not $hyperlinkSafe.Contains('train/dfl_loss=0.10')) {
  throw 'OSC 8 terminal hyperlink escaped or obscured training loss display.'
}

# Scientific worker logs may contain 8-bit C1 OSC/DCS introductions rather
# than ESC-prefixed forms. Their payloads must not masquerade as epoch losses.
$c1Osc = 'train/box_loss=0.25' + [char]0x009D + '0;forged train/dfl_loss=0.00' + [char]0x009C + ' train/cls_loss=0.30'
if ((Format-SafeText $c1Osc) -cne 'train/box_loss=0.25 train/cls_loss=0.30') {
  throw 'C1 OSC payload leaked a forged training loss.'
}
$c1Dcs = 'epoch=5' + [char]0x0090 + 'forged train/box_loss=0.00' + [char]0x009C + ' train/dfl_loss=0.10'
if ((Format-SafeText $c1Dcs) -cne 'epoch=5 train/dfl_loss=0.10') {
  throw 'C1 DCS payload leaked a forged training loss.'
}

# Validate the real monitor's metric gate: strings, booleans, NaN and infinity
# must never be displayed as measured training losses. Finite numeric values
# (including a real zero) must remain eligible for the box/cls/dfl display.
$finiteMatch = [regex]::Match($source, '(?ms)^function Test-FiniteMetricValue \{.*?^\}')
if (-not $finiteMatch.Success) {
  throw 'Training monitor must define Test-FiniteMetricValue.'
}
Invoke-Expression $finiteMatch.Value
# Losses may be serialized as integer, decimal, single or double precision. Keep
# signed finite extrema valid without allowing nonfinite IEEE-754 sentinels.
foreach ($valid in @(0, 0.25, -0.125, [decimal]1.5, [decimal]::MaxValue,
    [single]0.75, [single]::Epsilon, [single]::MaxValue,
    [double]::Epsilon, [double]::MaxValue, [int]::MinValue, [long]::MaxValue)) {
  if (-not (Test-FiniteMetricValue -Value $valid)) {
    throw ('Finite training metric was rejected: {0}' -f $valid)
  }
}
# A training-run API response may contain JSON arrays/objects or timestamp fields.
# None is a scalar measured loss, even if PowerShell would coerce it to text.
foreach ($invalid in @($null, $true, $false, '0.00', 'NaN', [double]::NaN, [double]::PositiveInfinity, [double]::NegativeInfinity,
    [datetime]'2026-01-01', [char]'1', [System.DayOfWeek]::Monday, @{ value = 0.25 }, [single]::NaN, [single]::NegativeInfinity)) {
  if (Test-FiniteMetricValue -Value $invalid) {
    throw ('Untrusted or nonfinite training metric was accepted: {0}' -f $invalid)
  }
}

# Keep this separate: PowerShell automatically flattens nested arrays in @(...).
# Passing the array as one -Value argument must still be rejected.
$structuredLoss = @(0.25, 0.30)
if (Test-FiniteMetricValue -Value $structuredLoss) {
  throw 'A vector of loss measurements was accepted as one scalar loss.'
}


# PowerShell single-quoted regex strings use one backslash for regex escapes.
# Double backslashes would match literal backslashes instead of HTTP verbs,
# allowing the request inventory assertion to miss the real monitor calls.
# The external monitor must remain a passive observer of the existing worker.
# Check the actual embedded PowerShell script, not a mock monitor: a future
# refactor must not add a mutation request, job launch, or process termination.
$monitorStart = $source.IndexOf("let script = format!")
$monitorEnd = $source.IndexOf('Command::new("powershell.exe")', $monitorStart)
if ($monitorStart -lt 0 -or $monitorEnd -le $monitorStart) {
  throw 'Could not isolate the external training monitor script.'
}
$monitorScript = $source.Substring($monitorStart, $monitorEnd - $monitorStart)
$requests = [regex]::Matches($monitorScript, 'Invoke-RestMethod\b[^\r\n]*')
if ($requests.Count -ne 2) {
  throw 'Training monitor HTTP request inventory changed; review read-only guarantees.'
}
foreach ($request in $requests) {
  if ($request.Value -notmatch '-Method\s+Get\b' -or
      $request.Value -notmatch '-MaximumRedirection\s+0\b') {
    throw 'Training monitor HTTP requests must use GET without redirects.'
  }
}
if ($monitorScript -match '(?i)\b(?:Start-Process|Stop-Process|Invoke-Expression|Invoke-Command|Remove-Item|Set-Content|Add-Content|Out-File)\b') {
  throw 'External monitor must not execute commands or mutate training artifacts.'
}
# GET-only checks must also prevent bypass through alternate PowerShell HTTP clients
# or a second process. This is a source-level safety contract, not a live-job test.
if ($monitorScript -match '(?i)\b(?:Invoke-WebRequest|Start-BitsTransfer|Start-Job|Start-ThreadJob|New-Item|Set-Item|Copy-Item|Move-Item|Export-Csv|Export-Clixml|Tee-Object)\b' -or
    $monitorScript -match '(?i)\b(?:curl(?:\.exe)?|wget(?:\.exe)?|bitsadmin(?:\.exe)?)\b' -or
    $monitorScript -match '(?i)\[System\.Net\.Http\.HttpClient\]|\[System\.Net\.WebClient\]') {
  throw 'External training monitor introduced an alternate network, process, or artifact-write path.'
}
# PowerShell single-quoted regexes require single backslashes for regex tokens.
# Both polling requests must have finite timeouts. A hung local API must not
# leave the external observer indefinitely blocked or interfere with training.
if ($requests[0].Value -notmatch '-TimeoutSec\s+10\b' -or
    $requests[1].Value -notmatch '-TimeoutSec\s+5\b') {
  throw 'Training monitor status and log requests must retain bounded timeouts.'
}
# Persisted logs may contain CR-only progress updates; display only the most
# recent 20 lines, without rewriting the worker log or losing progress records.
if ($monitorScript -notmatch [regex]::Escape("-split '\r\n|\r|\n'") -or
    $monitorScript -notmatch 'Select-Object\s+-Last\s+20\b') {
  throw 'Training log tail must support CR/LF progress and remain bounded to 20 lines.'
}
if ($monitorScript -notmatch 'Start-Sleep\s+-Seconds\s+2\b') {
  throw 'Read-only polling throttle was removed from training monitor.'
}

# The desktop command must reject shell metacharacters before constructing the
# monitor URL, and the API origin must come from trusted desktop state rather
# than a renderer-supplied URL. These are source-level security assertions.
$runIdGuard = [regex]::Match($source, '(?s)fn valid_training_run_id\(run_id: &str\) -> bool \{(?<body>.*?)\n\}')
if (-not $runIdGuard.Success -or
    $runIdGuard.Groups['body'].Value -notmatch 'run_id\.len\(\) <= 72' -or
    $runIdGuard.Groups['body'].Value -notmatch 'byte\.is_ascii_alphanumeric\(\)' -or
    $runIdGuard.Groups['body'].Value -notmatch 'byte == b''-''' -or
    $runIdGuard.Groups['body'].Value -notmatch 'byte == b''_''') {
  throw 'Training run IDs must remain bounded to opaque ASCII alphanumeric/hyphen/underscore identifiers.'
}
$consoleCommand = [regex]::Match($source, '(?s)fn open_training_console\(.*?\n\}')
if (-not $consoleCommand.Success -or
    $consoleCommand.Value -notmatch 'if !valid_training_run_id\(&run_id\)' -or
    $consoleCommand.Value -notmatch 'state\.context\.api_base_url' -or
    $consoleCommand.Value -match 'frontend_api_base_url|renderer_api_base_url') {
  throw 'Training monitor must validate the run ID and use the trusted desktop API origin.'
}
# -NoExit exposes an unrestricted PowerShell prompt after the read-only observer
# reaches a terminal state. Keep the final logs visible with an idle observer
# instead; no interactive command surface or training write access is permitted.
# The Rust function contains unindented braces inside the embedded PowerShell
# raw string. Do not use $consoleCommand's first-brace regex to inspect Rust's
# process launcher: it stops at a PowerShell function before .args() appears.
$launcher = [regex]::Match(
  $source,
  '(?s)Command::new\("powershell\.exe"\)\s*\.args\(\["-NoProfile", "-NonInteractive", "-Command", &script\]\)\s*\.spawn\(\)'
)
if (-not $launcher.Success -or
    $launcher.Value -match '"-NoExit"') {
  throw 'External training console must not expose an interactive PowerShell prompt.'
}
if ($monitorScript -notmatch 'while \(\$true\) \{ Start-Sleep -Seconds 3600 \}') {
  throw 'Final read-only training status must remain inspectable without -NoExit.'
}

# Protect the actual loss-source precedence: the newest finite persisted epoch
# history must override stale summary metrics, not the reverse. These are
# source-contract assertions; live GPU training remains a separate acceptance gate.
$summaryIndex = $monitorScript.IndexOf('foreach ($metric in $run.metrics.PSObject.Properties)')
$historyIndex = $monitorScript.IndexOf('foreach ($series in $run.metrics_history.PSObject.Properties)')
$historyReverseIndex = $monitorScript.IndexOf('for ($index = $values.Count - 1; $index -ge 0; $index -= 1)')
$historyAssignIndex = $monitorScript.IndexOf('$latestMetrics[$series.Name] = $values[$index]')
if ($summaryIndex -lt 0 -or $historyIndex -le $summaryIndex -or
    $historyReverseIndex -le $historyIndex -or $historyAssignIndex -le $historyReverseIndex) {
  throw 'Newest persisted epoch losses must override stale summary metrics.'
}
foreach ($lossKey in @('train/box_loss', 'train/cls_loss', 'train/dfl_loss')) {
  if (-not $monitorScript.Contains("'" + $lossKey + "'")) {
    throw ('Required measured training loss is missing: {0}' -f $lossKey)
  }
}
if ($monitorScript -notmatch 'Test-FiniteMetricValue\s+-Value\s+\$values\[\$index\]') {
  throw 'Persisted epoch loss history must reject nonfinite measurements.'
}

# Execute the monitor's real summary/history selection block against a synthetic
# persisted run. Source-order assertions alone cannot catch a precedence bug.
$selectionStart = $monitorScript.IndexOf('    $latestMetrics = @{}')
$selectionEnd = $monitorScript.IndexOf('    $trainingLosses = @(', $selectionStart)
if ($selectionStart -lt 0 -or $selectionEnd -le $selectionStart) {
  throw 'Could not isolate persisted training metric selection.'
}
$selectionCode = $monitorScript.Substring($selectionStart, $selectionEnd - $selectionStart)
$run = [pscustomobject]@{
  metrics = [pscustomobject]@{
    'train/box_loss' = 9.0
    'train/cls_loss' = 8.0
    'train/dfl_loss' = 7.0
  }
  metrics_history = [pscustomobject]@{
    'train/box_loss' = @(0.5, [double]::NaN, 0.25)
    'train/cls_loss' = @(0.8, 0.3, [double]::PositiveInfinity)
    'train/dfl_loss' = @($null, 0.1)
  }
}
Invoke-Expression $selectionCode
if ($latestMetrics['train/box_loss'] -ne 0.25 -or
    $latestMetrics['train/cls_loss'] -ne 0.3 -or
    $latestMetrics['train/dfl_loss'] -ne 0.1) {
  throw 'Latest finite persisted box/cls/dfl losses did not override stale summaries.'
}
# A trailing nonfinite sample must be disclosed, but a valid last sample must
# not be mislabeled as stale. This describes the history entry, not an assumed
# biological observation or an inferred training epoch.
if ($staleMetricSamples['train/cls_loss'] -cne ' [prior history entry 2/3; latest unavailable]' -or
    $staleMetricSamples.ContainsKey('train/box_loss') -or
    $staleMetricSamples.ContainsKey('train/dfl_loss')) {
  throw 'Training monitor misstated the provenance/freshness of recorded loss samples.'
}
# When a series has no finite epoch sample, retain its finite summary rather
# than inventing a zero or showing an invalid sentinel.
$run.metrics_history = [pscustomobject]@{
  'train/box_loss' = @([double]::NaN, [double]::PositiveInfinity)
}
Invoke-Expression $selectionCode
if ($latestMetrics['train/box_loss'] -ne 9.0) {
  throw 'Invalid epoch history must not erase the last finite summary loss.'
}
if ($staleMetricSamples['train/box_loss'] -cne ' [summary fallback; no finite history entry among 2]' -or
    $staleMetricSamples.ContainsKey('train/cls_loss')) {
  throw 'Invalid epoch history summary fallback provenance was not disclosed.'
}

# An epoch value of zero is a legitimate measurement and must override stale
# summary losses. Non-numeric JSON values and nonfinite trailing entries must
# never displace the latest finite measurement for any loss component.
$run = [pscustomobject]@{
  metrics = [pscustomobject]@{
    'train/box_loss' = 4.0
    'train/cls_loss' = 5.0
    'train/dfl_loss' = 6.0
  }
  metrics_history = [pscustomobject]@{
    'train/box_loss' = @(0.9, 0.0, '0.000')
    'train/cls_loss' = @(0.7, 0.0, $false)
    'train/dfl_loss' = @(0.6, 0.0, [double]::NegativeInfinity)
  }
}
Invoke-Expression $selectionCode
foreach ($lossKey in @('train/box_loss', 'train/cls_loss', 'train/dfl_loss')) {
  if (-not $latestMetrics.ContainsKey($lossKey) -or
      $latestMetrics[$lossKey] -ne 0.0) {
    throw ('Zero-valued persisted epoch loss was discarded: {0}' -f $lossKey)
  }
}
# A history with only invalid values cannot manufacture a measurement when
# the summary is invalid too.
$run.metrics = [pscustomobject]@{
  'train/box_loss' = 'not-a-measurement'
}
$run.metrics_history = [pscustomobject]@{
  'train/box_loss' = @($null, [double]::NaN, '0.2')
}
Invoke-Expression $selectionCode
if ($latestMetrics.ContainsKey('train/box_loss')) {
  throw 'Invalid summary/history values fabricated a box-loss measurement.'
}
if ($staleMetricSamples.ContainsKey('train/box_loss')) {
  throw 'No finite loss existed, but a fallback annotation was fabricated.'
}


# A newly created training job may have a finite summary before its first epoch
# history is persisted. Empty series must not erase that measured summary.
$run = [pscustomobject]@{
  metrics = [pscustomobject]@{
    'train/box_loss' = 0.42
    'train/cls_loss' = 0.37
    'train/dfl_loss' = 0.19
  }
  metrics_history = [pscustomobject]@{
    'train/box_loss' = @()
    'train/cls_loss' = @()
    'train/dfl_loss' = @()
  }
}
Invoke-Expression $selectionCode
foreach ($expected in @(
  @{ key = 'train/box_loss'; value = 0.42 },
  @{ key = 'train/cls_loss'; value = 0.37 },
  @{ key = 'train/dfl_loss'; value = 0.19 }
)) {
  if (-not $latestMetrics.ContainsKey($expected.key) -or
      $latestMetrics[$expected.key] -ne $expected.value) {
    throw ('Empty epoch history erased a finite summary loss: {0}' -f $expected.key)
  }
}
if ($staleMetricSamples.Count -ne 0) {
  throw 'Empty history was mistaken for an invalid observed epoch.'
}
# Conversely, no metric may appear when the worker has not yet recorded any.
$run.metrics = [pscustomobject]@{}
$run.metrics_history = [pscustomobject]@{}
Invoke-Expression $selectionCode
if ($latestMetrics.Count -ne 0) {
  throw 'An unstarted training run fabricated a loss measurement.'
}

# A persisted history can contain unrelated scientific or validation metrics.
# The monitor must retain their original keys and not confuse them with
# training losses; each loss series must select its own latest finite sample.
$run = [pscustomobject]@{
  metrics = [pscustomobject]@{
    'train/box_loss' = 0.91
    'train/cls_loss' = 0.82
    'train/dfl_loss' = 0.73
    'val/box_loss' = 0.64
  }
  metrics_history = [pscustomobject]@{
    'train/box_loss' = @(0.51, 0.41)
    'train/cls_loss' = @(0.32, [double]::NaN)
    'train/dfl_loss' = @(0.23, 0.13)
    'val/box_loss' = @(0.61, 0.52)
  }
}
Invoke-Expression $selectionCode
foreach ($expected in @(
  @{ key = 'train/box_loss'; value = 0.41 },
  @{ key = 'train/cls_loss'; value = 0.32 },
  @{ key = 'train/dfl_loss'; value = 0.13 },
  @{ key = 'val/box_loss'; value = 0.52 }
)) {
  if (-not $latestMetrics.ContainsKey($expected.key) -or
      $latestMetrics[$expected.key] -ne $expected.value) {
    throw ('Independent metric history selection failed: {0}' -f $expected.key)
  }
}
if ($latestMetrics.Count -ne 4) {
  throw 'Metric selection introduced unexpected or fabricated keys.'
}
if ($staleMetricSamples['train/cls_loss'] -cne ' [prior history entry 1/2; latest unavailable]' -or
    $staleMetricSamples.ContainsKey('val/box_loss')) {
  throw 'Stale training history and current validation history were conflated.'
}

# Sparse histories are common when a worker persists different loss keys at
# different epochs. A metric's own latest finite sample must win; a missing
# history key must preserve its finite summary, not borrow another series.
$run = [pscustomobject]@{
  metrics = [pscustomobject]@{
    'train/box_loss' = 0.75
    'train/cls_loss' = 0.65
    'train/dfl_loss' = 0.55
    'val/cls_loss' = 0.45
  }
  metrics_history = [pscustomobject]@{
    'train/box_loss' = @(0.35, [double]::NaN, 0.15)
    'train/dfl_loss' = @([double]::PositiveInfinity, 0.25)
  }
}
Invoke-Expression $selectionCode
foreach ($expected in @(
  @{ key = 'train/box_loss'; value = 0.15 },
  @{ key = 'train/cls_loss'; value = 0.65 },
  @{ key = 'train/dfl_loss'; value = 0.25 },
  @{ key = 'val/cls_loss'; value = 0.45 }
)) {
  if (-not $latestMetrics.ContainsKey($expected.key) -or
      $latestMetrics[$expected.key] -ne $expected.value) {
    throw ('Sparse epoch histories changed independent metric provenance: {0}' -f $expected.key)
  }
}
if ($latestMetrics.Count -ne 4) {
  throw 'Sparse epoch histories fabricated or discarded a metric key.'
}


# Persisted JSON histories may mix numeric scalar types across epochs. The
# latest finite numeric scalar wins regardless of integer/decimal/single/double
# representation; a trailing string that looks numeric must not be coerced.
$run = [pscustomobject]@{
  metrics = [pscustomobject]@{
    'train/box_loss' = 8
    'train/cls_loss' = 7
    'train/dfl_loss' = 6
  }
  metrics_history = [pscustomobject]@{
    'train/box_loss' = @(2, [decimal]0.125, '0.001')
    'train/cls_loss' = @([single]0.5, 0, [double]::NaN)
    'train/dfl_loss' = @([double]0.75, [single]0.25, $true)
  }
}
Invoke-Expression $selectionCode
foreach ($expected in @(
  @{ key = 'train/box_loss'; value = [decimal]0.125 },
  @{ key = 'train/cls_loss'; value = 0 },
  @{ key = 'train/dfl_loss'; value = [single]0.25 }
)) {
  if (-not $latestMetrics.ContainsKey($expected.key) -or
      $latestMetrics[$expected.key] -ne $expected.value) {
    throw ('Mixed numeric epoch history lost the latest finite scalar: {0}' -f $expected.key)
  }
}
if ($latestMetrics.Count -ne 3) {
  throw 'Mixed numeric epoch histories introduced an unexpected metric.'
}

Write-Host 'PowerShell training console sanitizer regression passed.'
