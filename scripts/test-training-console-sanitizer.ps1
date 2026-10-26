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

$scientific = 'train/box_loss=0.25; scale=10 µm; temp=24 °C'
if ((Format-SafeText $scientific) -cne $scientific) {
  throw 'Scientific units or loss values were altered.'
}
if ((Format-SafeText $null) -ne '') {
  throw 'Null metadata must render as empty text.'
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

Write-Host 'PowerShell training console sanitizer regression passed.'
