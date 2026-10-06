param(
    [switch]$RunFullFrontend
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Web = Join-Path $Repo "apps\web"
$ExpectedBranch = "feat/scientist-ready-phase12-ui-redesign-20261005"

Set-Location $Repo

$Branch = (git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $Branch -ne $ExpectedBranch) {
    throw "Phase 12 acceptance must run on $ExpectedBranch (found: $Branch)"
}

if (git status --porcelain) {
    git status --short
    throw "Phase 12 acceptance requires a clean worktree."
}

Write-Host ""
Write-Host "======================================================================"
Write-Host " REEFVISION SCIENTIST-READY PHASE 12"
Write-Host " SCIENTIST WORKSPACE UI REDESIGN"
Write-Host "======================================================================"
Write-Host ""
Write-Host "Branch: $Branch"
$Head = (git rev-parse HEAD).Trim()
Write-Host "Commit: $Head"

Push-Location $Web
try {
    Write-Host ""
    Write-Host "=== TYPECHECK ==="
    npm run typecheck
    if ($LASTEXITCODE -ne 0) {
        throw "Phase 12 TypeScript validation failed."
    }

    Write-Host ""
    Write-Host "=== FORMAT CHECK ==="
    npm run format:check
    if ($LASTEXITCODE -ne 0) {
        throw "Phase 12 frontend formatting failed."
    }

    Write-Host ""
    Write-Host "=== PHASE 12 FOCUSED TESTS ==="
    npm test -- src/components/layout/ProjectLauncher.test.tsx src/components/layout/workspacePresets.test.ts src/components/layout/ScientistWorkspaceInspector.test.tsx src/components/layout/ProjectInferenceInspector.test.tsx src/components/layout/ProjectMorphometricsInspector.test.tsx src/features/gallery/Gallery.test.tsx src/features/annotation-editor/EnhancedAnnotationEditor.test.tsx src/features/annotation-editor/MaskMeasurementPanel.test.tsx src/App.test.tsx
    if ($LASTEXITCODE -ne 0) {
        throw "Phase 12 focused UI tests failed."
    }

    if ($RunFullFrontend) {
        Write-Host ""
        Write-Host "=== FULL FRONTEND TEST SUITE ==="
        npm test
        if ($LASTEXITCODE -ne 0) {
            throw "Phase 12 full frontend suite failed."
        }

        Write-Host ""
        Write-Host "=== PRODUCTION BUILD ==="
        npm run build
        if ($LASTEXITCODE -ne 0) {
            throw "Phase 12 production frontend build failed."
        }
    }
}
finally {
    Pop-Location
}

git diff --check
if ($LASTEXITCODE -ne 0) {
    throw "Phase 12 git diff --check failed."
}

Write-Host ""
Write-Host "Phase 12 automated checks passed."
Write-Host ""
Write-Host "Current visual acceptance targets:"
Write-Host "[ ] Home launcher presents recent/pinned projects and quick starts cleanly."
Write-Host "[ ] Project opens into persistent left rail + central stage + right inspector."
Write-Host "[ ] Image workspace presents a dominant viewer and bottom filmstrip."
Write-Host "[ ] Workspace presets navigate existing canonical feature components."
Write-Host "[ ] Panel visibility persists without changing scientific project state."
Write-Host "[ ] Review preset makes the scientist-verification boundary visually explicit."
Write-Host "[ ] Inspector content changes with workspace context without duplicating scientific state."
Write-Host "[ ] Detection/annotation inspector exposes canonical batch model controls and provisional-output status."
Write-Host "[ ] Morphometrics inspector exposes reviewed calibration, Scale Assistant, measurement exports, and direct mask-workspace entry."
