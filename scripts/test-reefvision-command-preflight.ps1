# Run on Windows only. Every case uses a disposable LOCALAPPDATA directory.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$previousLocalAppData = $env:LOCALAPPDATA
$previousLocation = (Get-Location).Path
$root = Join-Path $env:TEMP ("reefvision-command-preflight-" + [guid]::NewGuid().ToString("N"))
$repo = Join-Path $root "repo"
$env:LOCALAPPDATA = Join-Path $root "local"
$rv = Join-Path $env:LOCALAPPDATA "ReefVision"
$bin = Join-Path $rv "bin"
$support = Join-Path $rv "commands"
$config = Join-Path $rv "config\commands.json"
$startWrapper = Join-Path $bin "start-reefvision.cmd"
$updateWrapper = Join-Path $bin "update-reefvision.cmd"
$installer = Join-Path $PSScriptRoot "install-reefvision-commands.ps1"
$checks = 0

function Assert([bool]$condition, [string]$message) {
    if (-not $condition) { throw $message }
    $script:checks++
}
function Reject([string]$expected, [switch]$Force) {
    $failure = $null
    try { & $installer -RepoPath $repo -Force:$Force 2>&1 | Out-Null }
    catch { $failure = $_.Exception.Message }
    Assert ($null -ne $failure) "Conflicting installation unexpectedly succeeded"
    Assert ($failure.Contains($expected)) "Wrong failure: $failure"
}
function Assert-ConfigUnchanged {
    Assert ((Get-FileHash -LiteralPath $config -Algorithm SHA256).Hash -eq $script:configHash) "Rejected install changed user configuration"
}
try {
    foreach ($dir in @($bin, (Join-Path $repo "apps\web"), (Join-Path $repo "scripts\lib"))) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    foreach ($file in @("pyproject.toml", "apps\web\package.json", "scripts\build-desktop.ps1",
                       "scripts\start-reefvision.ps1", "scripts\update-reefvision.ps1",
                       "scripts\lib\reefvision-commands.ps1", "scripts\lib\reefvision-msi-update.ps1")) {
        Set-Content -LiteralPath (Join-Path $repo $file) -Value "fixture" -Encoding ASCII
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $config) -Force | Out-Null
    Set-Content -LiteralPath $config -Value '{"repo_path":null,"installed_app_path":"preserve"}' -Encoding UTF8
    $script:configHash = (Get-FileHash -LiteralPath $config -Algorithm SHA256).Hash

    # A conflict at the second wrapper must not rewrite the first.
    Set-Content -LiteralPath $startWrapper -Value "@rem ReefVision managed command wrapper" -Encoding ASCII
    Set-Content -LiteralPath $updateWrapper -Value "@echo off & echo foreign" -Encoding ASCII
    $beforeStart = (Get-FileHash -LiteralPath $startWrapper -Algorithm SHA256).Hash
    $beforeUpdate = (Get-FileHash -LiteralPath $updateWrapper -Algorithm SHA256).Hash
    Reject "not ReefVision-managed"
    Assert ((Get-FileHash -LiteralPath $startWrapper -Algorithm SHA256).Hash -eq $beforeStart) "First wrapper changed"
    Assert ((Get-FileHash -LiteralPath $updateWrapper -Algorithm SHA256).Hash -eq $beforeUpdate) "Foreign wrapper changed"
    Assert (-not (Test-Path -LiteralPath $support)) "Support directory created on failure"
    Assert-ConfigUnchanged

    # Missing sources are checked before any support file is copied.
    Remove-Item -LiteralPath $startWrapper,$updateWrapper -Force
    $missing = Join-Path $repo "scripts\update-reefvision.ps1"
    Remove-Item -LiteralPath $missing -Force
    Reject "Required command asset is missing"
    Assert (-not (Test-Path -LiteralPath $support)) "Support directory created with missing source"
    Assert-ConfigUnchanged
    Set-Content -LiteralPath $missing -Value "fixture" -Encoding ASCII

    # The installed updater must not be deployed without its MSI helper.
    $missingMsiHelper = Join-Path $repo "scripts\lib\reefvision-msi-update.ps1"
    Remove-Item -LiteralPath $missingMsiHelper -Force
    Reject "Required command asset is missing"
    Assert (-not (Test-Path -LiteralPath $support)) "Support directory created with missing MSI helper"
    Assert-ConfigUnchanged
    Set-Content -LiteralPath $missingMsiHelper -Value "fixture" -Encoding ASCII

    # -Force cannot replace a directory masquerading as a wrapper.
    New-Item -ItemType Directory -Path $updateWrapper -Force | Out-Null
    Reject "Refusing to replace a directory" -Force
    Assert (Test-Path -LiteralPath $updateWrapper -PathType Container) "Wrapper directory lost"
    Assert-ConfigUnchanged
    Remove-Item -LiteralPath $updateWrapper -Recurse -Force

    # Support script collisions are rejected before configuration changes.
    $collision = Join-Path $support "start-reefvision.ps1"
    New-Item -ItemType Directory -Path $collision -Force | Out-Null
    Reject "Refusing to replace a directory with a ReefVision support script"
    Assert (Test-Path -LiteralPath $collision -PathType Container) "Support directory collision lost"
    Assert-ConfigUnchanged
    Remove-Item -LiteralPath $collision -Recurse -Force

    # Existing support files survive an unrelated unmanaged wrapper conflict.
    $existingSupport = Join-Path $support "start-reefvision.ps1"
    Set-Content -LiteralPath $existingSupport -Value "preserve support" -Encoding ASCII
    Set-Content -LiteralPath $updateWrapper -Value "foreign" -Encoding ASCII
    $supportHash = (Get-FileHash -LiteralPath $existingSupport -Algorithm SHA256).Hash
    Reject "not ReefVision-managed"
    Assert ((Get-FileHash -LiteralPath $existingSupport -Algorithm SHA256).Hash -eq $supportHash) "Existing support overwritten"
    Assert-ConfigUnchanged

    # A regular file at the managed bin directory must never be replaced.
    Remove-Item -LiteralPath $updateWrapper -Force
    Remove-Item -LiteralPath $support -Recurse -Force
    Remove-Item -LiteralPath $bin -Recurse -Force
    Set-Content -LiteralPath $bin -Value "unrelated user file" -Encoding ASCII
    Reject "Refusing to replace a file with a ReefVision command directory"
    Assert (Test-Path -LiteralPath $bin -PathType Leaf) "User file occupying bin lost"
    Assert-ConfigUnchanged

    # A junction must not redirect support-script writes outside LOCALAPPDATA.
    # Windows junctions do not require Developer Mode or administrator access.
    Remove-Item -LiteralPath $bin -Force
    $outside = Join-Path $root 'unmanaged-sentinel'
    New-Item -ItemType Directory -Path $outside -Force | Out-Null
    $sentinel = Join-Path $outside 'preserve.txt'
    Set-Content -LiteralPath $sentinel -Value 'do not change' -Encoding ASCII
    $sentinelHash = (Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash
    New-Item -ItemType Junction -Path $support -Target $outside | Out-Null
    try {
        Reject "reparse-point command directory" -Force
        Assert ((Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -eq $sentinelHash) "Junction target changed"
        Assert-ConfigUnchanged
    }
    finally {
        # Delete only the junction itself; never recursively delete its target.
        Remove-Item -LiteralPath $support -Force
    }
    Assert (Test-Path -LiteralPath $sentinel -PathType Leaf) "Unmanaged junction target lost"
    Write-Host "ReefVision command preflight: $checks assertions passed."
}
finally {
    $env:LOCALAPPDATA = $previousLocalAppData
    Set-Location -LiteralPath $previousLocation
    if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
}
