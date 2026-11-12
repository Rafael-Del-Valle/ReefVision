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

# Validate the real monitor's metric gate: strings, booleans, NaN and infinity
# must never be displayed as measured training losses. Finite numeric values
# (including a real zero) must remain eligible for the box/cls/dfl display.
$finiteMatch = [regex]::Match($source, '(?ms)^function Test-FiniteMetricValue \{.*?^\}')
if (-not $finiteMatch.Success) {
  throw 'Training monitor must define Test-FiniteMetricValue.'
}
Invoke-Expression $finiteMatch.Value
foreach ($valid in @(0, 0.25, -0.125, [decimal]1.5, [single]0.75, [double]::Epsilon, [double]::MaxValue)) {
  if (-not (Test-FiniteMetricValue -Value $valid)) {
    throw ('Finite training metric was rejected: {0}' -f $valid)
  }
}
# A training-run API response may contain JSON arrays/objects or timestamp fields.
# None is a scalar measured loss, even if PowerShell would coerce it to text.
foreach ($invalid in @($null, $true, $false, '0.00', 'NaN', [double]::NaN, [double]::PositiveInfinity, [double]::NegativeInfinity,
    [datetime]'2026-01-01', [char]'1', [System.DayOfWeek]::Monday, @{ value = 0.25 }, [double]::PositiveInfinity, [single]::NaN)) {
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
if ($monitorScript -notmatch 'Start-Sleep\s+-Seconds\s+2\b') {
  throw 'Read-only polling throttle was removed from training monitor.'
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

Write-Host 'PowerShell training console sanitizer regression passed.'
