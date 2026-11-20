# Windows-only child-process regression for start-reefvision CLI configuration.
# Uses disposable LOCALAPPDATA; never launches the desktop or changes user data.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$previousLocalAppData = $env:LOCALAPPDATA
$root = Join-Path $env:TEMP ('reefvision-start-config-' + [guid]::NewGuid().ToString('N'))
$configDir = Join-Path $root 'local\ReefVision\config'
$configPath = Join-Path $configDir 'commands.json'
$startScript = Join-Path $PSScriptRoot 'start-reefvision.ps1'
$repoPath = Split-Path -Parent $PSScriptRoot
$passed = 0

function Invoke-StartCommand {
    param([string]$ExtraOptions, [switch]$NoConfigure)
    $stdoutPath = Join-Path $root ('stdout-' + [guid]::NewGuid().ToString('N') + '.txt')
    $stderrPath = Join-Path $root ('stderr-' + [guid]::NewGuid().ToString('N') + '.txt')
    $args = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $startScript + '"'
    if (-not $NoConfigure) {
        $args += ' --configure-repo "' + $repoPath + '"'
    }
    $args += ' ' + $ExtraOptions
    $child = Start-Process -FilePath 'powershell.exe' -ArgumentList $args -PassThru -Wait `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    return [pscustomobject]@{
        ExitCode = $child.ExitCode
        Output = (Get-Content -LiteralPath $stdoutPath -Raw) +
            (Get-Content -LiteralPath $stderrPath -Raw)
    }
}

try {
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
    $env:LOCALAPPDATA = Join-Path $root 'local'
    Set-Content -LiteralPath $configPath -Encoding UTF8 -Value '{"repo_path":"original-preserved","installed_app_path":"sentinel"}'
    $originalHash = (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash

    foreach ($case in @(
        @{ Options = '--restart'; Expected = '--configure-repo cannot be combined' },
        @{ Options = '--safe-mode'; Expected = '--configure-repo cannot be combined' },
        @{ Options = '--logs'; Expected = '--configure-repo cannot be combined' },
        @{ Options = '--diagnostics'; Expected = '--configure-repo cannot be combined' },
        @{ Options = '--no-wait'; Expected = '--configure-repo cannot be combined' },
        @{ Options = '--status --dev'; Expected = '--status cannot be combined with a development mode' },
        @{ Options = '--dev --web-dev'; Expected = 'Choose only one development mode' },
        @{ Options = '--api-only --dev'; Expected = 'Choose only one development mode' }
    )) {
        $result = Invoke-StartCommand -ExtraOptions $case.Options
        if ($result.ExitCode -eq 0 -or -not $result.Output.Contains($case.Expected)) {
            throw "Unexpected start-command rejection for $($case.Options): exit=$($result.ExitCode); $($result.Output)"
        }
        if ((Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash -ne $originalHash) {
            throw "Rejected start-command invocation changed persistent settings: $($case.Options)"
        }
        $passed++
    }

    # No repository-configuration option: these combinations previously
    # reported success while ignoring restart, a read-only request, or
    # the installed-launcher switches. Check the same disposable config bytes
    # and require failure before any process or API action can be taken.
    foreach ($case in @(
        @{ Options = '--status --restart'; Expected = 'Choose only one start-reefvision action' },
        @{ Options = '--logs --diagnostics'; Expected = 'Choose only one start-reefvision action' },
        @{ Options = '--status --logs'; Expected = 'Choose only one start-reefvision action' },
        @{ Options = '--status --dev'; Expected = 'Choose only one start-reefvision action' },
        @{ Options = '--api-only --restart'; Expected = 'Choose only one start-reefvision action' },
        @{ Options = '--web-dev --no-wait'; Expected = 'apply only to the installed desktop launcher' },
        @{ Options = '--api-only --safe-mode'; Expected = 'apply only to the installed desktop launcher' },
        @{ Options = '--status --no-wait'; Expected = 'cannot be combined with status' },
        @{ Options = '--diagnostics --safe-mode'; Expected = 'cannot be combined with status' }
    )) {
        $result = Invoke-StartCommand -ExtraOptions $case.Options -NoConfigure
        if ($result.ExitCode -eq 0 -or -not $result.Output.Contains($case.Expected)) {
            throw "Unexpected mixed start action for $($case.Options): exit=$($result.ExitCode); $($result.Output)"
        }
        if ((Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash -ne $originalHash) {
            throw "Mixed start action modified saved configuration: $($case.Options)"
        }
        $passed++
    }

    # --help remains read-only even when a configure argument is present.
    $help = Invoke-StartCommand -ExtraOptions '--help'
    if ($help.ExitCode -ne 0 -or -not $help.Output.Contains('Usage:')) {
        throw 'The help command no longer succeeds.'
    }
    if ((Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash -ne $originalHash) {
        throw 'Help command unexpectedly changed saved configuration.'
    }
    $passed++

    # Pure configuration remains a supported explicit action.
    $valid = Invoke-StartCommand -ExtraOptions ''
    if ($valid.ExitCode -ne 0) {
        throw "Standalone repository configuration failed: $($valid.Output)"
    }
    $saved = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    if ($saved.repo_path -ine (Resolve-Path -LiteralPath $repoPath).Path -or
        $saved.installed_app_path -ne 'sentinel') {
        throw 'Valid configuration failed to retain repository path and installed-app identity.'
    }
    $passed++
    Write-Host "ReefVision start command configuration: $passed passed" -ForegroundColor Green
}
finally {
    $env:LOCALAPPDATA = $previousLocalAppData
    if (Test-Path -LiteralPath $root) {
        Remove-Item -LiteralPath $root -Recurse -Force
    }
}
