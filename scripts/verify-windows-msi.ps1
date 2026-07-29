param(
    [Parameter(Mandatory = $true)][string]$MsiPath,
    [string]$OutputDirectory,
    [switch]$RequireSignature,
    [switch]$PerformMachineInstall,
    [switch]$KeepInstalled,
    [string]$ExpectedPublisher
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ($PSVersionTable.PSEdition -eq "Core" -and -not $IsWindows) {
    throw "MSI verification must run on Windows."
}
$Root = Split-Path -Parent $PSScriptRoot
$ResolvedMsi = (Resolve-Path -LiteralPath $MsiPath).Path
if (-not (Test-Path -LiteralPath $ResolvedMsi -PathType Leaf)) {
    throw "MSI not found: $MsiPath"
}
if ([IO.Path]::GetExtension($ResolvedMsi).ToLowerInvariant() -ne ".msi") {
    throw "The supplied installer is not an MSI file."
}
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path `
        $env:USERPROFILE `
        "RVMSI\msi-verification-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$ExtractRoot = Join-Path $OutputDirectory "administrative-image"
$InstallLog = Join-Path $OutputDirectory "msiexec-administrative.log"
$Results = [System.Collections.Generic.List[object]]::new()

function Add-Check {
    param(
        [string]$Name,
        [bool]$Passed,
        [string]$Message,
        [object]$Evidence = $null,
        [bool]$Required = $true
    )
    [void]$Results.Add([pscustomobject]@{
        name = $Name
        passed = $Passed
        required = $Required
        message = $Message
        evidence = $Evidence
    })
    if ($Required -and -not $Passed) {
        throw "$Name failed: $Message"
    }
}

$MsiItem = Get-Item -LiteralPath $ResolvedMsi
$Hash = Get-FileHash -LiteralPath $ResolvedMsi -Algorithm SHA256
Add-Check "MSI exists" ($MsiItem.Length -gt 0) "Installer exists and is non-empty." @{
    path = $ResolvedMsi
    size_bytes = $MsiItem.Length
    sha256 = $Hash.Hash.ToLowerInvariant()
    modified_at = $MsiItem.LastWriteTimeUtc.ToString("o")
}

$Signature = Get-AuthenticodeSignature -LiteralPath $ResolvedMsi
$SignatureEvidence = @{
    status = $Signature.Status.ToString()
    status_message = $Signature.StatusMessage
    signer_subject = if ($Signature.SignerCertificate) {
        $Signature.SignerCertificate.Subject
    }
    else {
        $null
    }
    signer_thumbprint = if ($Signature.SignerCertificate) {
        $Signature.SignerCertificate.Thumbprint
    }
    else {
        $null
    }
    timestamp_subject = if ($Signature.TimeStamperCertificate) {
        $Signature.TimeStamperCertificate.Subject
    }
    else {
        $null
    }
}
$SignatureMessage = if ($Signature.Status -eq "Valid") {
    "Installer signature is valid."
}
else {
    "Signature is not required for this development build."
}
Add-Check `
    "Authenticode signature" `
    ($Signature.Status -eq "Valid") `
    $SignatureMessage `
    $SignatureEvidence `
    ([bool]$RequireSignature)
if ($ExpectedPublisher) {
    $ActualPublisher = if ($Signature.SignerCertificate) {
        $Signature.SignerCertificate.Subject
    }
    else {
        ""
    }
    Add-Check `
        "Expected publisher" `
        ($ActualPublisher -like "*$ExpectedPublisher*") `
        "Signer must contain '$ExpectedPublisher'." `
        @{ expected = $ExpectedPublisher; actual = $ActualPublisher }
}

# Administrative extraction validates the Windows Installer database without changing machine state.
if (Test-Path -LiteralPath $ExtractRoot) {
    Remove-Item -LiteralPath $ExtractRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $ExtractRoot -Force | Out-Null
$AdminArgumentLine = (
    "/a `"$ResolvedMsi`" /qn " +
    "TARGETDIR=`"$ExtractRoot`" /l*v `"$InstallLog`""
)
$Process = Start-Process `
    -FilePath "msiexec.exe" `
    -ArgumentList $AdminArgumentLine `
    -Wait `
    -PassThru
