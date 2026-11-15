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
    # Windows installer paths are case-insensitive and may contain spaces. The
    # collector must hash uppercase extensions without modifying either file.
    $uppercaseMsi = Join-Path $fixture 'Camera Build.MSI'
    $uppercaseCab = Join-Path $fixture 'Camera Payload.CAB'
    [System.IO.File]::WriteAllBytes($uppercaseMsi, $bytes)
    [System.IO.File]::WriteAllBytes($uppercaseCab, $cabBytes)
    $upperEvidence = (& $collector -CandidateSha $sha -MsiPath $uppercaseMsi -CabPath $uppercaseCab | Out-String | ConvertFrom-Json)
    foreach ($artifact in @($upperEvidence.artifacts)) {
        $expectedFile = if ($artifact.kind -eq 'msi') { $uppercaseMsi } else { $uppercaseCab }
        $expectedBytes = if ($artifact.kind -eq 'msi') { $bytes } else { $cabBytes }
        if ($artifact.status -ne 'hashed' -or
            $artifact.sha256 -cne (Get-FileHash -LiteralPath $expectedFile -Algorithm SHA256).Hash.ToLowerInvariant() -or
            $artifact.bytes -ne $expectedBytes.Length -or
            -not ([Convert]::ToBase64String([System.IO.File]::ReadAllBytes($expectedFile)) -ceq [Convert]::ToBase64String($expectedBytes))) {
            throw "Uppercase extension, spaced path, or read-only artifact contract failed for $($artifact.kind)."
        }
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
    # An in-progress installer must never be reported as a stable artifact.
    # Holding a write-capable handle simulates a packaging process that has
    # not finished. The collector's read-only handle must fail closed on
    # Windows rather than hashing concurrently mutable bytes.
    $writer = [System.IO.File]::Open(
        $sample,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::ReadWrite
    )
    try {
        $mutableRejected = $false
        try { $null = & $collector -CandidateSha $sha -MsiPath $sample 2>&1 }
        catch { $mutableRejected = $true }
        if (-not $mutableRejected) {
            throw 'A mutable, writer-open MSI was incorrectly accepted as stable evidence.'
        }
    } finally {
        $writer.Dispose()
    }
    $afterWriter = (& $collector -CandidateSha $sha -MsiPath $sample | Out-String | ConvertFrom-Json)
    if (@($afterWriter.artifacts | Where-Object { $_.kind -eq 'msi' -and $_.status -eq 'hashed' }).Count -ne 1) {
        throw 'Completed MSI could not be read after its writer closed.'
    }
    # Where Windows allows disposable symlink creation, reject both file
    # aliases and linked parent directories; never inspect linked targets.
    $fileLink = Join-Path $fixture 'linked installer.msi'
    $linkCreated = $false
    try {
        $null = New-Item -ItemType SymbolicLink -Path $fileLink -Target $sample -ErrorAction Stop
        $linkCreated = $true
    } catch {
        Write-Output "SKIP: Windows symlink privilege unavailable: $($_.Exception.GetType().Name)"
    }
    if ($linkCreated) {
        $linkedRejected = $false
        try { $null = & $collector -CandidateSha $sha -MsiPath $fileLink 2>&1 }
        catch { $linkedRejected = $true }
        if (-not $linkedRejected) { throw 'Symlinked MSI incorrectly accepted as source artifact.' }
    }
    $folderLink = Join-Path $fixture 'linked folder'
    $folderLinkCreated = $false
    try {
        $null = New-Item -ItemType SymbolicLink -Path $folderLink -Target $fixture -ErrorAction Stop
        $folderLinkCreated = $true
    } catch {
        Write-Output "SKIP: Windows directory symlink privilege unavailable: $($_.Exception.GetType().Name)"
    }
    if ($folderLinkCreated) {
        $linkedParentRejected = $false
        try { $null = & $collector -CandidateSha $sha -MsiPath (Join-Path $folderLink 'camera test artifact.msi') 2>&1 }
        catch { $linkedParentRejected = $true }
        if (-not $linkedParentRejected) {
            throw 'MSI through a symlinked parent directory incorrectly passed artifact acceptance.'
        }
    }
    # An arbitrary binary must not be mislabeled as a verified MSI/CAB.
    $wrongExtension = Join-Path $fixture 'not-an-installer.bin'
    [System.IO.File]::WriteAllBytes($wrongExtension, [byte[]](1, 2, 3))
    foreach ($artifactKind in @('MsiPath', 'CabPath')) {
        $mislabeledRejected = $false
        try {
            $params = @{ CandidateSha = $sha; $artifactKind = $wrongExtension }
            $null = & $collector @params 2>&1
        } catch { $mislabeledRejected = $true }
        if (-not $mislabeledRejected) { throw "Arbitrary binary was incorrectly accepted as $artifactKind evidence." }
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
    # An untrusted image-analysis workspace may prepend a fake executable to
    # PATH. The acceptance collector is read-only and must never resolve or
    # execute that program simply to inventory an optional GPU.
    $oldPath = $env:PATH
    $untrustedDirectory = Join-Path $fixture 'untrusted PATH tools'
    New-Item -ItemType Directory -Path $untrustedDirectory -ErrorAction Stop | Out-Null
    [System.IO.File]::WriteAllBytes(
        (Join-Path $untrustedDirectory 'nvidia-smi.exe'), [byte[]](77, 90, 0, 0)
    )
    $env:PATH = $untrustedDirectory + [System.IO.Path]::PathSeparator + $oldPath
    function Get-Command { throw 'Untrusted PATH lookup attempted by the evidence collector.' }
    try {
        $trusted = (& $collector -CandidateSha $sha | Out-String | ConvertFrom-Json)
        if ($trusted.candidateSha -cne $sha -or
            -not @($trusted.limitations | Where-Object { $_ -match 'trusted Windows driver paths' }).Count) {
            throw 'GPU inventory did not preserve commit identity and trusted-path limitations.'
        }
    } finally {
        Remove-Item Function:\Get-Command -ErrorAction SilentlyContinue
        $env:PATH = $oldPath
    }
    Write-Output 'PASS: SHA validation, stable MSI/CAB handle hashes, mutable-writer rejection, linked-path checks where supported, safe GPU discovery, and evidence limitations.'
} finally {
    Remove-Item -LiteralPath $fixture -Recurse -Force -ErrorAction SilentlyContinue
}
