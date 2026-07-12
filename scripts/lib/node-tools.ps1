Set-StrictMode -Version Latest

function Write-ReefVisionStep {
    param([Parameter(Mandatory = $true)][string]$Message)

    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Refresh-ReefVisionPath {
    if ($env:OS -ne "Windows_NT") {
        return
    }

    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $segments = @($env:Path, $machinePath, $userPath) `
        | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } `
        | ForEach-Object { $_ -split ";" } `
        | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } `
        | Select-Object -Unique
    $env:Path = $segments -join ";"
}

function Find-ReefVisionExecutable {
    param(
        [Parameter(Mandatory = $true)][string[]]$Names,
        [string[]]$FallbackPaths = @()
    )

    foreach ($name in $Names) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $command) {
            return $command.Source
        }
    }

    foreach ($candidate in $FallbackPaths) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    return $null
}

function Get-ReefVisionNodeTools {
    Refresh-ReefVisionPath

    $programFiles = [Environment]::GetFolderPath("ProgramFiles")
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")

    $nodeFallbacks = @(
        (Join-Path $programFiles "nodejs\node.exe"),
        (Join-Path $localAppData "Programs\nodejs\node.exe")
    )
    $npmFallbacks = @(
        (Join-Path $programFiles "nodejs\npm.cmd"),
        (Join-Path $localAppData "Programs\nodejs\npm.cmd")
    )

    $nodePath = Find-ReefVisionExecutable -Names @("node.exe", "node") -FallbackPaths $nodeFallbacks
    # Prefer npm.cmd on Windows so PowerShell execution-policy rules cannot block npm.ps1.
    $npmPath = Find-ReefVisionExecutable -Names @("npm.cmd", "npm.exe", "npm") -FallbackPaths $npmFallbacks

    [PSCustomObject]@{
        Node = $nodePath
        Npm = $npmPath
    }
}

function Get-ReefVisionMajorVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [string[]]$Arguments = @("--version")
    )

    $output = & $Executable @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to run '$Executable $($Arguments -join ' ')'. Output: $output"
    }

    $versionText = ($output | Select-Object -First 1).ToString().Trim().TrimStart("v")
    $majorText = ($versionText -split "\.")[0]
    $major = 0
    if (-not [int]::TryParse($majorText, [ref]$major)) {
        throw "Could not parse a version number from '$versionText'."
    }

    return $major
}

function Install-ReefVisionNodeLts {
    if ($env:OS -ne "Windows_NT") {
        throw "Automatic Node.js installation is currently supported only on Windows. Install an active Node.js LTS release with npm, then rerun this script."
    }

    $winget = Find-ReefVisionExecutable -Names @("winget.exe", "winget")
    if ($null -eq $winget) {
        throw @"
Node.js and npm are required, but Windows Package Manager (winget) is unavailable.
Install the current Node.js LTS Windows installer from https://nodejs.org/en/download,
close and reopen the terminal, and rerun .\scripts\bootstrap.ps1.
"@
    }

    Write-ReefVisionStep "Installing Node.js LTS and npm with Windows Package Manager"
    & $winget install --id OpenJS.NodeJS.LTS --exact --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "Windows Package Manager could not install Node.js LTS (exit code $LASTEXITCODE). Install Node.js LTS manually, reopen the terminal, and rerun the setup."
    }

    Refresh-ReefVisionPath
}

function Confirm-ReefVisionNodeInstall {
    param([switch]$NonInteractive)

    if ($NonInteractive) {
        return $true
    }

    $answer = Read-Host "Node.js/npm were not found. Install Node.js LTS automatically with winget now? [Y/n]"
    return [string]::IsNullOrWhiteSpace($answer) -or $answer -match "^(?i:y|yes)$"
}

function Ensure-ReefVisionNodeTools {
    param(
        [switch]$AllowInstall,
        [switch]$NonInteractive,
        [int]$MinimumNodeMajor = 22,
        [int]$MinimumNpmMajor = 10
    )

    $tools = Get-ReefVisionNodeTools

    if (($null -eq $tools.Node -or $null -eq $tools.Npm) -and $AllowInstall) {
        if (-not (Confirm-ReefVisionNodeInstall -NonInteractive:$NonInteractive)) {
            throw "Setup cancelled. Install Node.js LTS with npm and rerun .\scripts\bootstrap.ps1."
        }

        Install-ReefVisionNodeLts
        $tools = Get-ReefVisionNodeTools
    }

    if ($null -eq $tools.Node -or $null -eq $tools.Npm) {
        throw @"
ReefVision requires Node.js and npm, but one or both were not found.
Run .\scripts\bootstrap.ps1 to use the guided installer, or install Node.js LTS manually.
After installation, close and reopen the terminal before starting ReefVision.
"@
    }

    $nodeMajor = Get-ReefVisionMajorVersion -Executable $tools.Node
    $npmMajor = Get-ReefVisionMajorVersion -Executable $tools.Npm

    if ($nodeMajor -lt $MinimumNodeMajor) {
        throw "Node.js $MinimumNodeMajor or newer is required. Found major version $nodeMajor at '$($tools.Node)'. Install a current LTS release and rerun setup."
    }
    if ($npmMajor -lt $MinimumNpmMajor) {
        throw "npm $MinimumNpmMajor or newer is required. Found major version $npmMajor at '$($tools.Npm)'. Update Node.js/npm and rerun setup."
    }

    Write-Host "Node.js: $(& $tools.Node --version)" -ForegroundColor DarkGray
    Write-Host "npm:     $(& $tools.Npm --version)" -ForegroundColor DarkGray

    return $tools
}

