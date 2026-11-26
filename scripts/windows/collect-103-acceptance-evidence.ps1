# Read-only evidence collector for ReefVision 1.0.3 Windows acceptance.
# Run on the Windows acceptance host. Does not install, launch, or alter ReefVision.
param(
    [Parameter(Mandatory = $true)][string]$CandidateSha,
    [string]$MsiPath,
    [string[]]$CabPath,
    [string]$ProvenancePath
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($CandidateSha -notmatch '\A[0-9a-fA-F]{40}\z') {
    throw 'CandidateSha must be a full 40-character Git commit SHA.'
}
function Get-ArtifactEvidence([string]$Path, [string]$Kind) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return [pscustomobject]@{ kind = $Kind; status = 'not_provided' }
    }
    $file = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($file.PSIsContainer) { throw "$Kind path is a directory." }
    # Do not follow installer symlinks or junction parents into another build
    # directory. The approved evidence path must identify a regular file.
    if (($file.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "$Kind artifact must not be a symbolic link or reparse point."
    }
    $ancestor = Split-Path -Path $file.FullName -Parent
    while ($ancestor) {
        $directory = Get-Item -LiteralPath $ancestor -Force -ErrorAction Stop
        if (($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Kind artifact path must not traverse a junction or symbolic link."
        }
        $parent = Split-Path -Path $ancestor -Parent
        if (-not $parent -or $parent -eq $ancestor) { break }
        $ancestor = $parent
    }
    # Do not label an arbitrary file as an installer artifact merely because it
    # was supplied in the MSI/CAB argument. This is an extension check, not
    # signature verification or proof of a successful installer build.
    $expectedExtension = if ($Kind -eq 'msi') { '.msi' } elseif ($Kind -eq 'cab') { '.cab' } else { throw "Unknown artifact kind: $Kind" }
    if (-not [string]::Equals($file.Extension, $expectedExtension, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Kind artifact must have the $expectedExtension extension."
    }
    # Hash and count bytes from the SAME open read-only handle. Deny
    # concurrent writers/deleters on Windows: a file still being built must
    # fail evidence collection, not yield a mixed or stale SHA-256/size pair.
    $stream = [System.IO.File]::Open(
        $file.FullName,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    try {
        $bytes = $stream.Length
        # Validate the actual installer container signature, not the extension
        # alone. This is only a magic-byte check; it is NOT MSI/CAB structure,
        # Authenticode, install, or WebView2 verification. Read from the same
        # locked handle that will be hashed to prevent header/hash races.
        $expectedMagic = if ($Kind -eq 'msi') {
            [byte[]](0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1)
        } else {
            [byte[]](0x4D, 0x53, 0x43, 0x46)
        }
        if ($bytes -lt $expectedMagic.Length) {
            throw "$Kind artifact is too short for an installer container header."
        }
        foreach ($expectedByte in $expectedMagic) {
            if ($stream.ReadByte() -ne [int]$expectedByte) {
                throw "$Kind artifact does not have the expected installer container header."
            }
        }
        $stream.Position = 0
        $hasher = [System.Security.Cryptography.SHA256]::Create()
        try {
            $sha256 = ([BitConverter]::ToString($hasher.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
        } finally {
            $hasher.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
    return [pscustomobject]@{
        kind = $Kind
        status = 'hashed'
        headerCheck = 'magic_only'
        path = $file.FullName
        bytes = $bytes
        sha256 = $sha256
    }
}
# Reuse the same validated WebView2 inventory as the clean-install harness.
# The old local probes used a non-WebView2 product GUID and could silently
# report no runtime; provider-based HKLM paths also depend on PowerShell bitness.
# This remains read-only registry evidence, never installed-GUI acceptance.
$acceptanceLibrary = Join-Path (Split-Path -Parent $PSScriptRoot) 'lib/windows-clean-acceptance.ps1'
. $acceptanceLibrary
$runtimeInfo = Get-ReefVisionWebView2RuntimeInfo
$runtimeId = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
$registryPathsByScope = @{
    'machine-32' = "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$runtimeId"
    'machine-64' = "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$runtimeId"
    'user' = "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$runtimeId"
}
$webview = @($runtimeInfo.registrations | ForEach-Object {
    $scope = [string]$_.scope
    if (-not $registryPathsByScope.ContainsKey($scope)) {
        throw "Unexpected WebView2 registry scope: $scope"
    }
    # Preserve the existing 'registryPath'/'version' evidence fields, with an
    # additive 'scope' for unambiguous 32-bit/64-bit machine view provenance.
    [pscustomobject]@{
        registryPath = $registryPathsByScope[$scope]
        version = [string]$_.version
        scope = $scope
    }
})
# Caller-supplied SHA and an MSI hash are not evidence of common build origin.
# The optional manifest check ties supplied bytes to the claimed candidate,
# while explicitly disclosing CABs not supplied to this read-only collector.
# The split-cabinet Windows build produces five or six external CABs.
# Inventory each supplied CAB independently; a single -CabPath was previously
# unable to produce complete same-build evidence for the actual installer.
# Retain a not_provided CAB record for legacy MSI-only invocations.
$cabCandidates = @($CabPath | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
if ($cabCandidates.Count -gt 6) {
    throw 'ReefVision 1.0.3 acceptance supports at most six external CAB paths.'
}
$artifactRecords = @((Get-ArtifactEvidence -Path $MsiPath -Kind 'msi'))
if ($cabCandidates.Count -eq 0) {
    $artifactRecords += Get-ArtifactEvidence -Path $null -Kind 'cab'
} else {
    $seenCabPaths = @{}
    foreach ($cabCandidate in $cabCandidates) {
        $cabEvidence = Get-ArtifactEvidence -Path $cabCandidate -Kind 'cab'
        if ($seenCabPaths.ContainsKey([string]$cabEvidence.path)) {
            throw 'Duplicate external CAB path in acceptance evidence.'
        }
        $seenCabPaths[[string]$cabEvidence.path] = $true
        $artifactRecords += $cabEvidence
    }
}
$provenanceEvidence = [pscustomobject]@{
    status = 'not_provided'
    declaredArtifacts = 0
    verifiedArtifacts = 0
    unverifiedArtifactNames = @()
}
if (-not [string]::IsNullOrWhiteSpace($ProvenancePath)) {
    if ($artifactRecords[0].status -ne 'hashed') {
        throw 'An MSI is required before validating build provenance.'
    }
    $manifestFile = Get-Item -LiteralPath $ProvenancePath -Force -ErrorAction Stop
    if ($manifestFile.PSIsContainer -or $manifestFile.Name -cne 'build-provenance.json') {
        throw 'Provenance must be a build-provenance.json regular file.'
    }
    Assert-ReefVisionNoReparseAncestors -Path $manifestFile.FullName
    $msiDirectory = [IO.Path]::GetDirectoryName([string]$artifactRecords[0].path)
    if (-not [string]::Equals($manifestFile.DirectoryName, $msiDirectory, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Manifest and MSI must be in the same staging directory.'
    }
    # Read a stable manifest snapshot, just as for installer payloads. A
    # concurrent writer must not produce a partial or mixed provenance record.
    $manifestStream = [IO.File]::Open(
        $manifestFile.FullName,
        [IO.FileMode]::Open,
        [IO.FileAccess]::Read,
        [IO.FileShare]::Read
    )
    try {
        $manifestReader = [IO.StreamReader]::new($manifestStream)
        try {
            $manifest = $manifestReader.ReadToEnd() | ConvertFrom-Json
        } finally {
            $manifestReader.Dispose()
        }
    } finally {
        $manifestStream.Dispose()
    }
    # Require scalar JSON strings before comparisons: PowerShell comparison
    # operators filter arrays rather than testing scalar equality.
    if ($manifest.version -isnot [string] -or
        $manifest.version -cne '1.0.3' -or
        $manifest.source_commit -isnot [string] -or
        $manifest.source_commit -cne $CandidateSha.ToLowerInvariant() -or
        # JSON numbers and strings must not masquerade as Boolean proof that
        # a candidate was built from a clean source tree and MSI verified.
        # PowerShell's normal -eq/-ne comparisons coerce 1/"true" to $true.
        $manifest.source_tree_clean -isnot [bool] -or
        $manifest.source_tree_clean -ne $true -or
        $manifest.msi_verified -isnot [bool] -or
        $manifest.msi_verified -ne $true) {
        throw 'Build provenance does not match the candidate version, SHA, or verification flags.'
    }
    $declared = @{}
    foreach ($entry in @($manifest.files)) {
        if ($entry.name -isnot [string] -or $entry.sha256 -isnot [string]) {
            throw 'Build-provenance artifact name and SHA-256 must be scalar JSON strings.'
        }
        $name = $entry.name
        $hash = $entry.sha256
        if ($name -cnotmatch '\A(?:ReefVision_1\.0\.3_x64_en-US\.msi|rv[1-9][0-9]*\.cab)\z' -or
            $hash -cnotmatch '\A[0-9a-f]{64}\z' -or $declared.ContainsKey($name)) {
            throw 'Unsafe, duplicate, or malformed build-provenance artifact.'
        }
        $declared[$name] = $hash
    }
    if (-not $declared.ContainsKey('ReefVision_1.0.3_x64_en-US.msi')) {
        throw 'Build manifest omits the expected MSI.'
    }
    # A caller-written manifest that omits cabinets must not be described as
    # complete provenance for ReefVision's five/six-CAB Windows installer.
    # Requiring a contiguous rv1..rvN set prevents an incomplete or renamed
    # cabinet from disappearing from the declared artifact inventory. This
    # checks manifest completeness, NOT the MSI Media table or authenticity.
    $declaredCabs = @($declared.Keys | Where-Object { $_ -cmatch '^rv[1-9][0-9]*\.cab$' })
    if ($declaredCabs.Count -notin @(5, 6)) {
        throw 'Build provenance must declare five or six external CAB payloads.'
    }
    for ($cabNumber = 1; $cabNumber -le $declaredCabs.Count; $cabNumber++) {
        if (-not $declared.ContainsKey("rv$cabNumber.cab")) {
            throw 'Build provenance must declare contiguous rv1..rvN CAB payloads.'
        }
    }
    $verified = @{}
    foreach ($artifact in $artifactRecords) {
        if ($artifact.status -ne 'hashed') { continue }
        $name = [IO.Path]::GetFileName([string]$artifact.path)
        $directory = [IO.Path]::GetDirectoryName([string]$artifact.path)
        if (-not [string]::Equals($directory, $msiDirectory, [StringComparison]::OrdinalIgnoreCase) -or
            -not $declared.ContainsKey($name) -or
            $declared[$name] -cne $artifact.sha256 -or $verified.ContainsKey($name)) {
            throw 'Artifact hash, name, or directory conflicts with build provenance.'
        }
        $verified[$name] = $true
    }
    $unverified = @($declared.Keys | Where-Object { -not $verified.ContainsKey($_) } | Sort-Object)
    $provenanceEvidence = [pscustomobject]@{
        status = if ($unverified.Count -eq 0) { 'matched_complete' } else { 'matched_subset' }
        declaredArtifacts = $declared.Count
        verifiedArtifacts = $verified.Count
        unverifiedArtifactNames = $unverified
    }
}
$gpu = $null
# Never execute a PATH-resolved program while collecting supposedly read-only
# evidence. A project-local nvidia-smi.exe could otherwise be launched merely
# by running the acceptance inventory. Prefer known driver installation paths.
$trustedNvidiaSmiPaths = @(
    (Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::System)) 'nvidia-smi.exe')
    (Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles)) 'NVIDIA Corporation\NVSMI\nvidia-smi.exe')
)
# Even a literal system/driver path can be a reparse point, redirecting the
# supposedly read-only collector to an arbitrary executable. Reject links in
# both the executable and all parent directories before running GPU inventory.
$nvidiaSmi = Get-ReefVisionTrustedGpuTool -Candidates $trustedNvidiaSmiPaths
if ($null -ne $nvidiaSmi) {
    try {
        $output = @(& $nvidiaSmi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>&1 | ForEach-Object { [string]$_ })
        if ($LASTEXITCODE -eq 0) {
            $gpu = $output
        } else {
            $gpu = @("nvidia-smi exited with code $LASTEXITCODE; GPU inventory unverified")
        }
    } catch {
        $gpu = @("nvidia-smi query failed: $($_.Exception.Message)")
    }
}
$os = Get-CimInstance Win32_OperatingSystem
[pscustomobject]@{
    schema = 'reefvision.windows-acceptance-evidence.v1'
    candidateSha = $CandidateSha.ToLowerInvariant()
    collectedUtc = (Get-Date).ToUniversalTime().ToString('o')
    computer = $env:COMPUTERNAME
    osCaption = $os.Caption
    osVersion = $os.Version
    osBuild = $os.BuildNumber
    powershellVersion = $PSVersionTable.PSVersion.ToString()
    artifacts = $artifactRecords
    provenance = $provenanceEvidence
    webview2 = $webview
    # A denied registry view is unknown, not proof that the runtime is absent.
    # Preserve this machine-local diagnostic without making a GUI PASS claim.
    webview2Inspection = [pscustomobject]@{
        complete = [bool]$runtimeInfo.inspection_complete
        unreadableScopes = @($runtimeInfo.unreadable_scopes)
        invalidScopes = @($runtimeInfo.invalid_scopes)
    }
    nvidia = $gpu
    limitations = @(
        'Read-only inventory; does not prove installation, GUI, training, or scientific acceptance.',
        'MSI/CAB magic-byte checks do not prove package structure, signature trust, or installer validity.',
        'WebView2 registry detection is advisory; absence does not prove runtime is unavailable.',
        'An incomplete WebView2 registry inspection does not establish runtime absence or installed GUI acceptance.',
        'Malformed WebView2 registry versions are reported by scope, without exposing registry values.',
        'GPU inventory uses trusted Windows driver paths only; missing or failed nvidia-smi is not GPU acceptance.',
        'A matching unsigned provenance manifest does not attest the build or prove installation.',
        'Missing CAB artifacts remain unverified even when the supplied MSI hash matches.',
        'The MSI Media table must be checked separately to establish the complete required external CAB set.',
        'No file contents or scientific datasets are uploaded.'
    )
} | ConvertTo-Json -Depth 7
