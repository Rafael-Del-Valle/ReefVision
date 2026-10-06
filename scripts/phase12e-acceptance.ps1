$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Web = Join-Path $Repo "apps\web"
$Tauri = Join-Path $Web "src-tauri"

$ExpectedBranch =
    "feat/scientist-ready-phase12-ui-redesign-20261005"

$RequiredBaseline =
    "4b42146a490186b66fd7199408c499d5b37c07d8"

Set-Location $Repo

$Branch = (git branch --show-current).Trim()

if (
    $LASTEXITCODE -ne 0 -or
    $Branch -ne $ExpectedBranch
) {
    throw (
        "Phase 12E acceptance must run on " +
        "$ExpectedBranch (found: $Branch)"
    )
}

$Head = (git rev-parse HEAD).Trim()

git merge-base --is-ancestor `
    $RequiredBaseline `
    $Head

if ($LASTEXITCODE -ne 0) {
    throw (
        "Phase 12E source does not contain " +
        "the validated Phase 12D baseline."
    )
}

if (git status --porcelain) {
    git status --short

    throw (
        "Phase 12E acceptance requires a " +
        "clean committed source tree."
    )
}

$Stamp =
    [DateTime]::UtcNow.ToString(
        "yyyyMMddTHHmmssZ"
    )

$EvidenceRoot =
    Join-Path `
        $Repo `
        ".artifacts\phase12e-$Stamp"

$SummaryPath =
    Join-Path `
        $EvidenceRoot `
        "summary.json"

New-Item `
    -ItemType Directory `
    -Path $EvidenceRoot `
    -Force |
    Out-Null

$Summary = [ordered]@{
    schema_version =
        "reefvision-phase12e-acceptance-0001"

    started_at_utc =
        [DateTime]::UtcNow.ToString("o")

    completed_at_utc = $null

    branch = $Branch
    source_commit = $Head

    automated_status = "RUNNING"

    gates = [ordered]@{}

    installer = $null

    manual_visual_acceptance =
        "PENDING"

    failure_reason = $null
}

function Save-Summary {
    $Json =
        $Summary |
        ConvertTo-Json -Depth 12

    $Encoding =
        New-Object `
            System.Text.UTF8Encoding `
            -ArgumentList $false

    [System.IO.File]::WriteAllText(
        $SummaryPath,
        $Json,
        $Encoding
    )
}

function Invoke-Gate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [scriptblock]$Action
    )

    Write-Host ""
    Write-Host "=== $Name ==="

    $Started = Get-Date

    try {
        & $Action

        if ($LASTEXITCODE -ne 0) {
            throw (
                "$Name failed with exit code " +
                "$LASTEXITCODE."
            )
        }

        $Summary.gates[$Name] =
            [ordered]@{
                status = "PASS"
                duration_seconds =
                    [math]::Round(
                        (
                            (Get-Date) -
                            $Started
                        ).TotalSeconds,
                        3
                    )
            }

        Save-Summary
    }
    catch {
        $Summary.gates[$Name] =
            [ordered]@{
                status = "FAIL"
                duration_seconds =
                    [math]::Round(
                        (
                            (Get-Date) -
                            $Started
                        ).TotalSeconds,
                        3
                    )
                detail =
                    $_.Exception.Message
            }

        $Summary.failure_reason =
            "$Name`: $($_.Exception.Message)"

        $Summary.automated_status =
            "FAIL"

        $Summary.completed_at_utc =
            [DateTime]::UtcNow.ToString("o")

        Save-Summary

        throw
    }
}

Save-Summary

Write-Host ""
Write-Host "======================================================================"
Write-Host " REEFVISION SCIENTIST-READY PHASE 12E"
Write-Host " FINAL UI + RELEASE-CANDIDATE ACCEPTANCE"
Write-Host "======================================================================"
Write-Host ""
Write-Host "Branch:  $Branch"
Write-Host "Commit:  $Head"
Write-Host "Evidence: $EvidenceRoot"

Invoke-Gate `
    -Name "phase12_full_frontend" `
    -Action {
        & powershell.exe `
            -NoLogo `
            -NoProfile `
            -ExecutionPolicy Bypass `
            -File (
                Join-Path `
                    $Repo `
                    "scripts\phase12-acceptance.ps1"
            ) `
            -RunFullFrontend
    }

Invoke-Gate `
    -Name "phase12_browser_e2e" `
    -Action {
        Push-Location $Web

        try {
            npm run test:e2e
        }
        finally {
            Pop-Location
        }
    }

Invoke-Gate `
    -Name "node_builder_final_regression" `
    -Action {
        Push-Location $Web

        try {
            npm test -- `
                src/features/workflow-graphs/WorkflowVisualEditor.test.tsx `
                src/features/workflow-graphs/workflowTemplates.test.ts
        }
        finally {
            Pop-Location
        }
    }

Invoke-Gate `
    -Name "tauri_rust_final" `
    -Action {
        Push-Location $Tauri

        try {
            cargo fmt --check

            if ($LASTEXITCODE -ne 0) {
                throw "cargo fmt --check failed."
            }

            cargo test
        }
        finally {
            Pop-Location
        }
    }

Invoke-Gate `
    -Name "production_msi_build_and_verification" `
    -Action {
        & powershell.exe `
            -NoLogo `
            -NoProfile `
            -ExecutionPolicy Bypass `
            -File (
                Join-Path `
                    $Repo `
                    "scripts\build-desktop.ps1"
            )

        if ($LASTEXITCODE -ne 0) {
            throw (
                "build-desktop.ps1 failed."
            )
        }
    }

$InstallerDirectory =
    Join-Path `
        $Repo `
        "apps\web\src-tauri\target\x86_64-pc-windows-msvc\release\bundle\msi"

$MsiFiles = @(
    Get-ChildItem `
        -LiteralPath $InstallerDirectory `
        -Filter "*.msi" `
        -File
)

