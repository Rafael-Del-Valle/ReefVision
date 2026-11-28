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
    $bytes = [byte[]](208, 207, 17, 224, 161, 177, 26, 225, 0, 1, 2, 127, 128, 255)
    [System.IO.File]::WriteAllBytes($sample, $bytes)
    $sha = '0123456789abcdef0123456789abcdef01234567'
    $raw = & $collector -CandidateSha $sha.ToUpperInvariant() -MsiPath $sample
    $record = ($raw | Out-String | ConvertFrom-Json)
    if ($record.schema -ne 'reefvision.windows-acceptance-evidence.v1') { throw 'Unexpected evidence schema.' }
    if ($record.candidateSha -cne $sha) { throw 'Candidate SHA was not normalized.' }
    # The standalone evidence collector must use the SAME canonical, read-only
    # WebView2 registry inventory as the actual installed-app acceptance harness.
    # The former ad hoc collector used a different product GUID and silently
    # missed real Evergreen registrations. On CI, compare observed results
    # rather than requiring a runtime to be installed on every Windows image.
    $helper = Join-Path (Split-Path -Parent $PSScriptRoot) 'lib/windows-clean-acceptance.ps1'
    . $helper
    $expectedRuntime = Get-ReefVisionWebView2RuntimeInfo
    $reportedRegistrations = @($record.webview2 | Where-Object { $null -ne $_ })
    $expectedRegistrations = @($expectedRuntime.registrations | Where-Object { $null -ne $_ })
    if ($record.webview2Inspection.complete -ne $expectedRuntime.inspection_complete -or
        ((@($record.webview2Inspection.unreadableScopes) -join ',') -cne (@($expectedRuntime.unreadable_scopes) -join ',')) -or
        ((@($record.webview2Inspection.invalidScopes) -join ',') -cne (@($expectedRuntime.invalid_scopes) -join ','))) {
        throw 'Evidence collector lost registry access failures or misreported inspection completeness.'
    }
    if ($reportedRegistrations.Count -ne $expectedRegistrations.Count) {
        throw 'Evidence collector and installed-app harness disagree about WebView2 registrations.'
    }
    $webviewId = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    $pathsByScope = @{
        'machine-32' = "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$webviewId"
        'machine-64' = "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$webviewId"
        'user' = "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$webviewId"
    }
    foreach ($expectedEntry in $expectedRegistrations) {
        $matches = @($reportedRegistrations | Where-Object {
            $_.scope -ceq [string]$expectedEntry.scope -and
            $_.version -ceq [string]$expectedEntry.version
        })
        if ($matches.Count -ne 1 -or
            -not $pathsByScope.ContainsKey([string]$expectedEntry.scope) -or
            $matches[0].registryPath -cne $pathsByScope[[string]$expectedEntry.scope]) {
            throw 'WebView2 runtime evidence lost its canonical registry location, view, or version.'
        }
    }
    if (-not @($record.limitations | Where-Object { $_ -match 'Malformed WebView2 registry versions' }).Count) {
        throw 'Malformed WebView2 pv values must be disclosed as incomplete registry evidence.'
    }
    if (-not @($record.limitations | Where-Object { $_ -match 'incomplete WebView2 registry inspection' }).Count) {
        throw 'Incomplete WebView2 inventory must not be mistaken for runtime absence.'
    }
    if (-not @($record.limitations | Where-Object { $_ -match 'WebView2 registry detection is advisory' }).Count) {
        throw 'Registry detection must not imply installed GUI acceptance.'
    }
    $expectedHash = (Get-FileHash -LiteralPath $sample -Algorithm SHA256).Hash.ToLowerInvariant()
    $msi = @($record.artifacts | Where-Object { $_.kind -eq 'msi' })
    $cab = @($record.artifacts | Where-Object { $_.kind -eq 'cab' })
    if ($msi.Count -ne 1 -or $msi[0].status -ne 'hashed' -or $msi[0].headerCheck -ne 'magic_only' -or $msi[0].sha256 -cne $expectedHash -or $msi[0].bytes -ne $bytes.Length) {
        throw 'MSI artifact evidence does not match the input bytes.'
    }
    if ($cab.Count -ne 1 -or $cab[0].status -ne 'not_provided') { throw 'Missing CAB was not labeled as unprovided.' }
    if (-not @($record.limitations | Where-Object { $_ -match 'does not prove installation' }).Count) {
        throw 'Evidence must explicitly disclaim installation acceptance.'
    }
    if ($null -ne $record.provenance.manifestSha256 -or $null -ne $record.provenance.manifestBytes) {
        throw 'Unprovided build manifest must not have a fingerprint or byte count.'
    }
    # Both installer artifact kinds must be independently hashed; neither implies install success.
    $cabSample = Join-Path $fixture 'camera cabinet.cab'
    $cabBytes = [byte[]](77, 83, 67, 70, 255, 0, 17, 34, 51)
    [System.IO.File]::WriteAllBytes($cabSample, $cabBytes)
    $withCab = (& $collector -CandidateSha $sha -MsiPath $sample -CabPath $cabSample | Out-String | ConvertFrom-Json)
    $cabEvidence = @($withCab.artifacts | Where-Object { $_.kind -eq 'cab' })
    $expectedCabHash = (Get-FileHash -LiteralPath $cabSample -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($cabEvidence.Count -ne 1 -or $cabEvidence[0].status -ne 'hashed' -or $cabEvidence[0].headerCheck -ne 'magic_only' -or
        $cabEvidence[0].sha256 -cne $expectedCabHash -or $cabEvidence[0].bytes -ne $cabBytes.Length) {
        throw 'CAB artifact evidence does not match the input bytes.'
    }
    # A hash-only inventory cannot establish installer source identity. Match
    # the optional candidate build manifest and explicitly enumerate CABs that
    # were declared but not provided to this read-only collector.
    $candidateMsi = Join-Path $fixture 'ReefVision_1.0.3_x64_en-US.msi'
    $candidateCab = Join-Path $fixture 'rv1.cab'
    $manifestPath = Join-Path $fixture 'build-provenance.json'
    [System.IO.File]::WriteAllBytes($candidateMsi, $bytes)
    [System.IO.File]::WriteAllBytes($candidateCab, $cabBytes)
    $candidateManifest = [ordered]@{
        version = '1.0.3'
        source_commit = $sha
        source_tree_clean = $true
        msi_verified = $true
        files = @(
            [ordered]@{ name = 'ReefVision_1.0.3_x64_en-US.msi'; sha256 = $expectedHash }
            [ordered]@{ name = 'rv1.cab'; sha256 = $expectedCabHash }
        )
    }
    # A real 1.0.3 split-cabinet MSI has five or six CABs. A single-CAB
    # argument could never produce matched_complete on the actual payload.
    $candidateCabPaths = @($candidateCab)
    foreach ($cabNumber in 2..5) {
        $extraCabPath = Join-Path $fixture "rv$cabNumber.cab"
        $extraBytes = [byte[]](77, 83, 67, 70, 255, 0, 17, [byte]$cabNumber, 51)
        [System.IO.File]::WriteAllBytes($extraCabPath, $extraBytes)
        $candidateCabPaths += $extraCabPath
        $candidateManifest.files += [ordered]@{
            name = "rv$cabNumber.cab"
            sha256 = (Get-FileHash -LiteralPath $extraCabPath -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    $candidateManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $matched = (& $collector -CandidateSha $sha -MsiPath $candidateMsi -CabPath $candidateCabPaths -ProvenancePath $manifestPath |
        Out-String | ConvertFrom-Json)
    if ($matched.provenance.status -cne 'matched_complete' -or
        $matched.provenance.verifiedArtifacts -ne 6 -or
        $matched.provenance.declaredArtifacts -ne 6 -or
        @($matched.artifacts | Where-Object { $_.kind -eq 'cab' -and $_.status -eq 'hashed' }).Count -ne 5 -or
        @($matched.provenance.unverifiedArtifactNames | Where-Object { $null -ne $_ }).Count -ne 0) {
        throw 'Five-CAB manifest did not produce complete, separately hashed installer evidence.'
    }
    $expectedManifestHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($matched.provenance.manifestSha256 -cne $expectedManifestHash -or
        $matched.provenance.manifestBytes -ne (Get-Item -LiteralPath $manifestPath).Length) {
        throw 'Complete evidence lost the exact manifest fingerprint or byte count.'
    }
    # The same artifact set can match a byte-different manifest. Preserve the
    # distinction even if the only change is insignificant JSON whitespace.
    Add-Content -LiteralPath $manifestPath -Value ' ' -Encoding UTF8
    $reformatted = (& $collector -CandidateSha $sha -MsiPath $candidateMsi -CabPath $candidateCabPaths -ProvenancePath $manifestPath |
        Out-String | ConvertFrom-Json)
    if ($reformatted.provenance.status -cne 'matched_complete' -or
        $reformatted.provenance.manifestSha256 -ceq $expectedManifestHash -or
        $reformatted.provenance.manifestSha256 -cne (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -or
        $reformatted.provenance.manifestBytes -ne (Get-Item -LiteralPath $manifestPath).Length) {
        throw 'Changed manifest bytes did not produce distinct complete provenance evidence.'
    }
    $candidateManifest.files += [ordered]@{ name = 'rv6.cab'; sha256 = ('a' * 64) }
    $candidateManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $partial = (& $collector -CandidateSha $sha -MsiPath $candidateMsi -CabPath $candidateCabPaths -ProvenancePath $manifestPath |
        Out-String | ConvertFrom-Json)
    if ($partial.provenance.status -cne 'matched_subset' -or
        $partial.provenance.verifiedArtifacts -ne 6 -or
        $partial.provenance.declaredArtifacts -ne 7 -or
        $partial.provenance.manifestSha256 -cne (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -or
        $partial.provenance.manifestBytes -ne (Get-Item -LiteralPath $manifestPath).Length -or
        @($partial.provenance.unverifiedArtifactNames).Count -ne 1 -or
        $partial.provenance.unverifiedArtifactNames[0] -cne 'rv6.cab') {
        throw 'A missing sixth CAB was incorrectly accepted as complete installer provenance.'
    }
    # Both five- and six-CAB layouts must support complete validation.
    $sixthCab = Join-Path $fixture 'rv6.cab'
    [System.IO.File]::WriteAllBytes($sixthCab, [byte[]](77, 83, 67, 70, 255, 0, 17, 6, 51))
    $candidateManifest.files[-1].sha256 = (Get-FileHash -LiteralPath $sixthCab -Algorithm SHA256).Hash.ToLowerInvariant()
    $candidateManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $sixCabPaths = @($candidateCabPaths) + @($sixthCab)
    $completeSix = (& $collector -CandidateSha $sha -MsiPath $candidateMsi -CabPath $sixCabPaths -ProvenancePath $manifestPath |
        Out-String | ConvertFrom-Json)
    if ($completeSix.provenance.status -cne 'matched_complete' -or
        $completeSix.provenance.verifiedArtifacts -ne 7 -or
        $completeSix.provenance.declaredArtifacts -ne 7 -or
        @($completeSix.artifacts | Where-Object { $_.kind -eq 'cab' -and $_.status -eq 'hashed' }).Count -ne 6) {
        throw 'Six-CAB manifest did not produce complete installer evidence.'
    }
    # A singleton root array must not be unwrapped into valid provenance;
    # an oversized manifest must fail before parsing even if its JSON is valid.
    $validManifestJson = $candidateManifest | ConvertTo-Json -Depth 5
    foreach ($invalidManifest in @(
        @{ json = ('[' + $validManifestJson + ']'); error = 'Build provenance must be a JSON object' }
        @{ json = ($validManifestJson + (' ' * 1MB)); error = 'Build provenance manifest exceeds the 1 MiB size limit' }
    )) {
        Set-Content -LiteralPath $manifestPath -Value $invalidManifest.json -Encoding UTF8
        $beforeRejectedHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash
        $invalidManifestRejected = $false
        try {
            $null = & $collector -CandidateSha $sha -MsiPath $candidateMsi -CabPath $sixCabPaths -ProvenancePath $manifestPath
        } catch {
            if ($_.Exception.Message -notmatch [regex]::Escape($invalidManifest.error)) { throw }
            $invalidManifestRejected = $true
        }
        if (-not $invalidManifestRejected -or
            (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash -cne $beforeRejectedHash) {
            throw 'Invalid manifest was accepted or its bytes were changed.'
        }
    }
    Set-Content -LiteralPath $manifestPath -Value $validManifestJson -Encoding UTF8
    $restoredManifest = (& $collector -CandidateSha $sha -MsiPath $candidateMsi -CabPath $sixCabPaths -ProvenancePath $manifestPath |
        Out-String | ConvertFrom-Json)
    if ($restoredManifest.provenance.status -cne 'matched_complete' -or $restoredManifest.provenance.verifiedArtifacts -ne 7) {
        throw 'A valid object manifest failed after invalid root and size checks.'
    }
    # Nested singleton arrays expose their object's properties through
    # PowerShell member-access enumeration. Reject the shape even when all
    # six CAB names and hashes otherwise match the supplied payloads.
    $originalEntry = $candidateManifest.files[0]
    $candidateManifest.files[0] = ,$originalEntry
    $candidateManifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $nestedHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash
    $nestedRejected = $false
    try {
        $null = & $collector -CandidateSha $sha -MsiPath $candidateMsi -CabPath $sixCabPaths -ProvenancePath $manifestPath
    } catch {
        if ($_.Exception.Message -notmatch 'entries must be individual JSON objects') { throw }
        $nestedRejected = $true
    } finally {
        $candidateManifest.files[0] = $originalEntry
    }
    if (-not $nestedRejected -or
        (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash -cne $nestedHash) {
        throw 'Nested artifact record was accepted or its manifest bytes changed.'
    }
    $candidateManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $flatManifest = (& $collector -CandidateSha $sha -MsiPath $candidateMsi -CabPath $sixCabPaths -ProvenancePath $manifestPath |
        Out-String | ConvertFrom-Json)
    if ($flatManifest.provenance.status -cne 'matched_complete' -or $flatManifest.provenance.verifiedArtifacts -ne 7) {
        throw 'Valid flat manifest failed after nested entry rejection.'
    }
    # JSON array values must not exploit PowerShell's array comparison or
    # string conversion semantics to masquerade as scalar build identity.
    foreach ($field in @('version', 'source_commit')) {
        $originalValue = $candidateManifest[$field]
        $candidateManifest[$field] = @($originalValue)
        $candidateManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
        $arrayRejected = $false
        try { $null = & $collector -CandidateSha $sha -MsiPath $candidateMsi -CabPath $sixCabPaths -ProvenancePath $manifestPath 2>&1 }
        catch { $arrayRejected = $true }
        $candidateManifest[$field] = $originalValue
        if (-not $arrayRejected) { throw "Array-valued provenance $field was accepted." }
    }
    # Even the unprovided sixth cabinet must have a well-typed, exact hash;
    # a subset check must not accept malformed declarations it cannot verify.
    foreach ($field in @('name', 'sha256')) {
        $originalValue = $candidateManifest.files[-1][$field]
        $candidateManifest.files[-1][$field] = @($originalValue)
        $candidateManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
        $arrayRejected = $false
        try { $null = & $collector -CandidateSha $sha -MsiPath $candidateMsi -CabPath $candidateCabPaths -ProvenancePath $manifestPath 2>&1 }
        catch { $arrayRejected = $true }
        $candidateManifest.files[-1][$field] = $originalValue
        if (-not $arrayRejected) { throw "Array-valued CAB provenance $field was accepted." }
    }
    $originalHashValue = $candidateManifest.files[-1].sha256
    $candidateManifest.files[-1].sha256 = $originalHashValue + "`n"
    $candidateManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $newlineHashRejected = $false
    try { $null = & $collector -CandidateSha $sha -MsiPath $candidateMsi -CabPath $candidateCabPaths -ProvenancePath $manifestPath 2>&1 }
    catch { $newlineHashRejected = $true }
    $candidateManifest.files[-1].sha256 = $originalHashValue
    if (-not $newlineHashRejected) { throw 'A SHA-256 with trailing newline was accepted.' }
    $candidateManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $newlineShaRejected = $false
    try { $null = & $collector -CandidateSha ($sha + "`n") 2>&1 }
    catch { $newlineShaRejected = $true }
    if (-not $newlineShaRejected) { throw 'A candidate SHA with trailing newline was accepted.' }

    # A forged/partial manifest must never appear "matched_complete" merely
    # because the caller lists only the MSI. The CAB set must be complete in
    # the declaration, even when only an MSI is supplied for a subset check.
    $validManifestFiles = @($candidateManifest.files)
    $candidateManifest.files = @($validManifestFiles[0])
    $candidateManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $msiOnlyManifestRejected = $false
    try { $null = & $collector -CandidateSha $sha -MsiPath $candidateMsi -ProvenancePath $manifestPath 2>&1 }
    catch { $msiOnlyManifestRejected = $true }
    if (-not $msiOnlyManifestRejected) { throw 'MSI-only manifest was accepted as complete split-CAB build provenance.' }

    # Six declared cabinets with rv3 replaced by rv7 is not a valid cabinet
    # inventory, even if the supplied MSI bytes and signature still match.
    $candidateManifest.files = @($validManifestFiles | Where-Object { $_.name -cne 'rv3.cab' })
    $candidateManifest.files += [ordered]@{ name = 'rv7.cab'; sha256 = ('a' * 64) }
    $candidateManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $gapManifestRejected = $false
    try { $null = & $collector -CandidateSha $sha -MsiPath $candidateMsi -ProvenancePath $manifestPath 2>&1 }
    catch { $gapManifestRejected = $true }
    if (-not $gapManifestRejected) { throw 'Noncontiguous rv1..rvN CAB manifest was accepted.' }
    $candidateManifest.files = $validManifestFiles
    $candidateManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

    # A provenance manifest being rewritten by the packager is not stable
    # evidence even if its current bytes happen to contain a valid JSON record.
    $manifestWriter = [IO.File]::Open(
        $manifestPath,
        [IO.FileMode]::Open,
        [IO.FileAccess]::ReadWrite,
        [IO.FileShare]::ReadWrite
    )
    try {
        $mutableManifestRejected = $false
        try {
            $null = & $collector -CandidateSha $sha -MsiPath $candidateMsi -CabPath $sixCabPaths -ProvenancePath $manifestPath 2>&1
        } catch { $mutableManifestRejected = $true }
        if (-not $mutableManifestRejected) {
            throw 'A writer-open provenance manifest was incorrectly accepted.'
        }
    } finally {
        $manifestWriter.Dispose()
    }
    $stableManifest = (& $collector -CandidateSha $sha -MsiPath $candidateMsi -CabPath $sixCabPaths -ProvenancePath $manifestPath |
        Out-String | ConvertFrom-Json)
    if ($stableManifest.provenance.status -cne 'matched_complete' -or
        $stableManifest.provenance.verifiedArtifacts -ne 7) {
        throw 'A stable provenance manifest could not be validated after its writer closed.'
    }

    # Identical bytes from a different staging directory must not certify
    # a single installer set. Exercise both the manifest and CAB paths,
    # checking the intended rejection rather than any incidental error.
    $otherStage = Join-Path $fixture 'other build staging'
    New-Item -ItemType Directory -Path $otherStage -ErrorAction Stop | Out-Null
    $otherManifest = Join-Path $otherStage 'build-provenance.json'
    $otherCab = Join-Path $otherStage 'rv3.cab'
    Copy-Item -LiteralPath $manifestPath -Destination $otherManifest
    Copy-Item -LiteralPath $candidateCabPaths[2] -Destination $otherCab
    $otherManifestRejected = $false
    try {
        $null = & $collector -CandidateSha $sha -MsiPath $candidateMsi -CabPath $sixCabPaths -ProvenancePath $otherManifest
    } catch {
        if ($_.Exception.Message -notmatch 'Manifest and MSI must be in the same staging directory') { throw }
        $otherManifestRejected = $true
    }
    if (-not $otherManifestRejected) { throw 'Identical manifest from another staging directory was accepted.' }
    $mixedCabPaths = @($sixCabPaths | ForEach-Object { $_ })
    $mixedCabPaths[2] = $otherCab
    $otherCabRejected = $false
    try {
        $null = & $collector -CandidateSha $sha -MsiPath $candidateMsi -CabPath $mixedCabPaths -ProvenancePath $manifestPath
    } catch {
        if ($_.Exception.Message -notmatch 'Artifact hash, name, or directory conflicts with build provenance') { throw }
        $otherCabRejected = $true
    }
    if (-not $otherCabRejected) { throw 'Identical CAB from another staging directory was accepted.' }
    # Rejected inputs must not change the original build or copied artifacts.
    if ((Get-FileHash -LiteralPath $otherManifest -Algorithm SHA256).Hash -cne
        (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash -or
        (Get-FileHash -LiteralPath $otherCab -Algorithm SHA256).Hash -cne
        (Get-FileHash -LiteralPath $candidateCabPaths[2] -Algorithm SHA256).Hash) {
        throw 'A rejected cross-directory provenance check modified fixture bytes.'
    }
    $originalStage = (& $collector -CandidateSha $sha -MsiPath $candidateMsi -CabPath $sixCabPaths -ProvenancePath $manifestPath |
        Out-String | ConvertFrom-Json)
    if ($originalStage.provenance.status -cne 'matched_complete' -or $originalStage.provenance.verifiedArtifacts -ne 7) {
        throw 'Cross-directory rejection prevented subsequent valid same-directory evidence.'
    }

    $duplicatePathRejected = $false
    try { $null = & $collector -CandidateSha $sha -MsiPath $candidateMsi -CabPath @($candidateCab, $candidateCab) 2>&1 }
    catch { $duplicatePathRejected = $true }
    if (-not $duplicatePathRejected) { throw 'A repeated CAB source path was counted twice.' }
    # A modified middle CAB must fail provenance validation even when every
    # other CAB and the MSI still hash to their declared values.
    [System.IO.File]::WriteAllBytes($candidateCabPaths[2], [byte[]](77, 83, 67, 70, 255, 0, 17, 99, 51))
    $tamperedCabRejected = $false
    try { $null = & $collector -CandidateSha $sha -MsiPath $candidateMsi -CabPath $sixCabPaths -ProvenancePath $manifestPath 2>&1 }
    catch { $tamperedCabRejected = $true }
    if (-not $tamperedCabRejected) { throw 'A changed middle CAB incorrectly passed build provenance.' }
    [System.IO.File]::WriteAllBytes($candidateCabPaths[2], [byte[]](77, 83, 67, 70, 255, 0, 17, 3, 51))
    $candidateManifest.source_commit = ('f' * 40)
    $candidateManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $wrongCommitRejected = $false
    try { $null = & $collector -CandidateSha $sha -MsiPath $candidateMsi -ProvenancePath $manifestPath 2>&1 }
    catch { $wrongCommitRejected = $true }
    if (-not $wrongCommitRejected) { throw 'A different build commit was accepted as the requested candidate.' }
    $candidateManifest.source_commit = $sha
    $candidateManifest.files[0].sha256 = ('b' * 64)
    $candidateManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $wrongHashRejected = $false
    try { $null = & $collector -CandidateSha $sha -MsiPath $candidateMsi -ProvenancePath $manifestPath 2>&1 }
    catch { $wrongHashRejected = $true }
    if (-not $wrongHashRejected) { throw 'A mismatched installer SHA-256 was accepted as build provenance.' }
    $candidateManifest.files[0].sha256 = $expectedHash
    $candidateManifest.msi_verified = $false
    $candidateManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $unverifiedBuildRejected = $false
    try { $null = & $collector -CandidateSha $sha -MsiPath $candidateMsi -ProvenancePath $manifestPath 2>&1 }
    catch { $unverifiedBuildRejected = $true }
    if (-not $unverifiedBuildRejected) { throw 'An unverified MSI build was accepted as verified provenance.' }
    $candidateManifest.msi_verified = $true
    # A forged build manifest might encode attestation flags as JSON 1 or
    # "true". PowerShell ordinarily coerces both to $true, so these must fail
    # instead of marking an unverified MSI/CAB candidate as source-clean.
    foreach ($flagName in @('source_tree_clean', 'msi_verified')) {
        foreach ($untrustedValue in @(1, 'true', 'yes')) {
            $originalFlag = $candidateManifest[$flagName]
            $candidateManifest[$flagName] = $untrustedValue
            $candidateManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
            $forgedFlagRejected = $false
            try { $null = & $collector -CandidateSha $sha -MsiPath $candidateMsi -ProvenancePath $manifestPath 2>&1 }
            catch { $forgedFlagRejected = $true }
            $candidateManifest[$flagName] = $originalFlag
            if (-not $forgedFlagRejected) {
                throw "Non-Boolean $flagName attestation was accepted: $untrustedValue"
            }
        }
    }
    $candidateManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $candidateManifest.files += $candidateManifest.files[0]
    $candidateManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $duplicateRejected = $false
    try { $null = & $collector -CandidateSha $sha -MsiPath $candidateMsi -ProvenancePath $manifestPath 2>&1 }
    catch { $duplicateRejected = $true }
    if (-not $duplicateRejected) { throw 'A duplicated artifact record was accepted as provenance.' }
    $noMsiRejected = $false
    try { $null = & $collector -CandidateSha $sha -ProvenancePath $manifestPath 2>&1 }
    catch { $noMsiRejected = $true }
    if (-not $noMsiRejected) { throw 'A build manifest without an actual MSI was accepted as installer evidence.' }
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
    [System.IO.File]::WriteAllBytes($sample, [byte[]](208, 207, 17, 224, 161, 177, 26, 225, 0, 1, 2, 127, 128, 254))
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
    # Renaming an unrelated executable or truncated binary to .MSI/.CAB
    # must not yield a supposedly hashed installer artifact. These samples
    # have valid extensions but invalid container signatures.
    $invalidHeaders = @(
        @{ argument = 'MsiPath'; name = 'renamed-executable.msi'; bytes = [byte[]](77, 90, 0, 0, 0, 0, 0, 0) }
        @{ argument = 'MsiPath'; name = 'truncated-installer.msi'; bytes = [byte[]](208, 207, 17) }
        @{ argument = 'CabPath'; name = 'renamed-executable.cab'; bytes = [byte[]](77, 90, 0, 0, 0) }
        @{ argument = 'CabPath'; name = 'truncated-cabinet.cab'; bytes = [byte[]](77, 83, 67) }
    )
    foreach ($invalidHeader in $invalidHeaders) {
        $invalidPath = Join-Path $fixture $invalidHeader.name
        [System.IO.File]::WriteAllBytes($invalidPath, $invalidHeader.bytes)
        $arguments = @{ CandidateSha = $sha }
        $arguments[$invalidHeader.argument] = $invalidPath
        $headerRejected = $false
        try { $null = & $collector @arguments 2>&1 } catch { $headerRejected = $true }
        if (-not $headerRejected) {
            throw "Invalid installer signature was incorrectly accepted: $($invalidHeader.name)"
        }
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
    # Exercise the same driver-path selector used by the real evidence collector.
    # Disposable MZ bytes are never executed: they only test path selection.
    $gpuFixture = Join-Path $fixture 'fixture-nvidia-smi.exe'
    [System.IO.File]::WriteAllBytes($gpuFixture, [byte[]](77, 90, 0, 0))
    $missingGpu = Join-Path $fixture 'missing-nvidia-smi.exe'
    if ((Get-ReefVisionTrustedGpuTool -Candidates @($missingGpu, $gpuFixture)) -cne $gpuFixture) {
        throw 'GPU tool selector did not choose an existing regular file.'
    }
    if ($null -ne (Get-ReefVisionTrustedGpuTool -Candidates @($missingGpu))) {
        throw 'Missing GPU tool was treated as available.'
    }
    if ($linkCreated) {
        if ($null -ne (Get-ReefVisionTrustedGpuTool -Candidates @($fileLink))) {
            throw 'A linked GPU tool was selected for read-only evidence execution.'
        }
        if ((Get-ReefVisionTrustedGpuTool -Candidates @($fileLink, $gpuFixture)) -cne $gpuFixture) {
            throw 'GPU selector did not skip a linked candidate and choose a regular file.'
        }
    }
    if ($folderLinkCreated) {
        $linkedGpuParent = Join-Path $folderLink 'fixture-nvidia-smi.exe'
        if ($null -ne (Get-ReefVisionTrustedGpuTool -Candidates @($linkedGpuParent))) {
            throw 'GPU executable through a linked parent was selected for execution.'
        }
    }
    Write-Output 'PASS: SHA validation, five/six-CAB manifest coverage, duplicate/tampered CAB rejection, MSI/CAB headers, stable handle hashes, mutable-writer rejection, linked paths where supported, safe reparse-free GPU discovery, and evidence limitations.'
} finally {
    Remove-Item -LiteralPath $fixture -Recurse -Force -ErrorAction SilentlyContinue
}
