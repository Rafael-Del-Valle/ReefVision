Set-StrictMode -Version Latest

function Get-ReefVisionLoopbackDebugPort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return $listener.LocalEndpoint.Port
    } finally {
        $listener.Stop()
    }
}

function Wait-ReefVisionWebView2DebugEndpoint {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][int]$DesktopProcessId
    )

    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        foreach ($listener in $listeners) {
            if ($listener.LocalAddress -notin @('127.0.0.1', '::1')) {
                throw "WebView2 debugging is not limited to loopback on port $Port."
            }
            $ownerId = $listener.OwningProcess
            $owner = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $ownerId"
            if (-not $owner -or $owner.Name -ine 'msedgewebview2.exe' -or $owner.ParentProcessId -ne $DesktopProcessId) {
                throw "The listener on port $Port does not belong to this acceptance WebView2 process."
            }
        }
        if ($listeners.Count -gt 0 -and $listeners.LocalAddress -contains '127.0.0.1') {
            $version = $null
            try {
                $version = Invoke-RestMethod "http://127.0.0.1:$Port/json/version" -NoProxy -TimeoutSec 3
            } catch {
                # The listener can appear before Chromium finishes starting CDP.
            }
            if ($version) {
                $endpoint = [string]$version.webSocketDebuggerUrl
                if ($endpoint -notmatch "^ws://127[.]0[.]0[.]1:$Port/devtools/browser/[a-f0-9-]+$") {
                    throw 'WebView2 reported an unexpected debugger endpoint.'
                }
                return $endpoint
            }
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "WebView2 did not publish a loopback debugging endpoint on port $Port."
}

function Wait-ReefVisionWebView2DebugClosure([int]$Port) {
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
            return
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "WebView2 debugging was still listening on port $Port after the acceptance desktop closed."
}

function Invoke-ReefVisionSpatialWebView2Acceptance {
    param(
        [Parameter(Mandatory = $true)][string]$NodePath,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$EvidenceRoot,
        [Parameter(Mandatory = $true)][string]$Api,
        [Parameter(Mandatory = $true)][int]$DebugPort,
        [Parameter(Mandatory = $true)][int]$DesktopProcessId
    )

    $endpoint = Wait-ReefVisionWebView2DebugEndpoint -Port $DebugPort -DesktopProcessId $DesktopProcessId
    $playwrightRoot = Join-Path $RepositoryRoot 'apps\web'
    $playwrightCli = Join-Path $playwrightRoot 'node_modules\@playwright\test\cli.js'
    $output = Join-Path $EvidenceRoot 'spatial-playwright'
    $log = Join-Path $EvidenceRoot 'spatial-playwright.log'
    $report = Join-Path $EvidenceRoot 'spatial-playwright.json'
    $variables = @{
        REEFVISION_GUIDED_TEST_API = $Api
        REEFVISION_SPATIAL_WEBVIEW2_ENDPOINT = $endpoint
        PLAYWRIGHT_JSON_OUTPUT_FILE = $report
    }
    $previous = @{}
    foreach ($name in $variables.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $variables[$name], 'Process')
    }
    Push-Location -LiteralPath $playwrightRoot
    try {
        # Only the test driver uses the absolute Node path. The existing MSI
        # and desktop/sidecar processes still inherit the restricted PATH.
        $specs = @(
            'spatial-guided-workflow-live.spec.ts',
            'project-spatial-comparison-live.spec.ts',
            'anatomical-branch-live.spec.ts',
            'spatial-condition-live.spec.ts',
            'reviewed-coral-growth-live.spec.ts',
            'dataset-export-layout-live.spec.ts',
            'ordinary-project-live.spec.ts'
        )
        & $NodePath $playwrightCli test @specs --workers=1 --retries=0 --reporter=list,json --output=$output *> $log
        if ($LASTEXITCODE -ne 0) {
            $tail = Get-Content -LiteralPath $log -Tail 25 | Out-String
            throw "Packaged WebView2 spatial workflow failed with exit code $LASTEXITCODE. $tail"
        }
    } finally {
        Pop-Location
        foreach ($name in $variables.Keys) {
            [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
        }
    }

    $stats = (Get-Content -LiteralPath $report -Raw | ConvertFrom-Json).stats
    if ($stats.expected -ne $specs.Count -or $stats.skipped -ne 0 -or $stats.unexpected -ne 0) {
        throw 'Every requested packaged desktop journey must execute successfully.'
    }
    $results = @(Get-ChildItem -LiteralPath $output -Recurse -File -Filter 'spatial-workflow.json')
    if ($results.Count -ne 1) { throw 'Expected one completed two-acquisition spatial replay report.' }
    $result = Get-Content -LiteralPath $results[0].FullName -Raw | ConvertFrom-Json
    if ($result.surface -ne 'tauri-webview2') { throw 'The spatial replay did not run in ReefVision WebView2.' }
    $result | Add-Member -NotePropertyName completed_journeys -NotePropertyValue $stats.expected
    return $result
}
