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
    $resolved = Resolve-Path -LiteralPath $Path -ErrorAction Stop
    $file = Get-Item -LiteralPath $resolved.Path -ErrorAction Stop
    if ($file.PSIsContainer) { throw "$Kind path is a directory." }
    return [pscustomobject]@{
        kind = $Kind
        status = 'hashed'
        path = $file.FullName
        bytes = $file.Length
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
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
$nvidiaSmi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
if ($null -ne $nvidiaSmi) {
    try {
        $gpu = @(& $nvidiaSmi.Source --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>&1 | ForEach-Object { [string]$_ })
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
        'No file contents or scientific datasets are uploaded.'
    )
} | ConvertTo-Json -Depth 7
