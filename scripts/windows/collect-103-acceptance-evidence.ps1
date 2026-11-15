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
        path = $file.FullName
        bytes = $bytes
        sha256 = $sha256
    }
}
$webviewPaths = @(
    'HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F1A6D1A4-3C6D-4E0B-9E14-4DDE4B2A57A9}',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F1A6D1A4-3C6D-4E0B-9E14-4DDE4B2A57A9}',
    'HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F1A6D1A4-3C6D-4E0B-9E14-4DDE4B2A57A9}'
)
$webview = @($webviewPaths | ForEach-Object {
    $entry = Get-ItemProperty -LiteralPath $_ -ErrorAction SilentlyContinue
    if ($null -ne $entry -and $entry.pv) {
        [pscustomobject]@{ registryPath = $_; version = [string]$entry.pv }
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
    nvidia = $gpu
    limitations = @(
        'Read-only inventory; does not prove installation, GUI, training, or scientific acceptance.',
        'WebView2 registry detection is advisory; absence does not prove runtime is unavailable.',
        'GPU inventory uses trusted Windows driver paths only; missing or failed nvidia-smi is not GPU acceptance.',
        'No file contents or scientific datasets are uploaded.'
    )
} | ConvertTo-Json -Depth 7
