# Read-only evidence collector for ReefVision 1.0.3 Windows acceptance.
# Run on the Windows acceptance host. Does not install, launch, or alter ReefVision.
param(
    [Parameter(Mandatory = $true)][string]$CandidateSha,
    [string]$MsiPath,
    [string]$CabPath
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($CandidateSha -notmatch '^[0-9a-fA-F]{40}$') {
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
$gpu = $null
# Never execute a PATH-resolved program while collecting supposedly read-only
# evidence. A project-local nvidia-smi.exe could otherwise be launched merely
# by running the acceptance inventory. Prefer known driver installation paths.
$trustedNvidiaSmiPaths = @(
    (Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::System)) 'nvidia-smi.exe')
    (Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles)) 'NVIDIA Corporation\NVSMI\nvidia-smi.exe')
)
$nvidiaSmi = $trustedNvidiaSmiPaths |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1
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
    artifacts = @(
        (Get-ArtifactEvidence -Path $MsiPath -Kind 'msi')
        (Get-ArtifactEvidence -Path $CabPath -Kind 'cab')
    )
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
        'No file contents or scientific datasets are uploaded.'
    )
} | ConvertTo-Json -Depth 7
