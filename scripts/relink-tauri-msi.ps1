param(
    [ValidateSet("x86_64-pc-windows-msvc", "i686-pc-windows-msvc", "aarch64-pc-windows-msvc")]
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Architecture = switch ($TargetTriple) {
    "x86_64-pc-windows-msvc" { "x64" }
    "i686-pc-windows-msvc" { "x86" }
    "aarch64-pc-windows-msvc" { "arm64" }
    default { throw "Unsupported target triple: $TargetTriple" }
}

function Invoke-ReefVisionNativeTool {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$LogPath
    )

    $PreviousErrorActionPreference = $ErrorActionPreference
    $ExitCode = 1
    Push-Location $WorkingDirectory
    try {
        # Windows PowerShell promotes native stderr to ErrorRecord instances.
        # WiX writes ordinary progress and warnings there, so the native exit
        # code is authoritative while every line is retained in the log.
        $ErrorActionPreference = "Continue"
        & $FilePath @Arguments 2>&1 |
            Tee-Object -FilePath $LogPath |
            ForEach-Object { Write-Host ([string]$_) }
        $ExitCode = if ($null -eq $LASTEXITCODE) { 1 } else { $LASTEXITCODE }
    }
    finally {
        Pop-Location
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    return $ExitCode
}

$TauriRoot = Join-Path $Root "apps\web\src-tauri"
$ReleaseRoot = Join-Path $TauriRoot "target\$TargetTriple\release"
$WixWorkingDirectory = Join-Path $ReleaseRoot "wix\$Architecture"
$InstallerDirectory = Join-Path $ReleaseRoot "bundle\msi"
$TauriConfigPath = Join-Path $TauriRoot "tauri.conf.json"
$VerificationScript = Join-Path $PSScriptRoot "verify-windows-msi.ps1"
$WixToolsDirectory = Join-Path $env:LOCALAPPDATA "tauri\WixTools314"
$CandlePath = Join-Path $WixToolsDirectory "candle.exe"
$LightPath = Join-Path $WixToolsDirectory "light.exe"
$WixUtilExtension = Join-Path $WixToolsDirectory "WixUtilExtension.dll"
$WixUiExtension = Join-Path $WixToolsDirectory "WixUIExtension.dll"
$LocalePath = Join-Path $WixWorkingDirectory "locale.wxl"
$MainWixSource = Join-Path $WixWorkingDirectory "main.wxs"
$ApplicationPath = Join-Path $ReleaseRoot "reefvision-desktop.exe"

foreach ($RequiredPath in @(
    $WixWorkingDirectory,
    $TauriConfigPath,
    $VerificationScript,
    $CandlePath,
    $LightPath,
    $WixUtilExtension,
    $WixUiExtension,
    $LocalePath,
    $MainWixSource,
    $ApplicationPath
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required WiX recovery input is missing: $RequiredPath"
    }
}

$WixObjects = @(
    Get-ChildItem -LiteralPath $WixWorkingDirectory -Filter "*.wixobj" -File |
        Where-Object { $_.Name -ne "main-external.wixobj" } |
        Sort-Object -Property Name
)
if ($WixObjects.Count -eq 0) {
    throw "No generated WiX object files were found in $WixWorkingDirectory"
}

$TauriConfig = Get-Content -LiteralPath $TauriConfigPath -Raw | ConvertFrom-Json
$SafeProductName = [regex]::Replace([string]$TauriConfig.productName, "[^A-Za-z0-9._-]+", "")
if (-not $SafeProductName) {
    throw "The Tauri product name cannot be converted to a safe MSI filename."
}
$Version = [string]$TauriConfig.version
$InstallerName = "{0}_{1}_{2}_en-US.msi" -f $SafeProductName, $Version, $Architecture
$FinalInstaller = Join-Path $InstallerDirectory $InstallerName

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$ArtifactDirectory = Join-Path $Root ".artifacts\wix-relink-$Timestamp"
$EmbeddedOutput = Join-Path $ArtifactDirectory "embedded-relinked.msi"
$EmbeddedLog = Join-Path $ArtifactDirectory "light-embedded.log"
$ExternalSourceCopy = Join-Path $ArtifactDirectory "main-external.wxs"
$CandleLog = Join-Path $ArtifactDirectory "candle-external.log"
$ExternalLog = Join-Path $ArtifactDirectory "light-external.log"
$ExternalLayout = Join-Path $ArtifactDirectory "external-layout"
$ExternalOutput = Join-Path $ExternalLayout $InstallerName
$VerificationDirectory = Join-Path $ArtifactDirectory "msi-extraction"
$WixTempDirectory = Join-Path $ArtifactDirectory "wix-temp"
$ExternalWixSource = Join-Path $WixWorkingDirectory "main-external.wxs"
$ExternalWixObject = Join-Path $WixWorkingDirectory "main-external.wixobj"

New-Item -ItemType Directory -Path $ArtifactDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $ExternalLayout -Force | Out-Null
New-Item -ItemType Directory -Path $InstallerDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $WixTempDirectory -Force | Out-Null
Remove-Item -LiteralPath $EmbeddedOutput -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $ExternalOutput -Force -ErrorAction SilentlyContinue

$PreviousWixMums = $env:WIX_MUMS
$PreviousWixMcslfs = $env:WIX_MCSLFS
$PreviousWixTemp = $env:WIX_TEMP
try {
    # WiX's CAB API is not internally multithreaded. A high core count can add
    # I/O pressure without accelerating a single embedded cabinet, so the first
    # recovery attempt is deliberately serialized and uses a repository-local
    # temporary directory with ample free space.
    $env:WIX_MUMS = "512"
    $env:WIX_MCSLFS = "512"
    $env:WIX_TEMP = $WixTempDirectory

    $EmbeddedArguments = @(
        "-v",
        "-sval",
        "-ct", "1",
        "-notidy",
        "-ext", $WixUtilExtension,
        "-ext", $WixUiExtension,
        "-o", $EmbeddedOutput,
        "-cultures:en-us",
        "-loc", $LocalePath
    ) + @($WixObjects | ForEach-Object { $_.FullName })

    Write-Host "Trying a serialized embedded-cabinet relink..." -ForegroundColor Cyan
    Write-Host "Verbose linker log: $EmbeddedLog" -ForegroundColor DarkGray
    $EmbeddedExitCode = Invoke-ReefVisionNativeTool `
        -FilePath $LightPath `
        -Arguments $EmbeddedArguments `
        -WorkingDirectory $WixWorkingDirectory `
        -LogPath $EmbeddedLog

    if (
        $EmbeddedExitCode -eq 0 -and
        (Test-Path -LiteralPath $EmbeddedOutput -PathType Leaf)
    ) {
        Copy-Item -LiteralPath $EmbeddedOutput -Destination $FinalInstaller -Force
        Write-Host "Serialized embedded MSI created: $FinalInstaller" -ForegroundColor Green
        & $VerificationScript -MsiPath $FinalInstaller -OutputDirectory $VerificationDirectory
        if (-not $?) {
            throw "The serialized embedded MSI failed ReefVision payload verification."
        }
        Write-Host "MSI relink and extracted-payload verification passed." -ForegroundColor Green
        Write-Host "Installer: $FinalInstaller" -ForegroundColor Green
        Write-Host "Evidence: $ArtifactDirectory" -ForegroundColor Green
        return
    }

    Write-Warning (
        "The embedded cabinet could not be finalized. Rebuilding the generated " +
        "WiX source as a multi-cab external offline bundle."
    )

    $SourceText = Get-Content -LiteralPath $MainWixSource -Raw
    $ExternalMedia = (
        '<MediaTemplate CabinetTemplate="rv{0}.cab" EmbedCab="no" ' +
        'CompressionLevel="mszip" MaximumUncompressedMediaSize="512" ' +
        'MaximumCabinetSizeForLargeFileSplitting="512" />'
    )
    $RegexOptions = [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    $MediaTemplateRegex = New-Object System.Text.RegularExpressions.Regex(
        '<MediaTemplate\b[^>]*/>',
        $RegexOptions
    )
    $MediaRegex = New-Object System.Text.RegularExpressions.Regex(
        '<Media\b[^>]*\bCabinet\s*=\s*"[^"]+"[^>]*/>',
        $RegexOptions
    )

    if ($MediaTemplateRegex.IsMatch($SourceText)) {
        $ExternalSourceText = $MediaTemplateRegex.Replace(
            $SourceText,
            $ExternalMedia,
            1
        )
    }
    elseif ($MediaRegex.IsMatch($SourceText)) {
        $ExternalSourceText = $MediaRegex.Replace(
            $SourceText,
            $ExternalMedia,
            1
        )
    }
    else {
        throw "The generated Tauri WiX source does not contain a replaceable Media or MediaTemplate element."
    }

    $Utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText(
        $ExternalWixSource,
        $ExternalSourceText,
        $Utf8WithoutBom
    )
    Copy-Item -LiteralPath $ExternalWixSource -Destination $ExternalSourceCopy -Force
    Remove-Item -LiteralPath $ExternalWixObject -Force -ErrorAction SilentlyContinue

    $CandleArguments = @(
        "-nologo",
        "-arch", $Architecture,
        "-ext", $WixUtilExtension,
        "-ext", $WixUiExtension,
        "-dSourceDir=$ApplicationPath",
        "-out", $ExternalWixObject,
        $ExternalWixSource
    )
    Write-Host "Compiling the external-cabinet WiX source..." -ForegroundColor Cyan
    $CandleExitCode = Invoke-ReefVisionNativeTool `
        -FilePath $CandlePath `
        -Arguments $CandleArguments `
        -WorkingDirectory $WixWorkingDirectory `
        -LogPath $CandleLog
    if (
        $CandleExitCode -ne 0 -or
        -not (Test-Path -LiteralPath $ExternalWixObject -PathType Leaf)
    ) {
        throw "WiX external-cabinet compilation failed with exit code $CandleExitCode. Inspect $CandleLog."
    }

    $ExternalArguments = @(
        "-v",
        "-sval",
        "-ct", "1",
        "-notidy",
        "-ext", $WixUtilExtension,
        "-ext", $WixUiExtension,
        "-o", $ExternalOutput,
        "-cultures:en-us",
        "-loc", $LocalePath,
        $ExternalWixObject
    )
    Write-Host "Linking the external multi-cab offline bundle..." -ForegroundColor Cyan
    Write-Host "Verbose linker log: $ExternalLog" -ForegroundColor DarkGray
    $ExternalExitCode = Invoke-ReefVisionNativeTool `
        -FilePath $LightPath `
        -Arguments $ExternalArguments `
        -WorkingDirectory $ExternalLayout `
        -LogPath $ExternalLog
    if (
        $ExternalExitCode -ne 0 -or
        -not (Test-Path -LiteralPath $ExternalOutput -PathType Leaf)
    ) {
        throw "WiX external-cabinet linking failed with exit code $ExternalExitCode. Inspect $ExternalLog."
    }

    $ExternalCabinets = @(
        Get-ChildItem -LiteralPath $ExternalLayout -Filter "*.cab" -File |
            Sort-Object -Property Name
    )
    if ($ExternalCabinets.Count -eq 0) {
        throw "WiX reported success but produced no external cabinet files."
    }

    Remove-Item -LiteralPath $FinalInstaller -Force -ErrorAction SilentlyContinue
    Get-ChildItem -LiteralPath $InstallerDirectory -Filter "rv*.cab" -File -ErrorAction SilentlyContinue |
        Remove-Item -Force
    Copy-Item -LiteralPath $ExternalOutput -Destination $FinalInstaller -Force
    foreach ($Cabinet in $ExternalCabinets) {
        Copy-Item -LiteralPath $Cabinet.FullName -Destination $InstallerDirectory -Force
    }

    $BundleNotice = Join-Path $InstallerDirectory "ReefVision_1.7.0_OFFLINE_BUNDLE.txt"
    @(
        "ReefVision offline Windows installer bundle",
        "",
        "Keep the MSI and every rv*.cab file together in this directory.",
        "Run $InstallerName to install ReefVision.",
        "Copying or distributing the MSI without its CAB files will not work."
    ) | Set-Content -LiteralPath $BundleNotice -Encoding UTF8

    Write-Host (
        "External cabinet bundle created with $($ExternalCabinets.Count) CAB files: " +
        $InstallerDirectory
    ) -ForegroundColor Green
    & $VerificationScript -MsiPath $FinalInstaller -OutputDirectory $VerificationDirectory
    if (-not $?) {
        throw "The external-cabinet MSI failed ReefVision payload verification."
    }

    Write-Host "External multi-cab MSI and extracted-payload verification passed." -ForegroundColor Green
    Write-Host "Installer bundle directory: $InstallerDirectory" -ForegroundColor Green
    Write-Host "MSI: $FinalInstaller" -ForegroundColor Green
    Write-Host "Evidence: $ArtifactDirectory" -ForegroundColor Green
}
finally {
    $env:WIX_MUMS = $PreviousWixMums
    $env:WIX_MCSLFS = $PreviousWixMcslfs
    $env:WIX_TEMP = $PreviousWixTemp
}