function Get-ReefVisionRustTools {
    Refresh-ReefVisionPath

    $cargoFallbacks = @((Join-Path $env:USERPROFILE ".cargo\bin\cargo.exe"))
    $rustcFallbacks = @((Join-Path $env:USERPROFILE ".cargo\bin\rustc.exe"))

    [PSCustomObject]@{
        Cargo = Find-ReefVisionExecutable -Names @("cargo.exe", "cargo") -FallbackPaths $cargoFallbacks
        Rustc = Find-ReefVisionExecutable -Names @("rustc.exe", "rustc") -FallbackPaths $rustcFallbacks
    }
}

function Get-ReefVisionVsWhere {
    if ($env:OS -ne "Windows_NT") {
        return $null
    }

    $programFilesX86 = ${env:ProgramFiles(x86)}
    if ([string]::IsNullOrWhiteSpace($programFilesX86)) {
        return $null
    }

    $candidate = Join-Path $programFilesX86 "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        return (Resolve-Path -LiteralPath $candidate).Path
    }

    return $null
}

function Get-ReefVisionVisualStudioInstancePath {
    param([string[]]$Requires = @())

    $vswhere = Get-ReefVisionVsWhere
    if ($null -eq $vswhere) {
        return $null
    }

    $arguments = @("-latest", "-products", "*")
    foreach ($component in $Requires) {
        $arguments += @("-requires", $component)
    }
    $arguments += @("-property", "installationPath")

    $installationPath = & $vswhere @arguments 2>$null | Select-Object -First 1
    if ($null -eq $installationPath) {
        return $null
    }

    $installationPath = $installationPath.ToString().Trim()
    if ([string]::IsNullOrWhiteSpace($installationPath)) {
        return $null
    }

    return $installationPath
}

