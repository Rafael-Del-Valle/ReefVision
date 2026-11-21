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