if ($MsiFiles.Count -ne 1) {
    throw (
        "Expected exactly one Phase 12E MSI; " +
        "found $($MsiFiles.Count)."
    )
}

$Msi = $MsiFiles[0]

$ProvenancePath =
    Join-Path `
        $InstallerDirectory `
        "build-provenance.json"

if (
    -not (
        Test-Path `
            -LiteralPath $ProvenancePath `
            -PathType Leaf
    )
) {
    throw (
        "Phase 12E MSI is missing " +
        "build-provenance.json."
    )
}

$Provenance =
    Get-Content `
        -LiteralPath $ProvenancePath `
        -Raw |
    ConvertFrom-Json

if (
    [string]$Provenance.source_commit -ne
    $Head
) {
    throw (
        "MSI source commit does not match " +
        "Phase 12E HEAD."
    )
}

if (
    -not [bool]$Provenance.source_tree_clean
) {
    throw (
        "MSI provenance reports a dirty " +
        "source tree."
    )
}

if (
    -not [bool]$Provenance.msi_verified
) {
    throw (
        "MSI package verification did not pass."
    )
}

$Summary.installer =
    [ordered]@{
        path = $Msi.FullName
        size_bytes = $Msi.Length
        sha256 = (
            Get-FileHash `
                -LiteralPath $Msi.FullName `
                -Algorithm SHA256
        ).Hash.ToLowerInvariant()

        provenance =
            $ProvenancePath

        source_commit =
            [string]$Provenance.source_commit

        msi_verified = $true
    }

Save-Summary

Invoke-Gate `
    -Name "clean_install_safety_plan" `
    -Action {
        $PlanRoot =
            Join-Path `
                $env:SystemDrive `
                "reefvision-phase12e-disposable-plan"

        & powershell.exe `
            -NoLogo `
            -NoProfile `
            -ExecutionPolicy Bypass `
            -File (
                Join-Path `
                    $Repo `
                    "scripts\acceptance-windows-clean-install.ps1"
            ) `
            -InstallerPath $Msi.FullName `
            -AcceptanceRoot $PlanRoot `
            -PlanOnly

        if ($LASTEXITCODE -ne 0) {
            throw (
                "Clean-install safety-plan " +
                "validation failed."
            )
        }
    }

if (git status --porcelain) {
    git status --short

    throw (
        "Phase 12E acceptance changed " +
        "tracked source files."
    )
}

git diff --check

if ($LASTEXITCODE -ne 0) {
    throw (
        "Phase 12E git diff --check failed."
    )
}

$Summary.automated_status = "PASS"
$Summary.completed_at_utc =
    [DateTime]::UtcNow.ToString("o")

Save-Summary

Write-Host ""
Write-Host "======================================================================"
Write-Host " PHASE 12E AUTOMATED RELEASE-CANDIDATE GATE PASSED"
Write-Host "======================================================================"
Write-Host ""
Write-Host "Source commit:"
Write-Host "  $Head"
Write-Host ""
Write-Host "Evidence:"
Write-Host "  $SummaryPath"
Write-Host ""
Write-Host "Verified MSI:"
Write-Host "  $($Msi.FullName)"
Write-Host ""
Write-Host "MSI SHA-256:"
Write-Host "  $($Summary.installer.sha256)"
Write-Host ""
Write-Host "Automated gates:"
Write-Host "  [x] Phase 12 focused UI tests"
Write-Host "  [x] Full frontend regression"
Write-Host "  [x] Production frontend build"
Write-Host "  [x] Full Playwright browser E2E"
Write-Host "  [x] Keyboard skip navigation"
Write-Host "  [x] 1200x760 desktop sizing"
Write-Host "  [x] 1440x960 desktop sizing"
Write-Host "  [x] Horizontal overflow checks"
Write-Host "  [x] Async-state accessibility"
Write-Host "  [x] Detached-panel rerender stability"
Write-Host "  [x] Node Builder automated regression"
Write-Host "  [x] Tauri Rust tests"
Write-Host "  [x] MSI build"
Write-Host "  [x] MSI administrative verification"
Write-Host "  [x] Packaged backend self-test"
Write-Host "  [x] Clean-install safety plan"
Write-Host ""
Write-Host "Manual visual/native acceptance is still intentionally PENDING:"
Write-Host "  [ ] Home launcher visual inspection"
Write-Host "  [ ] 1440 desktop three-column workbench"
Write-Host "  [ ] 1200 desktop inspector overlay"
Write-Host "  [ ] Review Mode truth boundary"
Write-Host "  [ ] Detection/inference inspector"
Write-Host "  [ ] Morphometrics + Scale Assistant"
Write-Host "  [ ] Training monitor"
Write-Host "  [ ] Review Queue inspector"
Write-Host "  [ ] Video timeline + pose controls"
Write-Host "  [ ] Native inspector detach/dock"
Write-Host "  [ ] Multi-monitor geometry restoration"
Write-Host "  [ ] Node Builder human-review visual states"
Write-Host "  [ ] Node Builder dashed next-iteration cue"
Write-Host "  [ ] Node parameter editing"
Write-Host "  [ ] Node provenance inspection"
Write-Host ""
Write-Host "These visual checks must not be silently marked PASS."