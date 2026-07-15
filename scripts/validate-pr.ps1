[CmdletBinding()]
param(
    [switch]$InstallDependencies,
    [switch]$SkipE2E,
    [switch]$SkipDesktop,
    [switch]$BuildDesktop
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$webRoot = Join-Path $repoRoot "apps/web"
$cargoManifest = Join-Path $webRoot "src-tauri/Cargo.toml"
$validationRoot = Join-Path ([System.IO.Path]::GetTempPath()) "reefvision-validation-$PID"
$buildRoot = Join-Path $validationRoot "python-dist"
$previousDataDir = $env:REEFVISION_DATA_DIR

function Assert-Command {
    param([Parameter(Mandatory = $true)][string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found on PATH."
    }
}

function Invoke-ValidationStep {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    Write-Host ""
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE."
    }
}

try {
    Assert-Command "python"
    Assert-Command "npm"
    if (-not $SkipDesktop) {
        Assert-Command "cargo"
    }

    New-Item -ItemType Directory -Path $validationRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
    $env:REEFVISION_DATA_DIR = Join-Path $validationRoot "data"

    Set-Location $repoRoot

    if ($InstallDependencies) {
        Invoke-ValidationStep "Upgrade pip" {
            python -m pip install --upgrade pip
        }
        Invoke-ValidationStep "Install ReefVision backend development dependencies" {
            python -m pip install -e ".[dev]"
        }
    }

    Invoke-ValidationStep "Backend Ruff lint" {
        python -m ruff check apps/api
    }
    Invoke-ValidationStep "Backend Ruff formatting" {
        python -m ruff format --check apps/api
    }
    Invoke-ValidationStep "Backend mypy" {
        python -m mypy apps/api/reefvision
    }
    Invoke-ValidationStep "Backend pytest" {
        python -m pytest apps/api/reefvision/tests
    }
    Invoke-ValidationStep "Alembic upgrade to head" {
        python -m alembic -c apps/api/alembic.ini upgrade head
    }
    Invoke-ValidationStep "Alembic downgrade to base" {
        python -m alembic -c apps/api/alembic.ini downgrade base
    }
    Invoke-ValidationStep "Build Python package" {
        python -m build --outdir $buildRoot
    }

    Push-Location $webRoot
    try {
        Invoke-ValidationStep "Frontend lockfile consistency" {
            npm run lockfile:check
        }
        if ($InstallDependencies) {
            Invoke-ValidationStep "Install frontend dependencies" {
                npm ci
            }
        }
        elseif (-not (Test-Path (Join-Path $webRoot "node_modules"))) {
            throw "apps/web/node_modules is missing. Re-run with -InstallDependencies."
        }

        Invoke-ValidationStep "Frontend Prettier" {
            npm run format:check
        }
        Invoke-ValidationStep "Frontend TypeScript" {
            npm run typecheck
        }
        Invoke-ValidationStep "Frontend Vitest" {
            npm run test
        }

        if (-not $SkipE2E) {
            Invoke-ValidationStep "Install Playwright Chromium" {
                npx playwright install chromium
            }
            Invoke-ValidationStep "Frontend Playwright" {
                npm run test:e2e
            }
        }
        else {
            Invoke-ValidationStep "Frontend production build" {
                npm run build
            }
        }

        if (-not $SkipDesktop) {
            Invoke-ValidationStep "Rust formatting" {
                cargo fmt --manifest-path $cargoManifest -- --check
            }
            Invoke-ValidationStep "Rust Clippy" {
                cargo clippy --manifest-path $cargoManifest --all-targets --all-features -- -D warnings
            }
            Invoke-ValidationStep "Rust tests" {
                cargo test --manifest-path $cargoManifest --all-features
            }

            if ($BuildDesktop) {
                Invoke-ValidationStep "Tauri desktop build" {
                    npm run desktop:build
                }
            }
        }
    }
    finally {
        Pop-Location
    }

    Write-Host ""
    Write-Host "All selected ReefVision validation gates passed." -ForegroundColor Green
}
finally {
    Set-Location $repoRoot
    if ($null -eq $previousDataDir) {
        Remove-Item Env:REEFVISION_DATA_DIR -ErrorAction SilentlyContinue
    }
    else {
        $env:REEFVISION_DATA_DIR = $previousDataDir
    }
    Remove-Item -Path $validationRoot -Recurse -Force -ErrorAction SilentlyContinue
}
