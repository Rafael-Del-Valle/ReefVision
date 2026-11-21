param(
    [Parameter(Mandatory)][string]$RepositoryRoot,
    [Parameter(Mandatory)][long]$RunId,
    [Parameter(Mandatory)][ValidatePattern('^[a-f0-9]{40}$')][string]$SourceCommit,
    [Parameter(Mandatory)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version,
    [Parameter(Mandatory)][string]$Root
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = 'Rafael-Del-Valle/ReefVision'
if ($env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_ENVIRONMENT -cne 'github-hosted' -or
    $env:RUNNER_OS -cne 'Windows' -or $env:GITHUB_REPOSITORY -cne $repo -or
    $env:GITHUB_WORKFLOW -cne 'Windows Original Storage Recovery Proof' -or
    $Root -ine "${env:SystemDrive}/rv-storage-proof-$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT") {
    throw 'Original MSI staging requires the dedicated fresh GitHub-hosted proof workflow.'
}
if (Test-Path -LiteralPath $Root) { throw 'The staging directory already exists.' }
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

$payload = Join-Path $Root 'payload'
$evidence = Join-Path $Root 'evidence'
New-Item -ItemType Directory -Path $payload,$evidence | Out-Null
$seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$transport = @(for ($index = 0; $index -lt $parts.Count; $index++) {
    $part = $parts[$index]
    if ($part.name -cne "${prefix}$($index + 1)" -or $part.expired -or $part.workflow_run.id -ne $RunId -or
        $part.workflow_run.head_sha -cne $SourceCommit -or $part.digest -cnotmatch '^sha256:[a-f0-9]{64}$') {
        throw "Invalid original transport metadata for $($part.name)."
    }
    $zip = Join-Path $Root "part-$($index + 1).zip"
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
$verified | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $evidence 'verified-payload.json')
[ordered]@{
    source_commit=$SourceCommit; build_run_id=$RunId; build_job_id=$build[0].databaseId; build_run_url=$run.url
    version=$Version; original_msi_sha256=($verified.files | Where-Object name -eq $msi).sha256; parts=$transport
} | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $evidence 'verified-transport.json')
