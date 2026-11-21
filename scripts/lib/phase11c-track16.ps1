# Pure branch and build-provenance gates for Phase 11C. No MSI or user-data access.
function Assert-ReefVisionPhase11CBranch {
    param(
        [Parameter(Mandatory = $true)][string]$ActualBranch,
        [switch]$TrackD16
    )

    $expected = if ($TrackD16) {
        'develop/reefvision-1.6'
    } else {
        'feat/scientist-ready-phase11-packaging-hardware-20261004'
    }
    if ($ActualBranch -cne $expected) {
        throw "Phase 11C must run on $expected (found: $ActualBranch)"
    }
    return $expected
}

function Assert-ReefVisionPhase11CBuildSource {
    param(
        [Parameter(Mandatory = $true)][string]$HarnessHead,
        [AllowEmptyString()][string]$InstallerSourceCommit,
        [switch]$TrackD16
    )

    # Preserve the historical Phase 11 mode. Track D 1.6 cannot borrow an MSI
    # built from an earlier commit and call it exact-head installed acceptance.
    if (-not $TrackD16) { return }
    if ($HarnessHead -cnotmatch '^[0-9a-f]{40}$' -or
        $InstallerSourceCommit -cnotmatch '^[0-9a-f]{40}$' -or
        $InstallerSourceCommit -cne $HarnessHead) {
        throw 'Track D 1.6 installed acceptance requires an MSI built from the exact checked-out commit.'
    }
}

function Assert-ReefVisionPhase11CEvidenceToken {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Token)

    if ($Token -cnotmatch '^[0-9a-f]{12}$') {
        throw 'Phase 11C evidence token must be exactly 12 lowercase hexadecimal characters.'
    }
    return $Token
}

# Reject another disposable root even if the report has the right token and
# last path component. This checks evidence only; the child still validates
# filesystem junctions, protected user paths and marker-gated cleanup.
function Assert-ReefVisionPhase11CReportDataRoot {
    param(
        [Parameter(Mandatory = $true)][string]$ExpectedAcceptanceRoot,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$ReportedAcceptanceRoot,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$ReportedDataRoot,
        [Parameter(Mandatory = $true)][string]$EvidenceToken
    )

    [void](Assert-ReefVisionPhase11CEvidenceToken -Token $EvidenceToken)
    if ([string]::IsNullOrWhiteSpace($ReportedAcceptanceRoot) -or
        [string]::IsNullOrWhiteSpace($ReportedDataRoot) -or
        -not [System.IO.Path]::IsPathRooted($ReportedAcceptanceRoot) -or
        -not [System.IO.Path]::IsPathRooted($ReportedDataRoot)) {
        throw 'Phase 11C acceptance report roots must be nonempty absolute paths.'
    }
    $expectedRoot = [System.IO.Path]::GetFullPath($ExpectedAcceptanceRoot).TrimEnd([char[]]@('\', '/'))
    $reportedRoot = [System.IO.Path]::GetFullPath($ReportedAcceptanceRoot).TrimEnd([char[]]@('\', '/'))
    $expectedData = [System.IO.Path]::GetFullPath(
        (Join-Path (Join-Path $expectedRoot "reefvision-clean-$EvidenceToken") 'data')
    ).TrimEnd([char[]]@('\', '/'))
    $reportedData = [System.IO.Path]::GetFullPath($ReportedDataRoot).TrimEnd([char[]]@('\', '/'))
    if ($reportedRoot -ine $expectedRoot -or $reportedData -ine $expectedData) {
        throw 'Phase 11C report does not match the invoking acceptance root and isolated data path.'
    }
    return $expectedData
}

# A child harness can run beside other isolated acceptance runs. Never
# attribute its evidence by directory modification time: another run may
# finish later, yielding a false PASS for this invocation.
function Assert-ReefVisionPhase11CUniqueNewReport {
    param(
        [AllowEmptyCollection()][string[]]$PriorDirectories = @(),
        [AllowEmptyCollection()][string[]]$CurrentDirectories = @()
    )

    $new = @(
        $CurrentDirectories |
            Where-Object { $_ -notin $PriorDirectories } |
            Select-Object -Unique
    )
    if ($new.Count -ne 1) {
        throw "Phase 11C expected exactly one new acceptance evidence directory; found $($new.Count). Cannot attribute concurrent evidence."
    }
    return [string]$new[0]
}
