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
$script:stopInputs = @()
$script:blockedIds = @()
function Get-Process {
    param([string]$ErrorAction)
    return $script:fakeProcesses
}
function Stop-Process {
    # A positional PID stop is intentionally NOT supported by this mock.
    # Only the exact already-checked Process object may be stopped.
    param([object]$InputObject, [switch]$Force, [string]$ErrorAction)
    if ($null -eq $InputObject -or -not $Force) {
        throw 'The stop did not retain the checked process object.'
    }
    $script:stopInputs += $InputObject
    if ($script:blockedIds -contains ([int]$InputObject.Id)) {
        throw 'Synthetic access denied; keep the installation running.'
    }
    $script:stopped += [int]$InputObject.Id
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
Assert-SameIds -Observed @($script:stopInputs | ForEach-Object { $_.Id }) -Expected @(101,104,108) -Context 'object-backed stops'
# An unrelated valid ReefVision installation must remain untouched.
$script:stopped = @()
$script:stopInputs = @()
Stop-ReefVisionRunningProcesses -InstalledExecutablePath 'E:\OtherInstall\ReefVision.exe'
Assert-SameIds -Observed $script:stopped -Expected @() -Context 'foreign installation'
Assert-SameIds -Observed $script:stopInputs -Expected @() -Context 'no foreign object stops'

# A protected or still-busy sidecar must prevent restart/MSI installation.
# A warning alone would let the installer replace a running research session.
$script:blockedIds = @(104)
$script:stopped = @()
$script:stopInputs = @()
$blockedError = $null
try {
    Stop-ReefVisionRunningProcesses -InstalledExecutablePath $installed
}
catch {
    $blockedError = $_.Exception.Message
}
if ($null -eq $blockedError -or $blockedError -notmatch 'Refusing to restart or update' -or
    $blockedError -notmatch '104') {
    throw "A partial stop did not abort restart/update: $blockedError"
}
Assert-SameIds -Observed $script:stopped -Expected @(101,108) -Context 'partial stop attempts'
Assert-SameIds -Observed @($script:stopInputs | ForEach-Object { $_.Id }) -Expected @(101,104,108) -Context 'blocked instance retained'

# Explicit recovery may proceed only after all managed stops succeed.
$script:blockedIds = @()
$script:stopped = @()
Stop-ReefVisionRunningProcesses -InstalledExecutablePath $installed
Assert-SameIds -Observed $script:stopped -Expected @(101,104,108) -Context 'recovered restart'
if (Test-ReefVisionManagedProcessPath -ProcessPath 'C:\ReefVision-archive\reefvision-api.exe' -InstalledExecutablePath $installed -Kind sidecar) {
    throw 'A sibling directory was incorrectly treated as the installed backend.'
}
if (Test-ReefVisionManagedProcessPath -ProcessPath $null -InstalledExecutablePath $installed -Kind desktop) {
    throw 'An unreadable process executable was incorrectly accepted.'
}
Write-Host 'ReefVision installed process isolation, object-bound stops and fail-closed recovery passed.'
