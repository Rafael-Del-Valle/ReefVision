# Windows-native regression. Pure report selection: no installer or user data.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'lib\phase11c-track16.ps1')

function Assert-Rejected {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [Parameter(Mandatory = $true)][string]$MessagePattern
    )
    $rejected = $false
    try {
        & $Action | Out-Null
    }
    catch {
        if ($_.Exception.Message -notmatch $MessagePattern) { throw }
        $rejected = $true
    }
    if (-not $rejected) { throw "Expected Phase 11C fail-closed refusal was not raised." }
}

$validToken = 'a1b2c3d4e5f6'
$roundTripToken = Assert-ReefVisionPhase11CEvidenceToken -Token $validToken
if ($roundTripToken -cne $validToken) { throw 'Evidence token was not preserved.' }
foreach ($badToken in @('', 'A1B2C3D4E5F6', 'a1b2c3d4e5', 'a1b2c3d4e5f60',
    'a1b2c3d4e5fz', '../a1b2c3d4e5f6', ' a1b2c3d4e5f6')) {
    Assert-Rejected -MessagePattern '12 lowercase hexadecimal' -Action {
        Assert-ReefVisionPhase11CEvidenceToken -Token $badToken
    }
}

$old = 'C:\disposable\windows-clean-acceptance-old'
$own = 'C:\disposable\windows-clean-acceptance-own'
$other = 'C:\disposable\windows-clean-acceptance-other'

$onlyNew = Assert-ReefVisionPhase11CUniqueNewReport -PriorDirectories @($old) -CurrentDirectories @($old, $own)
if ($onlyNew -cne $own) { throw 'Did not identify exactly one new run.' }

$firstRun = Assert-ReefVisionPhase11CUniqueNewReport -PriorDirectories @() -CurrentDirectories @($own)
if ($firstRun -cne $own) { throw 'First clean acceptance run was not accepted.' }

$duplicateListing = Assert-ReefVisionPhase11CUniqueNewReport -PriorDirectories @($old) -CurrentDirectories @($old, $own, $own)
if ($duplicateListing -cne $own) { throw 'Duplicate listings must not appear as two distinct runs.' }

$caseOld = Assert-ReefVisionPhase11CUniqueNewReport -PriorDirectories @($old.ToUpperInvariant()) -CurrentDirectories @($old, $own)
if ($caseOld -cne $own) { throw 'Case variant of an existing Windows report was counted as new.' }

Assert-Rejected -MessagePattern 'exactly one new acceptance evidence directory; found 0' -Action {
    Assert-ReefVisionPhase11CUniqueNewReport -PriorDirectories @($old) -CurrentDirectories @($old)
}
Assert-Rejected -MessagePattern 'exactly one new acceptance evidence directory; found 0' -Action {
    Assert-ReefVisionPhase11CUniqueNewReport -PriorDirectories @() -CurrentDirectories @()
}
Assert-Rejected -MessagePattern 'exactly one new acceptance evidence directory; found 2' -Action {
    Assert-ReefVisionPhase11CUniqueNewReport -PriorDirectories @($old) -CurrentDirectories @($old, $own, $other)
}
Assert-Rejected -MessagePattern 'exactly one new acceptance evidence directory; found 2' -Action {
    Assert-ReefVisionPhase11CUniqueNewReport -PriorDirectories @() -CurrentDirectories @($own, $other)
}

[void](Assert-ReefVisionPhase11CBranch -ActualBranch 'develop/reefvision-1.6' -TrackD16)
Assert-Rejected -MessagePattern 'must run on develop/reefvision-1.6' -Action {
    Assert-ReefVisionPhase11CBranch -ActualBranch 'develop/reefvision-1.7' -TrackD16
}
$head = 'a' * 40
[void](Assert-ReefVisionPhase11CBuildSource -HarnessHead $head -InstallerSourceCommit $head -TrackD16)
Assert-Rejected -MessagePattern 'exact checked-out commit' -Action {
    Assert-ReefVisionPhase11CBuildSource -HarnessHead $head -InstallerSourceCommit ('b' * 40) -TrackD16
}

Write-Host 'Phase 11C invocation-bound evidence, legacy selection, and exact-head gates passed.'
