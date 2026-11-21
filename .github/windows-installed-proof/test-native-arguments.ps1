param(
    [Parameter(Mandatory)][string]$NodePath,
    [Parameter(Mandatory)][string]$Scratch,
    [string]$Library = (Join-Path $PSScriptRoot 'lib/windows-spatial-webview2-acceptance.ps1')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (Test-Path -LiteralPath $Scratch) { throw 'The native argument test requires a fresh scratch directory.' }
$scratchRoot = [IO.Path]::GetFullPath($Scratch)
$repo = Join-Path $scratchRoot 'checkout with spaces'
$cli = Join-Path $repo 'apps/web/node_modules/@playwright/test/cli.js'
$null = New-Item -ItemType Directory -Path (Split-Path -Parent $cli)
@'
const fs = require("node:fs");
const count = Number(process.env.REEFVISION_NATIVE_ARGUMENT_TEST_COUNT);
fs.writeFileSync(process.env.PLAYWRIGHT_JSON_OUTPUT_FILE, JSON.stringify({
  arguments: process.argv.slice(2),
  stats: { expected: count, skipped: 0, unexpected: 0, flaky: 0 },
}));
'@ | Set-Content -LiteralPath $cli -Encoding utf8
. $Library

# The test replaces only the attachment lookup. A real Windows Node process
# receives the original PowerShell function's native command line.
function Wait-ReefVisionWebView2DebugEndpoint {
    param([int]$Port, [int]$DesktopProcessId, [string]$ExpectedBrowserSid,
        [string]$FailureEvidencePath, [string]$AttachmentEvidencePath)
    return "http://127.0.0.1:$Port"
}

foreach ($suite in 'research-tools','first-use','workspace') {
    $specs = switch ($suite) {
        'research-tools' { @('taxonomy-detectability-live.spec.ts','bioacoustics-live.spec.ts') }
        'first-use' { @('ordinary-project-live.spec.ts') }
        'workspace' { @('safe-class-lifecycle-live.spec.ts','qc-review-workflow-live.spec.ts') }
    }
    $specs = @($specs)
    $evidence = Join-Path $scratchRoot $suite
    $null = New-Item -ItemType Directory -Path $evidence
    $null = Invoke-ReefVisionInstalledPlaywrightSuite -NodePath $NodePath -RepositoryRoot $repo -EvidenceRoot $evidence `
        -Api 'http://127.0.0.1:1/api/v1' -DebugPort 1 -DesktopProcessId 1 -Suite $suite -Specs $specs `
        -AdditionalEnvironment @{REEFVISION_NATIVE_ARGUMENT_TEST_COUNT=[string]$specs.Count}
    $actual = (Get-Content -LiteralPath (Join-Path $evidence "$suite-playwright.json") -Raw | ConvertFrom-Json).arguments
    $trace = @(if ($suite -ceq 'research-tools') { '--trace=off' })
    $expected = @('test') + $specs + $trace + @('--workers=1','--retries=0','--reporter=list,json',"--output=$evidence\$suite-playwright")
    if (($actual -join "`n") -cne ($expected -join "`n")) {
        throw "Native $suite argument order and boundaries differed. Expected [$($expected -join ' | ')], got [$($actual -join ' | ')]."
    }
}
Write-Output 'Windows native argv preserves selected specs, one research trace flag and zero unrelated trace arguments.'
