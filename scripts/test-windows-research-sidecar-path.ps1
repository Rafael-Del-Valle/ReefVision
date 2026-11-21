param(
    [Parameter(Mandatory)][string]$NodePath,
    [Parameter(Mandatory)][string]$Scratch,
    [string]$DriverScript = (Join-Path $PSScriptRoot 'acceptance-windows-clean-install.ps1')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (Test-Path -LiteralPath $Scratch) { throw 'Expected a fresh sidecar identity scratch directory.' }
$InstallRoot = Join-Path ([IO.Path]::GetFullPath($Scratch)) 'Install root with spaces'
$witness = [IO.Path]::Combine($InstallRoot, 'backend', 'reefvision-api', 'reefvision-api.exe')
$null = New-Item -ItemType Directory -Path (Split-Path -Parent $witness)
Copy-Item -LiteralPath $NodePath -Destination $witness

# Evaluate the exact argument bound by the registered ResearchTools call. No
# installation, app launch or operating-system setting is exercised here.
$tokens = $null
$parseErrors = $null
$driver = [System.Management.Automation.Language.Parser]::ParseFile($DriverScript, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors) { throw 'The registered driver failed to parse.' }
$bindings = @($driver.FindAll({ param($ast)
    $ast -is [System.Management.Automation.Language.HashtableAst]
}, $true) | ForEach-Object KeyValuePairs | Where-Object {
    $_.Item1 -is [System.Management.Automation.Language.StringConstantExpressionAst] -and $_.Item1.Value -ceq 'BackendExecutable'
})
if ($bindings.Count -ne 1) { throw 'Expected exactly one ResearchTools backend executable argument.' }
$assignments = @($driver.FindAll({ param($ast)
    $ast -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $ast.Left -is [System.Management.Automation.Language.VariableExpressionAst] -and
    $ast.Left.VariablePath.UserPath -ceq 'installedSidecarPath'
}, $true))
if ($assignments.Count -gt 1) { throw 'The registered sidecar path was resolved more than once.' }
if ($assignments.Count -eq 1) { . ([ScriptBlock]::Create($assignments[0].Extent.Text)) }
$argument = & ([ScriptBlock]::Create($bindings[0].Item2.Extent.Text))
$process = Start-Process -FilePath $witness -ArgumentList @('-e', 'setTimeout(()=>{},10000)') -PassThru -WindowStyle Hidden
try {
    $active = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.Id)"
    $actual = $active.ExecutablePath
    if ($process.HasExited -or $actual -ine $witness -or $argument -ine $actual -or
        $argument.IndexOfAny([char[]]"`r`n") -ge 0 -or -not (Test-Path -LiteralPath $argument -PathType Leaf)) {
        throw "ResearchTools sidecar argument differs from the actual Windows executable path. Argument $($argument | ConvertTo-Json -Compress) observed $($actual | ConvertTo-Json -Compress)."
    }
} finally {
    if (-not $process.HasExited) { $process.Kill(); $null = $process.WaitForExit(8000) }
}
Write-Output 'The registered ResearchTools sidecar argument matches the real Windows executable path.'
