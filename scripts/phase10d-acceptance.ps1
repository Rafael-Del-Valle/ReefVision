param(
    [switch]$RunFullFrontend
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Web = Join-Path $Repo "apps\web"
$ExpectedBranch = "feat/scientist-ready-phase10d-node-builder-20261004"

Set-Location $Repo

$Branch = (git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $Branch -ne $ExpectedBranch) {
    throw "Phase 10D acceptance must run on $ExpectedBranch (found: $Branch)"
}

Write-Host "Phase 10D Node Builder UI acceptance"
Write-Host "Branch: $Branch"

Push-Location $Web
try {
    Write-Host ""
    Write-Host "=== TYPECHECK ==="
    npm run typecheck
    if ($LASTEXITCODE -ne 0) {
        throw "Phase 10D TypeScript validation failed."
    }

    Write-Host ""
    Write-Host "=== FOCUSED NODE BUILDER TESTS ==="
    npm test -- src/features/workflow-graphs/WorkflowVisualEditor.test.tsx src/features/workflow-graphs/workflowTemplates.test.ts
    if ($LASTEXITCODE -ne 0) {
        throw "Phase 10D focused node builder tests failed."
    }

    if ($RunFullFrontend) {
        Write-Host ""
        Write-Host "=== FULL FRONTEND TEST SUITE ==="
        npm test
        if ($LASTEXITCODE -ne 0) {
            throw "Full frontend test suite failed."
        }

        Write-Host ""
        Write-Host "=== PRODUCTION BUILD ==="
        npm run build
        if ($LASTEXITCODE -ne 0) {
            throw "Production frontend build failed."
        }
    }
}
finally {
    Pop-Location
}

git diff --check
if ($LASTEXITCODE -ne 0) {
    throw "git diff --check failed."
}

Write-Host ""
Write-Host "Phase 10D automated checks passed."
Write-Host ""
Write-Host "Scientist UI checks:"
Write-Host "[ ] Pose Active Learning -> retrain template loads visually."
Write-Host "[ ] Human-review nodes are visually distinct from automated nodes."
Write-Host "[ ] Waiting-for-review run state appears directly on the node."
Write-Host "[ ] Dashed next-iteration cue is visible and is not an execution edge."
Write-Host "[ ] Primitive node parameters can be edited without raw JSON."
Write-Host "[ ] Advanced JSON remains available for nested settings."
Write-Host "[ ] Terminal provenance SHA and manifest are inspectable."
Write-Host "[ ] Saved revisions reopen with node positions and metadata intact."
