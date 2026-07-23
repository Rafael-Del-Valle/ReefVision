param(
    [string[]]$ScriptPaths = @(
        "scripts/bootstrap.ps1",
        "scripts/build-desktop.ps1",
        "scripts/run-release-validation.ps1",
        "scripts/run-complete-release-validation.ps1",
        "scripts/validate-external-interchange.ps1",
        "scripts/verify-windows-msi.ps1",
        "scripts/all-phases-acceptance.ps1",
        "scripts/run-all-phases-acceptance.ps1"
    )
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
$Failures = [System.Collections.Generic.List[object]]::new()
$Results = [System.Collections.Generic.List[object]]::new()

foreach ($RelativePath in $ScriptPaths) {
    $Path = Join-Path $Root $RelativePath
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        [void]$Failures.Add([pscustomobject]@{
            path = $RelativePath
            message = "Script file is missing."
        })
        continue
    }
    $Tokens = $null
    $Errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $Path,
        [ref]$Tokens,
        [ref]$Errors
    )
    if (@($Errors).Count -gt 0) {
        foreach ($ParseError in $Errors) {
            [void]$Failures.Add([pscustomobject]@{
                path = $RelativePath
                line = $ParseError.Extent.StartLineNumber
                column = $ParseError.Extent.StartColumnNumber
                message = $ParseError.Message
            })
        }
        continue
    }
    [void]$Results.Add([pscustomobject]@{
        path = $RelativePath
        token_count = @($Tokens).Count
        parsed = $true
    })
}

$Report = [pscustomobject]@{
    schema = "reefvision-release-script-syntax-v4"
    passed = $Failures.Count -eq 0
    parsed = $Results
    failures = $Failures
}
$Report | ConvertTo-Json -Depth 6
if ($Failures.Count -gt 0) {
    exit 1
}
