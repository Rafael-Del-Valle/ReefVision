param(
    [Parameter(Mandatory = $true)][string]$InstallerDirectory,
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$ExpectedFilename,
    [string]$SourceCommit,
    [switch]$RequireProvenance
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-ReefVisionMsiPayload {
    param([string]$Directory, [string]$ProductVersion)

    $msi = @(Get-ChildItem -LiteralPath $Directory -Filter '*.msi' -File)
    $cabs = @(Get-ChildItem -LiteralPath $Directory -Filter '*.cab' -File)
    if ($msi.Count -ne 1) { throw 'Expected exactly one MSI.' }
    if ($ExpectedFilename -and $msi[0].Name -cne $ExpectedFilename) {
        throw "Expected MSI filename $ExpectedFilename."
    }

    $installer = New-Object -ComObject WindowsInstaller.Installer
    $database = $installer.OpenDatabase($msi[0].FullName, 0)
    $identity = [ordered]@{}
    foreach ($name in @('ProductVersion', 'ProductCode', 'UpgradeCode')) {
        $query = 'SELECT `Value` FROM `Property` WHERE `Property`=''{0}''' -f $name
        $view = $database.OpenView($query)
        $null = $view.Execute()
        $record = $view.Fetch()
        if ($null -eq $record) { throw "MSI has no $name." }
        $identity[$name] = [string]$record.StringData(1)
        $null = $view.Close()
    }
    if ($identity.ProductVersion -ne $ProductVersion) { throw "Unexpected MSI ProductVersion: $($identity.ProductVersion)." }
    foreach ($name in @('ProductCode', 'UpgradeCode')) {
        $guid = [guid]::Empty
        if (-not [guid]::TryParseExact($identity[$name], 'B', [ref]$guid) -or $guid -eq [guid]::Empty) {
            throw "Invalid MSI ${name}: $($identity[$name])."
        }
    }

    $view = $database.OpenView('SELECT `DiskId`, `Cabinet` FROM `Media` ORDER BY `DiskId`')
    $null = $view.Execute()
    $media = @(while ($record = $view.Fetch()) {
        $cabinet = [string]$record.StringData(2)
        if ($cabinet -and $cabinet -notmatch '^#?[a-z0-9_.-]+\.cab$') {
            throw "Unsafe MSI cabinet name: $cabinet."
        }
        [ordered]@{
            disk_id = [int]$record.IntegerData(1)
            cabinet = $cabinet
            embedded = $cabinet.StartsWith('#')
        }
    })
    $null = $view.Close()
    if (-not @($media | Where-Object { $_.cabinet }).Count) { throw 'MSI declares no cabinets.' }
    $external = @($media | Where-Object { $_.cabinet -and -not $_.embedded } | ForEach-Object { $_.cabinet })
    if ($external.Count -ne $cabs.Count -or @($external | Sort-Object -Unique).Count -ne $external.Count) {
        throw 'MSI external cabinet count does not match the payload.'
    }
    foreach ($name in $external) {
        if ($name -notin $cabs.Name) { throw "Missing external cabinet: $name." }
    }
    $files = @(foreach ($item in ($msi + @($cabs | Sort-Object Name))) {
        if ($item.Length -le 0) { throw "Empty installer file: $($item.Name)." }
        [ordered]@{
            name = $item.Name
            size_bytes = $item.Length
            sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    })
    [ordered]@{ identity = $identity; media = $media; files = $files }
}

$payload = Get-ReefVisionMsiPayload -Directory $InstallerDirectory -ProductVersion $Version
if ($RequireProvenance) {
    $manifest = Get-Content -LiteralPath (Join-Path $InstallerDirectory 'build-provenance.json') -Raw | ConvertFrom-Json
    if ($manifest.version -ne $Version -or $manifest.source_commit -ne $SourceCommit -or
        $manifest.source_tree_clean -ne $true -or $manifest.msi_verified -ne $true) {
        throw 'Installer provenance does not identify the requested verified source.'
    }
    $expected = [ordered]@{
        identity = $manifest.msi.identity
        media = $manifest.msi.media
        files = $manifest.files
    }
    if (($payload | ConvertTo-Json -Depth 8 -Compress) -cne ($expected | ConvertTo-Json -Depth 8 -Compress)) {
        throw 'Installer identity, Media table, or file digests differ from build provenance.'
    }
}
$payload
