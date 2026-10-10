# ReefVision 1.0.1 -- formatting, full validation, and Windows MSI release build.
# Runs ONLY on the dedicated 1.0.1 branch. Never resets/discards local edits.
# A clean initial checkout is required. On success, safe formatting-only changes
# are committed/pushed, then the weight-free Windows installer is built.

param(
    [switch]$SkipInstaller,
    [switch]$SkipPlaywright
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Branch = "feat/reefvision-1.0.1-sam-class-review-import-20261010"
Set-Location $Root

function Invoke-Required {
    param([string]$Title, [scriptblock]$Action)
    Write-Host ""
    Write-Host "==> $Title" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Title failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path (Join-Path $Root ".git"))) {
    throw "Run this script from your ReefVision repository checkout."
}
$Dirty = @(git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "git status failed" }
if ($Dirty.Count -gt 0) {
    git status --short
    throw "Local uncommitted files exist. Save or commit them before running; the script never overwrites local edits."
}

Invoke-Required "Fetch the 1.0.1 development branch" {
    git fetch origin $Branch
}
$CurrentBranch = (git branch --show-current).Trim()
if ($CurrentBranch -ne $Branch) {
    $LocalBranch = @(git branch --list $Branch)
    if ($LocalBranch.Count -gt 0) {
        Invoke-Required "Switch to existing 1.0.1 branch" { git switch $Branch }
    }
    else {
        Invoke-Required "Create local tracking branch" {
            git switch --track -c $Branch "origin/$Branch"
        }
    }
}
Invoke-Required "Fast-forward to latest 1.0.1 changes" {
    git pull --ff-only origin $Branch
}
$CurrentBranch = (git branch --show-current).Trim()
if ($CurrentBranch -ne $Branch) { throw "Refusing to modify branch $CurrentBranch" }

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    Invoke-Required "Bootstrap missing environment" {
        & (Join-Path $Root "scripts\bootstrap.ps1") -NonInteractive -SkipPlaywrightBrowser
    }
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python virtual environment not found after bootstrap"
}

$LogDirectory = Join-Path $Root ".desktop"
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
$Log = Join-Path $LogDirectory "reefvision-1.0.1-validation.log"
Start-Transcript -Path $Log -Force | Out-Null
try {
    Invoke-Required "Install/confirm Python test dependencies" {
        & $Python -m pip install -e ".[dev]"
    }
    Invoke-Required "Install exact frontend dependencies" {
        & npm --prefix apps/web ci
    }
    Invoke-Required "Apply Python Ruff formatting" {
        & $Python -m ruff format apps/api
    }
    Invoke-Required "Apply Python Ruff automatic fixes" {
        & $Python -m ruff check apps/api --fix
    }
    Invoke-Required "Finalize Python Ruff formatting" {
        & $Python -m ruff format apps/api
    }
    Invoke-Required "Apply frontend Prettier formatting" {
        & npm --prefix apps/web run format
    }

    Invoke-Required "Check exact 1.0.1 version consistency" {
        & $Python scripts/check-release-version.py
    }
    Invoke-Required "Check Python lint" {
        & $Python -m ruff check apps/api
    }
    Invoke-Required "Check Python format" {
        & $Python -m ruff format --check apps/api
    }
    Invoke-Required "Check strict Python type safety" {
        & $Python -m mypy apps/api/reefvision
    }
    Invoke-Required "Run all backend tests" {
        & $Python -m pytest apps/api/reefvision/tests -q
    }
    Invoke-Required "Check frontend format" {
        & npm --prefix apps/web run format:check
    }
    Invoke-Required "Check frontend types" {
        & npm --prefix apps/web run typecheck
    }
    Invoke-Required "Run frontend unit tests" {
        & npm --prefix apps/web run test
    }
    if (-not $SkipPlaywright) {
        Invoke-Required "Install Chromium for E2E tests" {
            & npx --prefix apps/web playwright install chromium
        }
        Invoke-Required "Run frontend end-to-end tests" {
            & npm --prefix apps/web run test:e2e
        }
    }
    Invoke-Required "Build production frontend" {
        & npm --prefix apps/web run build
    }
    Invoke-Required "Verify the complete patch has no whitespace errors" {
        git diff --check
    }

    $FormattingDiff = @(git status --porcelain)
    if ($FormattingDiff.Count -gt 0) {
        Invoke-Required "Commit reproducible formatting corrections" {
            git add -u
            git commit -m "style(1.0.1): apply verified Ruff and Prettier formatting"
        }
        Invoke-Required "Publish validated source branch" {
            git push origin $Branch
        }
    }

    if (-not $SkipInstaller) {
        Invoke-Required "Build and verify Windows 1.0.1 MSI/CAB installer" {
            & (Join-Path $Root "scripts\build-desktop.ps1") -TargetTriple "x86_64-pc-windows-msvc"
        }
        $InstallerFolder = Join-Path $Root "apps\web\src-tauri\target\x86_64-pc-windows-msvc\release\bundle\msi"
        if (-not (Test-Path -LiteralPath (Join-Path $InstallerFolder "ReefVision_1.0.1_x64_en-US.msi"))) {
            throw "Build reported success but the expected 1.0.1 MSI was not found"
        }
        Write-Host "Installer folder: $InstallerFolder" -ForegroundColor Green
        Get-ChildItem $InstallerFolder -File | Select-Object Name, Length
    }
    Write-Host "1.0.1 SOURCE VALIDATION PASSED." -ForegroundColor Green
    Write-Host "Independent clean-PC installation remains required before public release."
}
catch {
    Write-Host "Validation/build failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Copy the last 80 log lines to ChatGPT:"
    Write-Host ('  Get-Content -LiteralPath "' + $Log + '" -Tail 80')
    throw
}
finally {
    Stop-Transcript | Out-Null
}
