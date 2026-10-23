# Windows-only, disposable, read-only regression for MSI updater path safety.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'lib\reefvision-msi-update.ps1')
$root = Join-Path $env:TEMP ('rv-msi-preflight-' + [guid]::NewGuid().ToString('N'))
$repo = Join-Path $root 'repo'
$bundle = Get-ReefVisionMsiDirectory -RepoPath $repo
$msi = Join-Path $bundle 'ReefVision_1.0.2_x64_en-US.msi'
$sentinel = Join-Path $root 'preserve.txt'
$passed = 0

function Assert-Throws {
    param([scriptblock]$Action, [string]$Fragment)
    $message = $null
    try { & $Action | Out-Null } catch { $message = $_.Exception.Message }
    if ($null -eq $message -or -not $message.Contains($Fragment)) {
        throw "Expected '$Fragment', received '$message'"
    }
    $script:passed++
}

try {
    New-Item -ItemType Directory -Path $bundle -Force | Out-Null
    Set-Content -LiteralPath $msi -Value 'not an installer' -Encoding ASCII
    Set-Content -LiteralPath $sentinel -Value 'preserve external data' -Encoding ASCII
    $sentinelHash = (Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash
    $actual = Assert-ReefVisionMsiLocalPath -InstallerPath $msi -RepoPath $repo
    if ($actual -ne [System.IO.Path]::GetFullPath($msi)) {
        throw 'Local MSI preflight changed the expected path.'
    }
    $passed++
    Assert-Throws {
        Assert-ReefVisionMsiLocalPath -InstallerPath $sentinel -RepoPath $repo
    } 'outside the exact local build directory'
    Assert-Throws {
        Assert-ReefVisionMsiLocalPath -InstallerPath (Join-Path $bundle 'missing.msi') -RepoPath $repo
    } 'missing from the local build directory'
    Assert-Throws {
        Assert-ReefVisionMsiPayload -InstallerPath $msi -RepoPath $repo -ExpectedVersion '1.0.2' -ExpectedCommit ('a' * 40)
    } 'Python environment missing'

    # A junction can preserve the apparent MSI directory suffix but redirect
    # to a different location. Reject it before any manifest or MSI access.
    $linkedRepo = Join-Path $root 'linked-repo'
    New-Item -ItemType Junction -Path $linkedRepo -Target $repo | Out-Null
    try {
        $linked = Join-Path (Get-ReefVisionMsiDirectory -RepoPath $linkedRepo) (Split-Path -Leaf $msi)
        Assert-Throws {
            Assert-ReefVisionMsiLocalPath -InstallerPath $linked -RepoPath $linkedRepo
        } 'symlink/junction'
    }
    finally {
        Remove-Item -LiteralPath $linkedRepo -Force
    }
    if ((Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -ne $sentinelHash) {
        throw 'MSI preflight changed an unrelated file.'
    }
    $passed++
    Write-Host "MSI update preflight: $passed passed" -ForegroundColor Green
}
finally {
    if (Test-Path -LiteralPath $root) {
        Remove-Item -LiteralPath $root -Recurse -Force
    }
}
