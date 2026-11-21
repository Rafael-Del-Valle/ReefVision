function Get-OfflinePredecessor([string]$Root, [string]$PreviousSource) {
    $pin = '3e37524e28c4b7dde8ffbe203120d3b8e7fe2ee9'
    $msi = Join-Path $Root 'payload-previous/ReefVision_1.7.0_x64_en-US.msi'
    $prior = Join-Path $Root 'evidence/previous'
    $payload = Get-Content -LiteralPath (Join-Path $prior 'verified-payload.json') -Raw | ConvertFrom-Json
    $transport = Get-Content -LiteralPath (Join-Path $prior 'verified-transport.json') -Raw | ConvertFrom-Json
    $hash = (Get-FileHash -LiteralPath $msi -Algorithm SHA256).Hash.ToLowerInvariant()
    if ((git -C $PreviousSource rev-parse HEAD).Trim() -cne $pin -or $transport.source_commit -cne $pin -or
        $transport.build_run_id -ne 44827326113 -or $transport.build_job_id -ne 136603186182 -or
        $payload.identity.ProductVersion -cne '1.7.0' -or $transport.original_msi_sha256 -cne $hash -or
        $hash -cne '90faf157f5dc8489d64f31f92c9b105471e24621bc732d96b91132763ef290cc') {
        throw 'The selected exact qualified predecessor source or MSI differs.'
    }
    return [ordered]@{
        source_commit=$pin; msi=$msi; msi_sha256=$hash; product_code=$payload.identity.ProductCode
        version='1.7.0'; schema='b17_monitor_0003'; build_run_id=$transport.build_run_id; build_job_id=$transport.build_job_id
        shell_sha256='ff006cd2594983f8839211fecd28b1008647bde5117da70835d4ec812111cbf2'
        sidecar_sha256='82961858248b453b15b1903a6cb112b04b2e28dc330f7de2ee1e7ca658b68461'
    }
}

function Assert-OfflinePredecessorBinary($Prior, [string]$Shell, [string]$Sidecar) {
    Assert-ReefVisionLineageHash -Path $Shell -ExpectedSha256 $Prior.shell_sha256 -Label 'Exact prior shell'
    Assert-ReefVisionLineageHash -Path $Sidecar -ExpectedSha256 $Prior.sidecar_sha256 -Label 'Exact prior sidecar'
}

function Close-OfflineUpgradeDesktop($Account, $Desktop, [int]$Port, $Session, [string]$DataRoot) {
    $null = $Desktop.CloseMainWindow()
    if (-not $Desktop.WaitForExit(15000) -or -not $Account.launcher.WaitForExit(10000)) {
        throw 'The previous ordinary desktop and launcher did not close before transition.'
    }
    Wait-ReefVisionWebView2DebugClosure -Port $Port
    Wait-ReefVisionWebView2DebugClosure -Port $Session.api_port
    if (Get-Process -Id $Session.backend_pid -ErrorAction SilentlyContinue) { throw 'Previous packaged sidecar is still running.' }
    $runtimePort = Join-Path $DataRoot 'runtime/backend-port.txt'
    if (Test-Path -LiteralPath $runtimePort -PathType Leaf) { Remove-Item -LiteralPath $runtimePort }
}

function New-OfflinePreUpgradeBackup([string]$Api, [string]$Profile, [string]$Revision) {
    $response = New-ReefVisionAcceptanceBackup -Api $Api
    $job = Wait-ReefVisionAcceptanceJob -Api $Api -JobId $response.job.id -Operation 'Offline predecessor backup'
    $backup = $response.backup
    $verified = Invoke-RestMethod -Uri "$Api/backups/$($backup.id)/verify" -Method Post -NoProxy -TimeoutSec 60
    if ($verified.status -cne 'valid' -or -not $verified.completion_marker_present -or
        $verified.current_schema_revision -cne $Revision -or $verified.file_count -lt 2) {
        throw 'The previous live desktop did not create a valid recovery backup.'
    }
    $manifest = Resolve-ReefVisionLineageFile -Root $Profile -RelativePath $backup.manifest_path -Label 'Pre-upgrade backup manifest'
    Assert-ReefVisionLineageHash -Path $manifest -ExpectedSha256 $job.result_json.manifest_sha256 -Label 'Pre-upgrade backup manifest'
    return [ordered]@{
        id=$backup.id; job_id=$job.id; manifest_path=$backup.manifest_path; manifest_sha256=$job.result_json.manifest_sha256
        verified_files=$verified.file_count; verified_bytes=$verified.total_size_bytes; schema=$Revision
    }
}

function Restore-OfflinePreUpgradeBackup([string]$Api, [string]$Profile, $Backup) {
    $url = "$Api/backups/$($Backup.id)"
    $check = Invoke-RestMethod -Uri "$url/verify" -Method Post -NoProxy -TimeoutSec 60
    if ($check.status -cne 'valid' -or -not $check.completion_marker_present -or $check.current_schema_revision -cne $Backup.schema -or
        $check.file_count -ne $Backup.verified_files -or $check.total_size_bytes -ne $Backup.verified_bytes) {
        throw 'The upgraded desktop could not verify the exact earlier backup.'
    }
    $response = Invoke-RestMethod -Uri "$url/restore" -Method Post -ContentType 'application/json' `
        -Body '{"destination_name":"offline-return-to-17","overwrite_existing":false}' -NoProxy -TimeoutSec 60
    $job = Wait-ReefVisionAcceptanceJob -Api $Api -JobId $response.job.id -Operation 'Offline predecessor restore'
    if ($response.verification_status -cne 'valid' -or $response.destination_path -cne 'recoveries/offline-return-to-17' -or
        $job.result_json.restored_file_count -ne $check.file_count -or $job.result_json.restored_total_size_bytes -ne $check.total_size_bytes) {
        throw 'The offline restore did not publish the expected verified files.'
    }
    $manifest = Resolve-ReefVisionLineageFile -Root $Profile -RelativePath $Backup.manifest_path -Label 'Retained predecessor manifest'
    Assert-ReefVisionLineageHash -Path $manifest -ExpectedSha256 $Backup.manifest_sha256 -Label 'Retained predecessor manifest'
    $document = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
    $recovered = Join-Path $Profile $response.destination_path
    Assert-ReefVisionNoReparseAncestors -Path $recovered
    if ($document.backup_id -cne $Backup.id -or @($document.file_inventory).Count -ne $Backup.verified_files) {
        throw 'The restored manifest does not bind the verified previous record.'
    }
    foreach ($entry in $document.file_inventory) {
        if ($entry.path -ceq "database/$($document.database_filename)") { $key = $document.database_filename }
        elseif ($entry.path.StartsWith('data/')) { $key = $entry.path.Substring(5) }
        else { throw 'Unexpected backup member prefix.' }
        $file = Resolve-ReefVisionLineageFile -Root $recovered -RelativePath $key -Label 'Offline recovered member'
        if ((Get-Item -LiteralPath $file).Length -ne $entry.size_bytes) { throw 'Recovered member length differs.' }
        Assert-ReefVisionLineageHash -Path $file -ExpectedSha256 $entry.sha256 -Label 'Offline recovered member'
    }
    return [ordered]@{
        destination_path=$response.destination_path; path=$recovered; restore_job_id=$job.id
        files_rehashed=$Backup.verified_files; bytes_rehashed=$Backup.verified_bytes
        recovered_db_sha256=(Get-FileHash -LiteralPath (Join-Path $recovered $document.database_filename) -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