function Import-ReefVisionMsvcEnvironment {
    param(
        [ValidateSet("x86_64-pc-windows-msvc", "i686-pc-windows-msvc", "aarch64-pc-windows-msvc")]
        [string]$TargetTriple = "x86_64-pc-windows-msvc"
    )

    $installationPath = Get-ReefVisionVisualStudioInstancePath -Requires @("Microsoft.VisualStudio.Component.VC.Tools.x86.x64")
    if ($null -eq $installationPath) {
        return $false
    }

    $devCommand = Join-Path $installationPath "Common7\Tools\VsDevCmd.bat"
    if (-not (Test-Path -LiteralPath $devCommand -PathType Leaf)) {
        return $false
    }

    $arch = switch ($TargetTriple) {
        "i686-pc-windows-msvc" { "x86" }
        "aarch64-pc-windows-msvc" { "arm64" }
        default { "x64" }
    }

    $cmd = "${env:SystemRoot}\System32\cmd.exe"
    $tempScript = Join-Path ([System.IO.Path]::GetTempPath()) ("reefvision-vsdevcmd-" + [guid]::NewGuid().ToString() + ".cmd")
    $scriptContent = @(
        "@echo off"
        "call `"$devCommand`" -arch=$arch -host_arch=x64 >nul"
        "if errorlevel 1 exit /b %errorlevel%"
        "set Path=%PATH%"
        "set"
    ) -join "`r`n"

    Set-Content -LiteralPath $tempScript -Value $scriptContent -Encoding ASCII

    try {
        $environment = & $cmd /d /c $tempScript
        if ($LASTEXITCODE -ne 0) {
            return $false
        }
    }
    finally {
        Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
    }

    $importedEnvironment = @{}
    foreach ($line in $environment) {
        $parts = $line -split "=", 2
        if ($parts.Count -ne 2 -or [string]::IsNullOrWhiteSpace($parts[0])) {
            continue
        }

        $name = $parts[0]
        if ($env:OS -eq "Windows_NT" -and $name -ieq "PATH") {
            $name = "Path"
        }
        if ($importedEnvironment.ContainsKey($name)) {
            continue
        }
        $importedEnvironment[$name] = $parts[1]
    }

    foreach ($entry in $importedEnvironment.GetEnumerator()) {
        Set-Item -Path "Env:$($entry.Key)" -Value $entry.Value
    }

    return $null -ne (Find-ReefVisionExecutable -Names @("link.exe", "link"))
}

function Ensure-ReefVisionRustTools {
    param(
        [string]$Purpose = "build the ReefVision desktop application",
        [ValidateSet("x86_64-pc-windows-msvc", "i686-pc-windows-msvc", "aarch64-pc-windows-msvc")]
        [string]$TargetTriple = "x86_64-pc-windows-msvc"
    )

    $tools = Get-ReefVisionRustTools
    if ($null -eq $tools.Cargo -or $null -eq $tools.Rustc) {
        throw @"
ReefVision requires Rust and Cargo to $Purpose.
Install rustup and the Microsoft C++ build tools, reopen the terminal, and rerun this command.
"@
    }

    $requiresMsvcToolchain = $env:OS -eq "Windows_NT" -and $TargetTriple -like "*-pc-windows-msvc"
    if ($requiresMsvcToolchain -and $null -eq (Find-ReefVisionExecutable -Names @("link.exe", "link"))) {
        $importedMsvcEnvironment = Import-ReefVisionMsvcEnvironment -TargetTriple $TargetTriple
        if (-not $importedMsvcEnvironment) {
            $hasAnyVisualStudioBuildTools = $null -ne (Get-ReefVisionVisualStudioInstancePath)
            $hasVisualCppTools = $null -ne (
                Get-ReefVisionVisualStudioInstancePath -Requires @("Microsoft.VisualStudio.Component.VC.Tools.x86.x64")
            )
            if ($hasAnyVisualStudioBuildTools -and -not $hasVisualCppTools) {
                throw @"
ReefVision requires the Microsoft C++ build tools to $Purpose, but the MSVC linker (link.exe) is not available.

Visual Studio Build Tools 2022 is installed, but the C++ toolchain is missing. Open Visual Studio Installer and add:
- Desktop development with C++
- MSVC v143 - VS 2022 C++ x64/x86 build tools
- Windows 11 SDK (or Windows 10 SDK)

After installation, reopen the terminal and rerun this command.
"@
            }

            if ($hasAnyVisualStudioBuildTools -and $hasVisualCppTools) {
                throw @"
ReefVision detected Visual Studio Build Tools 2022, but the MSVC linker (link.exe) is still unavailable.

Open Visual Studio Installer and confirm these components are installed:
- Desktop development with C++
- MSVC v143 - VS 2022 C++ x64/x86 build tools
- Windows 11 SDK (or Windows 10 SDK)

After any installer changes, reopen the terminal and rerun this command.
"@
            }

            throw @"
ReefVision requires the Microsoft C++ build tools to $Purpose, but the MSVC linker (link.exe) is not available.

Install Visual Studio Build Tools 2022 with:
- Desktop development with C++
- MSVC v143 - VS 2022 C++ x64/x86 build tools
- Windows 11 SDK (or Windows 10 SDK)

After installation, reopen the terminal and rerun this command.
"@
        }
    }

    Write-Host "cargo:   $(& $tools.Cargo --version)" -ForegroundColor DarkGray
    Write-Host "rustc:   $(& $tools.Rustc --version)" -ForegroundColor DarkGray
    return $tools
}

function Repair-ReefVisionPackageLock {
    param(
        [Parameter(Mandatory = $true)][string]$LockFilePath
    )

    if (-not (Test-Path -LiteralPath $LockFilePath -PathType Leaf)) {
        return
    }

    $resolvedPath = (Resolve-Path -LiteralPath $LockFilePath).Path
    $content = Get-Content -LiteralPath $resolvedPath -Raw
    $updated = $content -replace 'https://[^/"]+/artifactory/api/npm/npm-public/', 'https://registry.npmjs.org/'
    if ($updated -ne $content) {
        Set-Content -LiteralPath $resolvedPath -Value $updated -NoNewline
        Write-Host "Normalized npm package-lock registry URLs to registry.npmjs.org." -ForegroundColor DarkGray
    }
}

function Invoke-ReefVisionNpm {
    param(
        [Parameter(Mandatory = $true)]$NodeTools,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string[]]$AdditionalPathEntries = @()
    )

    $previousPath = $env:Path
    [string[]]$pathEntries = @(
        (Split-Path -Parent $NodeTools.Node)
        $AdditionalPathEntries
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique

    for ($index = $pathEntries.Count - 1; $index -ge 0; $index -= 1) {
        $entry = $pathEntries[$index]
        if (($env:Path -split ";") -notcontains $entry) {
            $env:Path = "$entry;$env:Path"
        }
    }

    try {
        & $NodeTools.Npm @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "npm failed with exit code $LASTEXITCODE while running: npm $($Arguments -join ' ')"
        }
    }
    finally {
        $env:Path = $previousPath
    }
}

function Assert-ReefVisionPublicLockfile {
    param(
        [Parameter(Mandatory = $true)]$NodeTools,
        [string]$ProjectDir = "apps/web"
    )

    $scriptPath = Join-Path $ProjectDir "scripts\check-lockfile.mjs"
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        return
    }

    Invoke-ReefVisionNpm -NodeTools $NodeTools -Arguments @("--prefix", $ProjectDir, "run", "lockfile:check")
}
