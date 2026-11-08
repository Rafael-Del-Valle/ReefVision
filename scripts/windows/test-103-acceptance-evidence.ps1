# Self-contained regression checks for the read-only Windows acceptance collector.
# Run with: pwsh -NoProfile -File scripts/windows/test-103-acceptance-evidence.ps1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$collector = Join-Path $PSScriptRoot 'collect-103-acceptance-evidence.ps1'
if (-not (Test-Path -LiteralPath $collector -PathType Leaf)) {
    throw 'Acceptance evidence collector is missing.'
}
$fixture = Join-Path ([System.IO.Path]::GetTempPath()) ("reefvision-103-evidence-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixture -ErrorAction Stop | Out-Null
try {
    $sample = Join-Path $fixture 'camera test artifact.msi'
    $bytes = [byte[]](0, 1, 2, 127, 128, 255)
    [System.IO.File]::WriteAllBytes($sample, $bytes)
    $sha = '0123456789abcdef0123456789abcdef01234567'
    $raw = & $collector -CandidateSha $sha.ToUpperInvariant() -MsiPath $sample
    $record = ($raw | Out-String | ConvertFrom-Json)
    if ($record.schema -ne 'reefvision.windows-acceptance-evidence.v1') { throw 'Unexpected evidence schema.' }
    if ($record.candidateSha -cne $sha) { throw 'Candidate SHA was not normalized.' }
    $expectedHash = (Get-FileHash -LiteralPath $sample -Algorithm SHA256).Hash.ToLowerInvariant()
    $msi = @($record.artifacts | Where-Object { $_.kind -eq 'msi' })
    $cab = @($record.artifacts | Where-Object { $_.kind -eq 'cab' })
    if ($msi.Count -ne 1 -or $msi[0].status -ne 'hashed' -or $msi[0].sha256 -cne $expectedHash -or $msi[0].bytes -ne $bytes.Length) {
        throw 'MSI artifact evidence does not match the input bytes.'
    }
    if ($cab.Count -ne 1 -or $cab[0].status -ne 'not_provided') { throw 'Missing CAB was not labeled as unprovided.' }
    if (-not @($record.limitations | Where-Object { $_ -match 'does not prove installation' }).Count) {
        throw 'Evidence must explicitly disclaim installation acceptance.'
    }
    # Both installer artifact kinds must be independently hashed; neither implies install success.
    $cabSample = Join-Path $fixture 'camera cabinet.cab'
    $cabBytes = [byte[]](255, 0, 17, 34, 51)
    [System.IO.File]::WriteAllBytes($cabSample, $cabBytes)
    $withCab = (& $collector -CandidateSha $sha -MsiPath $sample -CabPath $cabSample | Out-String | ConvertFrom-Json)
    $cabEvidence = @($withCab.artifacts | Where-Object { $_.kind -eq 'cab' })
    $expectedCabHash = (Get-FileHash -LiteralPath $cabSample -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($cabEvidence.Count -ne 1 -or $cabEvidence[0].status -ne 'hashed' -or
        $cabEvidence[0].sha256 -cne $expectedCabHash -or $cabEvidence[0].bytes -ne $cabBytes.Length) {
        throw 'CAB artifact evidence does not match the input bytes.'
    }
    # Missing artifacts must remain explicitly unverified, not silently omitted.
    $withoutArtifacts = (& $collector -CandidateSha $sha | Out-String | ConvertFrom-Json)
    $absent = @($withoutArtifacts.artifacts)
    if ($absent.Count -ne 2 -or @($absent | Where-Object { $_.status -eq 'not_provided' }).Count -ne 2) {
        throw 'Unprovided MSI and CAB must both be reported as not_provided.'
    }
    # A changed binary must produce different evidence; this protects against
    # accidentally reusing a stale hash or hashing the wrong artifact path.
    $originalHash = $msi[0].sha256
    [System.IO.File]::WriteAllBytes($sample, [byte[]](0, 1, 2, 127, 128, 254))
    $changed = (& $collector -CandidateSha $sha -MsiPath $sample | Out-String | ConvertFrom-Json)
    $changedMsi = @($changed.artifacts | Where-Object { $_.kind -eq 'msi' })
    $changedHash = (Get-FileHash -LiteralPath $sample -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($changedMsi.Count -ne 1 -or $changedMsi[0].sha256 -cne $changedHash -or $changedMsi[0].sha256 -ceq $originalHash) {
        throw 'Modified MSI bytes did not invalidate the previous evidence hash.'
    }
    $directoryRejected = $false
    try { $null = & $collector -CandidateSha $sha -CabPath $fixture 2>&1 } catch { $directoryRejected = $true }
    if (-not $directoryRejected) { throw 'Directory was incorrectly accepted as a CAB artifact.' }
    $invalidRejected = $false
    try { $null = & $collector -CandidateSha 'not-a-commit' 2>&1 } catch { $invalidRejected = $true }
    if (-not $invalidRejected) { throw 'Invalid candidate SHA was accepted.' }
    $missingRejected = $false
    try { $null = & $collector -CandidateSha $sha -MsiPath (Join-Path $fixture 'missing.msi') 2>&1 } catch { $missingRejected = $true }
    if (-not $missingRejected) { throw 'Missing MSI was incorrectly treated as validated.' }
    Write-Output 'PASS: SHA validation, MSI/CAB hashes, missing artifacts, mutation-sensitive hashes, directory rejection, and evidence limitations.'
} finally {
    Remove-Item -LiteralPath $fixture -Recurse -Force -ErrorAction SilentlyContinue
}
