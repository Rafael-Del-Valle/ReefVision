# ReefVision Milestone 2.5 Completion Report

## Status

In progress. The desktop packaging workflow, sidecar launcher, and NSIS bundle configuration are in place, but Milestone 2.5 should not be marked complete until the NSIS installer builds successfully. The local frontend and backend validation suite largely passed, but a full local Tauri installer build was not completed in this environment because the Visual Studio MSVC C++ toolchain required by the Windows Rust target is still missing.

## Implemented desktop behavior

- Added a Tauri 2 desktop shell in `apps/web/src-tauri`.
- Added a desktop runtime bootstrap so the React app can discover a Tauri-provided local API base URL before rendering.
- Added a FastAPI desktop sidecar entrypoint that:
  - receives the desktop data directory at launch;
  - selects its own free `127.0.0.1` port dynamically;
  - runs Alembic migrations against that data directory; and
  - publishes its selected loopback port only after the FastAPI server reports readiness.
- Added PyInstaller-based backend sidecar packaging and target-triple naming for Tauri `externalBin`.
- Added NSIS-targeted Tauri configuration with offline WebView2 install mode.
- Added single-instance protection in the desktop shell to prevent competing launches on Windows.
- Added a retryable startup failure screen when the desktop backend does not become healthy in time.
- Added second-launch window focusing so an already-running ReefVision desktop instance is surfaced instead of leaving the user with a silent no-op.
- Added Windows PowerShell scripts for desktop development and installer builds.
- Added lockfile validation and public-registry normalization so `apps/web/package-lock.json` cannot silently retain inaccessible private-registry tarball URLs.
- Added fail-fast prerequisite checks for the Visual Studio MSVC linker toolchain.

## Main changed areas

- `apps/api/reefvision/desktop.py`
- `apps/api/reefvision/config.py`
- `apps/api/reefvision/tests/test_desktop.py`
- `apps/web/.prettierignore`
- `apps/web/src/startup.ts`
- `apps/web/src/startup.test.ts`
- `apps/web/src/runtime.ts`
- `apps/web/src-tauri/`
- `.github/workflows/ci.yml`
- `scripts/build-desktop-backend.ps1`
- `scripts/build-desktop.ps1`
- `scripts/dev-desktop.ps1`
- `scripts/lib/node-tools.ps1`
- `apps/web/package-lock.json`

## Verification

- Ruff lint: passed.
- Ruff format check: passed.
- mypy strict checking: passed.
- Backend pytest: 27 passed.
- Backend sidecar desktop tests: 5 passed.
- Frontend TypeScript check: passed.
- Frontend Vitest: previously passed before the latest startup-screen changes; rerun in this sandbox is blocked by local esbuild filesystem restrictions.
- Frontend Prettier check: passed.
- Vite production build: previously passed before the latest startup-screen changes; rerun in this sandbox is blocked by local esbuild filesystem restrictions.
- Playwright Chromium gallery workflow: previously passed before the latest startup-screen changes; rerun in this sandbox is blocked because it depends on the Vite build.
- PyInstaller desktop sidecar build: passed.
- `apps/web/package-lock.json` public-registry validation: passed.
- `cargo fmt --check`: passed, with a local rustfmt path-canonicalization warning in this environment.
- Desktop build entry script: confirmed to fail fast with a clear MSVC-toolchain prerequisite message on this machine.

## Manual verification

- Verified that the lockfile no longer contains the inaccessible Artifactory host and now resolves packages from `registry.npmjs.org`.
- Verified that tracked frontend files no longer hard-code a developer-specific Windows AppData path.
- Verified that frontend formatting ignores generated `apps/web/src-tauri/target` artifacts.
- Verified that the desktop startup error UI now includes an explicit retry action.
- Verified from the Windows shell code path that a second launch attempts to surface the existing ReefVision window instead of launching a competing instance.
- Verified that the PyInstaller sidecar rebuild still succeeds after the desktop runtime startup changes.
- Verified that the desktop build script checks for the required MSVC desktop linker before attempting a Tauri build.
- Verified that Playwright Chromium can be installed and the existing gallery workflow still succeeds after the runtime bootstrap changes.

## Known limitations

- A full local NSIS installer was not produced in this environment because the Visual Studio C++ toolchain that provides `link.exe` is missing.
- The Tauri desktop launcher itself was not executed end to end for the same reason.
- The frontend Vitest, Vite, and Playwright workflows could not be rerun after the latest startup-screen changes inside this managed sandbox because esbuild cannot traverse the restricted parent directories; the same workflows had already passed outside the sandbox immediately beforehand.
- The backend still runs as one FastAPI process with the existing in-process thumbnail worker; a separate packaged worker process is intentionally out of scope for Milestone 2.5.

## Specification deviations

- The original roadmap placed packaging later than Milestone 2, but this change intentionally introduces it as Milestone 2.5 without pulling in Milestone 3 annotation work.
