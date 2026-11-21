param(
    [Parameter(Mandatory)][string]$RepositoryRoot,
    [Parameter(Mandatory)][long]$RunId,
    [Parameter(Mandatory)][ValidatePattern('^[a-f0-9]{40}$')][string]$SourceCommit,
    [Parameter(Mandatory)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version,
    [Parameter(Mandatory)][string]$Root,
    [switch]$Previous
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = 'Rafael-Del-Valle/ReefVision'
if ($env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_ENVIRONMENT -cne 'github-hosted' -or
    $env:RUNNER_OS -cne 'Windows' -or $env:GITHUB_REPOSITORY -cne $repo -or
    $env:GITHUB_WORKFLOW -cne 'Windows Offline Original MSI Proof' -or
    $Root -ine "${env:SystemDrive}/rv-offline-$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT") {
    throw 'Original MSI staging requires the dedicated fresh GitHub-hosted proof workflow.'
}
if ($Previous) {
    if ($RunId -ne 44853957856 -or $SourceCommit -cne 'e3e8ffb6395c9f2675ffc10397c2401388e63ee8' -or $Version -cne '1.8.0' -or
        -not (Test-Path -LiteralPath (Join-Path $Root 'evidence/verified-transport.json') -PathType Leaf)) {
        throw 'The older payload must use the original qualified 1.8.0 run in a candidate staging root.'
    }
} elseif (Test-Path -LiteralPath $Root) { throw 'The staging directory already exists.' }
if ($PSVersionTable.PSVersion -lt [version]'7.4') { throw 'Transport requires binary-safe PowerShell redirection.' }
$source = (Resolve-Path -LiteralPath $RepositoryRoot).Path
if ((git -C $source rev-parse HEAD).Trim() -cne $SourceCommit) { throw 'The first-use source checkout is not pinned to the original build.' }

$deadline = [DateTimeOffset]::UtcNow.AddMinutes(40)
do {
    $run = gh run view $RunId --repo $repo --json databaseId,name,headSha,url,event,status,jobs | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $run.databaseId -ne $RunId -or $run.headSha -cne $SourceCommit -or
        $run.name -cne 'Build Windows Desktop Release Candidate' -or $run.event -cne 'pull_request') {
        throw 'The nominated run is not the exact original Windows build workflow.'
    }
    $build = @($run.jobs | Where-Object name -eq 'build-windows-installer')
    if ($build.Count -eq 1 -and $build[0].status -ceq 'completed') {
        if ($build[0].conclusion -cne 'success') { throw 'The original installer build job failed.' }
        break
    }
    if ($run.status -ceq 'completed' -or [DateTimeOffset]::UtcNow -ge $deadline) { throw 'The exact original installer build did not become available.' }
    Start-Sleep -Seconds 20
} while ($true)

$msi = "ReefVision_${Version}_x64_en-US.msi"
$prefix = "ReefVision-$Version-RC-Installer-Part-"
$partPattern = '^' + [regex]::Escape($prefix) + '[1-4]$'
$artifacts = gh api "repos/$repo/actions/runs/$RunId/artifacts?per_page=100" | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $artifacts.total_count -gt 100) { throw 'Could not unambiguously enumerate original build artifacts.' }
$parts = @($artifacts.artifacts | Where-Object name -match $partPattern | Sort-Object name)
if ($parts.Count -lt 1 -or $parts.Count -gt 4) { throw 'Unexpected number of original artifact parts.' }

$payload = Join-Path $Root $(if ($Previous) { 'payload-previous' } else { 'payload' })
$evidence = Join-Path $Root $(if ($Previous) { 'evidence/previous' } else { 'evidence' })
New-Item -ItemType Directory -Path $payload,$evidence | Out-Null
$seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$transport = @(for ($index = 0; $index -lt $parts.Count; $index++) {
    $part = $parts[$index]
    if ($part.name -cne "${prefix}$($index + 1)" -or $part.expired -or $part.workflow_run.id -ne $RunId -or
        $part.workflow_run.head_sha -cne $SourceCommit -or $part.digest -cnotmatch '^sha256:[a-f0-9]{64}$') {
        throw "Invalid original transport metadata for $($part.name)."
    }
    $zip = Join-Path $payload "part-$($index + 1).zip"
    gh api "repos/$repo/actions/artifacts/$($part.id)/zip" > $zip
    if ($LASTEXITCODE -ne 0 -or (Get-Item -LiteralPath $zip).Length -ne $part.size_in_bytes -or
        (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ine $part.digest.Substring(7)) {
        throw "Original transport integrity check failed for $($part.name)."
    }
    $archive = [IO.Compression.ZipFile]::OpenRead($zip)
    try {
        foreach ($entry in $archive.Entries) {
            if ($entry.FullName -cne $entry.Name -or
                ($entry.Name -cne $msi -and $entry.Name -cne 'build-provenance.json' -and $entry.Name -cnotmatch '^[a-z0-9_.-]+\.cab$') -or
                -not $seen.Add($entry.Name)) { throw "Unexpected or duplicate original member $($entry.FullName)." }
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $payload $entry.Name))
        }
    } finally { $archive.Dispose() }
    Remove-Item -LiteralPath $zip
    [ordered]@{id=$part.id; name=$part.name; size_bytes=$part.size_in_bytes; sha256=$part.digest.Substring(7)}
})

$verified = & (Join-Path $source 'scripts/verify-windows-installer-payload.ps1') -InstallerDirectory $payload -Version $Version `
    -ExpectedFilename $msi -SourceCommit $SourceCommit -RequireProvenance
$msiHash = ($verified.files | Where-Object name -CEQ $msi).sha256
if ($Previous -and ($build[0].databaseId -ne 136691608332 -or $transport.Count -ne 2 -or
    $msiHash -cne '78d52066848afc6aeac975765359ba13cd3d0e2e8b79ef1b90307eecd03c35ed' -or
    (Get-FileHash -LiteralPath (Join-Path $payload 'build-provenance.json') -Algorithm SHA256).Hash.ToLowerInvariant() -cne '5f9bf934e2fe442ec7c9da5817ddd7fe7bb03ad30035708429d8d1f70b1361f6' -or
    @($verified.media | Where-Object { $_.cabinet -and -not $_.embedded }).Count -ne 6)) {
    throw 'The cached 1.8 payload differs from the original qualified MSI, CABs or manufacturing proof.'
}
$verified | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $evidence 'verified-payload.json')
[ordered]@{
    source_commit=$SourceCommit; build_run_id=$RunId; build_job_id=$build[0].databaseId; build_run_url=$run.url
    version=$Version; original_msi_sha256=$msiHash; parts=$transport
} | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $evidence 'verified-transport.json')
