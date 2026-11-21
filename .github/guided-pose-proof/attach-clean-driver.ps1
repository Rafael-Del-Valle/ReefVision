param(
    [Parameter(Mandatory)][string]$RepositoryRoot,
    [Parameter(Mandatory)][ValidatePattern('^[a-f0-9]{40}$')][string]$SourceCommit,
    [Parameter(Mandatory)][ValidatePattern('^[a-f0-9]{40}$')][string]$ExpectedDriverBlob
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$checkout = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$files = @(git -C $checkout status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0 -or $files.Count -gt 0 -or (git -C $checkout rev-parse HEAD).Trim() -cne $SourceCommit) {
    throw 'The clean driver must be attached to a pristine checkout of the exact manufactured source.'
}
$relative = 'scripts/acceptance-windows-clean-install.ps1'
$driver = Join-Path $checkout $relative
if ((git -C $checkout rev-parse "HEAD:$relative").Trim() -cne $ExpectedDriverBlob) {
    throw 'The exact clean acceptance driver is required before attaching the guided proof.'
}
$content = [IO.File]::ReadAllText($driver).Replace("`r`n", "`n")
$hook = @'
                try {
                    if (-not $HostedStandardUserWebView2 -or -not $ordinaryUser -or -not $env:RV_GUIDED_PROOF_DRIVER) {
                        throw 'Guided pose proof requires the independently verified hosted standard user.'
                    }
                    $guided = @{
                        RepositoryRoot=$RepositoryRoot; Profile=$SpatialDataRoot; ProfileMarker=$Token; EvidenceRoot=$EvidenceRoot
                        NodePath=$SpatialWorkflowNodePath; PythonPath=$env:RV_GUIDED_PROOF_PYTHON; BackendExecutable=$installedSidecarPath
                        BackendPort=$spatialPort; DesktopProcessId=$spatialDesktop.Id; DebugPort=$debugPort
                        BrowserSid=$browserSid; BrowserArtifactsDirectory=$browserArtifacts
                        Version=$ProductVersion; Revision=$ExpectedSchemaRevision; SourceCommit=$env:SOURCE_COMMIT
                        InstallerSha256=$InstallerHash.ToLowerInvariant()
                    }
                    & $env:RV_GUIDED_PROOF_DRIVER @guided
                    $report.guided_pose_workflow = New-ReefVisionEvidenceResult -Status 'PASS' -Detail 'Standard-user installed WebView2 completed two saved pose runs, four actual review gates and checksum-verified downloads.'
                } catch {
                    $report.guided_pose_workflow = New-ReefVisionEvidenceResult -Status 'FAIL' -Detail $_.Exception.Message
                }
'@
$anchor = '                $spatialResult = Invoke-ReefVisionSpatialWebView2Acceptance '
if ([regex]::Matches($content, [regex]::Escape($anchor)).Count -ne 1) {
    throw 'The installed standard-user driver hook is ambiguous.'
}
$content = $content.Replace($anchor, $hook + "`n" + $anchor)
[IO.File]::WriteAllText($driver, $content, [Text.UTF8Encoding]::new($false))
$changes = @(git -C $checkout diff --name-only)
if ($LASTEXITCODE -ne 0 -or $changes.Count -ne 1 -or $changes[0] -cne $relative) {
    throw 'The proof checkout may change only the scoped clean acceptance driver.'
}
$parseErrors = $null
$null = [Management.Automation.Language.Parser]::ParseFile($driver, [ref]$null, [ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw 'The attached clean acceptance driver does not parse.' }
[ordered]@{
    changed_path=$relative; original_driver_git_blob=$ExpectedDriverBlob
    attached_driver_sha256=(Get-FileHash -LiteralPath $driver -Algorithm SHA256).Hash.ToLowerInvariant()
}
