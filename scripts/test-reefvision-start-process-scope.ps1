# Windows-only, read-only simulation of installed-app process isolation.
# Mock process enumeration and Stop-Process: never terminate a real process.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'lib\reefvision-commands.ps1')

$installed = 'C:\ReefVision\ReefVision.exe'
$script:fakeProcesses = @(
    [pscustomobject]@{ Id = 101; ProcessName = 'ReefVision'; Path = $installed },
    [pscustomobject]@{ Id = 102; ProcessName = 'ReefVision'; Path = 'D:\AnotherStudy\ReefVision.exe' },
    [pscustomobject]@{ Id = 103; ProcessName = 'ReefVision'; Path = $null },
    [pscustomobject]@{ Id = 104; ProcessName = 'reefvision-api'; Path = 'C:\ReefVision\backend\reefvision-api\reefvision-api.exe' },
    [pscustomobject]@{ Id = 105; ProcessName = 'reefvision-api'; Path = 'C:\ReefVision-archive\reefvision-api.exe' },
    [pscustomobject]@{ Id = 106; ProcessName = 'reefvision-api'; Path = 'D:\AnotherStudy\reefvision-api.exe' },
    [pscustomobject]@{ Id = 107; ProcessName = 'reefvision-api'; Path = $null },
    [pscustomobject]@{ Id = 108; ProcessName = 'reefvision-api-x86_64-pc-windows-msvc'; Path = 'c:\reefvision\reefvision-api-x86_64-pc-windows-msvc.exe' }
)
$script:stopped = @()
function Get-Process {
    param([string]$ErrorAction)
    return $script:fakeProcesses
}
function Stop-Process {
    param([int]$Id, [switch]$Force, [string]$ErrorAction)
    $script:stopped += $Id
}
function Assert-SameIds {
    param([object[]]$Observed, [int[]]$Expected, [string]$Context)
    $actual = @($Observed | ForEach-Object { [int]$_ } | Sort-Object)
    $wanted = @($Expected | Sort-Object)
    if (($actual -join ',') -ne ($wanted -join ',')) {
        throw "${Context}: observed '$($actual -join ',')', expected '$($wanted -join ',')'"
    }
}
$observed = Get-ReefVisionDesktopProcessList -InstalledExecutablePath $installed
Assert-SameIds -Observed @($observed.desktop | ForEach-Object { $_.Id }) -Expected @(101) -Context 'installed desktop'
Assert-SameIds -Observed @($observed.sidecars | ForEach-Object { $_.Id }) -Expected @(104,108) -Context 'installed sidecars'

Stop-ReefVisionRunningProcesses -InstalledExecutablePath $installed
Assert-SameIds -Observed $script:stopped -Expected @(101,104,108) -Context 'restart scope'
# An unrelated valid ReefVision installation must remain untouched.
$script:stopped = @()
Stop-ReefVisionRunningProcesses -InstalledExecutablePath 'E:\OtherInstall\ReefVision.exe'
Assert-SameIds -Observed $script:stopped -Expected @() -Context 'foreign installation'
if (Test-ReefVisionManagedProcessPath -ProcessPath 'C:\ReefVision-archive\reefvision-api.exe' -InstalledExecutablePath $installed -Kind sidecar) {
    throw 'A sibling directory was incorrectly treated as the installed backend.'
}
if (Test-ReefVisionManagedProcessPath -ProcessPath $null -InstalledExecutablePath $installed -Kind desktop) {
    throw 'An unreadable process executable was incorrectly accepted.'
}
Write-Host 'ReefVision installed process isolation: enumeration and simulated restart passed.'
