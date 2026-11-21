function Invoke-ReefVisionPackagedAutomationProof {
    param(
        [Parameter(Mandatory)][string]$ConsolePath,
        [Parameter(Mandatory)][string]$Scratch,
        [Parameter(Mandatory)][string]$ExpectedVersion
    )

    $automationProfile = Join-Path $Scratch 'profile'
    New-Item -ItemType Directory -Path $Scratch,$automationProfile | Out-Null

    function Invoke-AutomationProofCommand([string]$Name, [string[]]$Arguments = @()) {
        $stdout = Join-Path $Scratch "$Name.stdout.txt"
        $stderr = Join-Path $Scratch "$Name.stderr.txt"
        $launch = @{
            FilePath = $ConsolePath
            WorkingDirectory = $Scratch
            RedirectStandardOutput = $stdout
            RedirectStandardError = $stderr
            WindowStyle = 'Hidden'
            PassThru = $true
            Wait = $true
        }
        if ($Arguments.Count -gt 0) { $launch.ArgumentList = $Arguments }
        $process = Start-Process @launch
        [pscustomobject]@{
            code = $process.ExitCode
            stdout = [string](Get-Content -LiteralPath $stdout -Raw -Encoding UTF8)
            stderr = [string](Get-Content -LiteralPath $stderr -Raw -Encoding UTF8)
        }
    }

    $previousPath = $env:PATH
    try {
        $env:PATH = @(
            (Join-Path $env:SystemRoot 'System32'),
            $env:SystemRoot,
            (Join-Path $env:SystemRoot 'System32\Wbem')
        ) -join ';'
        foreach ($runtime in 'python.exe','python3.exe','node.exe','npm.cmd','rustc.exe','cargo.exe') {
            if (Get-Command $runtime -ErrorAction SilentlyContinue) {
                throw "Unexpected developer executable on the isolated automation PATH: $runtime"
            }
        }

        $noArgs = Invoke-AutomationProofCommand -Name 'no-args'
        $help = Invoke-AutomationProofCommand -Name 'help' -Arguments @('--help')
        if ($noArgs.code -ne 0 -or $help.code -ne 0 -or $noArgs.stderr -or $help.stderr -or
            $noArgs.stdout -notmatch '(?m)^usage: reefvision' -or $noArgs.stdout -cne $help.stdout) {
            throw 'The packaged automation console did not return matching usage on stdout.'
        }

        $rejected = Invoke-AutomationProofCommand -Name 'invalid' -Arguments @('--invalid-automation-proof-option')
        $errorReply = $rejected.stderr | ConvertFrom-Json
        if ($rejected.code -ne 2 -or $rejected.stdout -or $errorReply.status -ne 'error') {
            throw 'The packaged automation console did not preserve its structured failure on stderr.'
        }

        $name = 'Generated-automation-verification'
        $profileArgument = '"' + $automationProfile + '"'
        $create = Invoke-AutomationProofCommand -Name 'create' -Arguments @('--profile', $profileArgument, '--timeout', '90', 'project', 'create', $name)
        if ($create.code -ne 0 -or $create.stderr) { throw "Headless project creation failed: $($create.stderr)" }
        $created = $create.stdout | ConvertFrom-Json
        if ($created.status -ne 'ok' -or $created.application_version -ne $ExpectedVersion -or
            $created.result.name -cne $name -or $created.result.id -notmatch '^[a-f0-9-]{36}$') {
            throw 'The console did not create the expected generated project in the isolated profile.'
        }

        $open = Invoke-AutomationProofCommand -Name 'reopen' -Arguments @('--profile', $profileArgument, '--timeout', '90', 'project', 'open', $created.result.id)
        if ($open.code -ne 0 -or $open.stderr) { throw "Headless project reopen failed: $($open.stderr)" }
        $reopened = $open.stdout | ConvertFrom-Json
        if ($reopened.status -ne 'ok' -or $reopened.application_version -ne $ExpectedVersion -or
            $reopened.result.id -cne $created.result.id -or $reopened.result.name -cne $name) {
            throw 'An independent automation invocation did not reopen the same generated project.'
        }
        Write-Host 'Native Windows automation passed usage, structured failure, project creation and reopen without developer runtimes.'
    }
    finally {
        $env:PATH = $previousPath
    }
}
