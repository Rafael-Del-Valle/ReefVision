# ReefVision Windows Setup Fix

## Problem

The original `scripts/bootstrap.ps1` created the Python environment and installed Python dependencies before checking whether Node.js and npm were available. On computers without npm in PATH, setup failed late with an unhandled command-not-found error.

## Resolution

- Added shared Node.js/npm discovery in `scripts/lib/node-tools.ps1`.
- Moved Node.js/npm validation to the beginning of first-time setup.
- Added guided installation of the current Node.js LTS package through Windows Package Manager (`winget`).
- Refreshed the running PowerShell process PATH after installation.
- Added fallback discovery for standard machine-level and user-level Node.js installation paths.
- Preferred `npm.cmd` on Windows to avoid PowerShell execution-policy blocking of `npm.ps1`.
- Added minimum version checks for Node.js 22 and npm 10.
- Switched lockfile-based setup to deterministic `npm ci`.
- Added visible setup stages and a warning that npm may be quiet while creating many files.
- Added double-click launchers:
  - `setup.bat`
  - `start-reefvision.bat`
  - `check-reefvision.bat`
- Updated web startup, build, and test scripts to use the shared npm resolver.

## Verification

- Backend Ruff lint: passed.
- Backend Ruff formatting: passed.
- Backend strict mypy: passed.
- Backend pytest: 21 passed.
- Frontend Prettier: passed.
- Frontend TypeScript checking: passed.
- Frontend Vitest: 6 passed.
- Frontend production build: passed.
- `npm ci --ignore-scripts --no-audit --no-fund`: passed.
- JSON manifests: valid.
- PowerShell static delimiter checks: passed.

The Windows-specific `winget` installation branch requires a Windows machine for an end-to-end execution test. The command and package ID follow the documented WinGet syntax and the Microsoft WinGet package manifest for `OpenJS.NodeJS.LTS`.