Add-Check `
    "MSI administrative extraction" `
    ($Process.ExitCode -eq 0) `
    "msiexec /a completed with exit code $($Process.ExitCode)." `
    @{
        exit_code = $Process.ExitCode
        log_path = $InstallLog
        extraction_root = $ExtractRoot
    }

$ExtractedFiles = @(
    Get-ChildItem -LiteralPath $ExtractRoot -File -Recurse -ErrorAction Stop
)
Add-Check `
    "Extracted payload" `
    ($ExtractedFiles.Count -gt 0) `
    "Administrative image contains files." `
    @{
        file_count = $ExtractedFiles.Count
        total_bytes = ($ExtractedFiles | Measure-Object Length -Sum).Sum
    }
$Executables = @($ExtractedFiles | Where-Object Extension -eq ".exe")
Add-Check `
    "Executable payload" `
    ($Executables.Count -gt 0) `
    "At least one executable is packaged." `
    @{
        executables = @(
            $Executables |
                ForEach-Object {
                    $_.FullName.Substring($ExtractRoot.Length).TrimStart('\')
                }
        )
    }
$Sidecars = @($Executables | Where-Object Name -match "reefvision-api")
Add-Check `
    "API sidecar payload" `
    ($Sidecars.Count -gt 0) `
    "The packaged ReefVision API sidecar is present." `
    @{ sidecars = @($Sidecars | ForEach-Object FullName) }

$CudaRuntimePatterns = @(
    "cudnn_*.dll",
    "cublas*.dll",
    "cusparse*.dll",
    "cusolver*.dll",
    "cufft*.dll",
    "curand*.dll",
    "nvrtc*.dll",
    "nvJitLink*.dll"
)
$MissingCudaRuntimePatterns = @(
    foreach ($Pattern in $CudaRuntimePatterns) {
        if (@($ExtractedFiles | Where-Object { $_.Name -like $Pattern }).Count -eq 0) {
            $Pattern
        }
    }
)
$CudaRuntimeFiles = @(
    $ExtractedFiles |
        Where-Object {
            $Name = $_.Name
            @($CudaRuntimePatterns | Where-Object { $Name -like $_ }).Count -gt 0
        } |
        Sort-Object -Property Name -Unique
)
$CudaRuntimeMessage = if ($MissingCudaRuntimePatterns.Count -eq 0) {
    "Every required CUDA runtime family is present in the MSI payload."
}
else {
    "Missing CUDA runtime families: $($MissingCudaRuntimePatterns -join ', ')."
}
Add-Check `
    "PyTorch CUDA runtime payload" `
    ($MissingCudaRuntimePatterns.Count -eq 0) `
    $CudaRuntimeMessage `
    @{
        file_count = $CudaRuntimeFiles.Count
        files = @($CudaRuntimeFiles | ForEach-Object Name)
        missing_patterns = $MissingCudaRuntimePatterns
    }

$WebviewFiles = @(
    $ExtractedFiles | Where-Object Name -match "WebView2|msedgewebview"
)
$WebviewMessage = if ($WebviewFiles.Count) {
    "WebView2-related payload files were found."
}
else {
    "No bundled WebView2 runtime was found; system runtime may be required."
}
Add-Check `
    "WebView2 payload observation" `
    $true `
    $WebviewMessage `
    @{ file_count = $WebviewFiles.Count } `
    $false

$MachineInstallEvidence = $null
if ($PerformMachineInstall) {
    $Principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "-PerformMachineInstall requires an elevated PowerShell session."
    }
    $MachineLog = Join-Path $OutputDirectory "msiexec-machine-install.log"
    $MachineArgumentLine = (
        "/i `"$ResolvedMsi`" /qn /norestart /l*v `"$MachineLog`""
    )
    $Install = Start-Process `
        -FilePath "msiexec.exe" `
        -ArgumentList $MachineArgumentLine `
        -Wait `
        -PassThru
    Add-Check `
        "Machine install" `
        ($Install.ExitCode -in @(0, 3010)) `
        "Silent installation completed." `
        @{ exit_code = $Install.ExitCode; log_path = $MachineLog }
    $ProductCode = $null
    $Installer = $null
    $Database = $null
    $View = $null
    $Record = $null
    try {
        $Installer = New-Object -ComObject WindowsInstaller.Installer
        $Database = $Installer.GetType().InvokeMember(
            "OpenDatabase",
            "InvokeMethod",
            $null,
            $Installer,
            @($ResolvedMsi, 0)
        )
        $View = $Database.GetType().InvokeMember(
            "OpenView",
            "InvokeMethod",
            $null,
            $Database,
            @("SELECT `Value` FROM `Property` WHERE `Property`='ProductCode'")
        )
        $View.GetType().InvokeMember(
            "Execute",
            "InvokeMethod",
            $null,
            $View,
            $null
        ) | Out-Null
        $Record = $View.GetType().InvokeMember(
            "Fetch",
            "InvokeMethod",
            $null,
            $View,
            $null
        )
        if ($Record) {
            $ProductCode = $Record.GetType().InvokeMember(
                "StringData",
                "GetProperty",
                $null,
                $Record,
                1
            )
        }
    }
    finally {
        if ($Record) {
            [Runtime.InteropServices.Marshal]::FinalReleaseComObject($Record) |
                Out-Null
        }
        if ($View) {
            [Runtime.InteropServices.Marshal]::FinalReleaseComObject($View) |
                Out-Null
        }
        if ($Database) {
            [Runtime.InteropServices.Marshal]::FinalReleaseComObject($Database) |
                Out-Null
        }
        if ($Installer) {
            [Runtime.InteropServices.Marshal]::FinalReleaseComObject($Installer) |
                Out-Null
        }
    }
    Add-Check `
        "MSI ProductCode" `
        ([bool]$ProductCode) `
        "ProductCode was read from the installer database." `
        @{ product_code = $ProductCode }
    $MachineInstallEvidence = @{
        product_code = $ProductCode
        kept_installed = [bool]$KeepInstalled
    }
    if (-not $KeepInstalled) {
        $UninstallLog = Join-Path $OutputDirectory "msiexec-uninstall.log"
        $UninstallArgumentLine = (
            "/x $ProductCode /qn /norestart /l*v `"$UninstallLog`""
        )
        $Uninstall = Start-Process `
            -FilePath "msiexec.exe" `
            -ArgumentList $UninstallArgumentLine `
            -Wait `
            -PassThru
        Add-Check `
            "Machine uninstall" `
            ($Uninstall.ExitCode -in @(0, 1605, 3010)) `
            "Silent uninstall completed." `
            @{ exit_code = $Uninstall.ExitCode; log_path = $UninstallLog }
    }
}

$RequiredFailures = @(
    $Results | Where-Object { $_.required -and -not $_.passed }
)
$Report = [pscustomobject]@{
    schema = "reefvision-windows-msi-verification-v4"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    msi = @{
        path = $ResolvedMsi
        size_bytes = $MsiItem.Length
        sha256 = $Hash.Hash.ToLowerInvariant()
    }
    administrative_image = $ExtractRoot
    machine_install = $MachineInstallEvidence
    passed = $RequiredFailures.Count -eq 0
    checks = $Results
}
$ReportPath = Join-Path $OutputDirectory "msi-verification.json"
$Report |
    ConvertTo-Json -Depth 10 |
    Set-Content -LiteralPath $ReportPath -Encoding utf8
$ExtractedFiles |
    Select-Object FullName, Length, LastWriteTimeUtc |
    ConvertTo-Json -Depth 4 |
    Set-Content `
        -LiteralPath (Join-Path $OutputDirectory "msi-payload-inventory.json") `
        -Encoding utf8
Write-Host "MSI verification report: $ReportPath"
$Results | Format-Table name, passed, required, message -AutoSize
