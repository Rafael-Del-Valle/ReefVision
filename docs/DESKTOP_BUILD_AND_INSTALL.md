# Desktop Build and Installation

## Scope

This guide covers the current ReefVision desktop shell, sidecar build, MSI packaging path, verification, and common Windows-specific build pitfalls.

## Prerequisites

Development and packaging require:

- Python 3.12.x with the ReefVision pinned dependencies installed;
- the pinned Windows provider stack, including `opencv-contrib-python` for the Scale Assistant ArUco/ChArUco runtime;
- Node.js and npm;
- a Rust toolchain;
- Visual Studio 2022 build tools with the MSVC C++ toolchain and Windows SDK.

End users of the finished installer do not need the development toolchain.

Run the supported bootstrap rather than installing provider packages independently:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

When the pinned provider requirements use OpenCV contrib, bootstrap removes conflicting base/headless OpenCV distributions before installation and verifies that the resulting `cv2` runtime exposes `aruco`. This is important because the base and contrib OpenCV wheels share the same `cv2` namespace and should not be installed together in the ReefVision environment.

## Development shell

Use the desktop development workflow when validating the shell against the live repository:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-desktop.ps1
```

This starts the Vite frontend in Tauri, launches the FastAPI backend from `.venv`, and waits for sidecar readiness before rendering the application UI.

The development script sets `REEFVISION_DESKTOP_DATA_DIR` to `.desktop/dev-data` in the repository so desktop development can still start when the platform app-data directory is unavailable or blocked in a restricted environment.

## Production build

Build the packaged app and MSI installer with:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-desktop.ps1
```

The build script:

- checks the public npm lockfile policy;
- verifies the source `.venv` has the pinned providers and the Scale Assistant `cv2.aruco` runtime;
- builds the PyInstaller sidecar, collecting the `cv2` package and `opencv-contrib-python` metadata;
- stages the sidecar into `apps/web/src-tauri/binaries`;
- removes dependency test trees, bytecode, and development caches from the staged runtime;
- preserves the complete required CPU/GPU provider runtime and scientific resources;
- runs `tauri build --bundles msi`, using split external WiX cabinets when the release payload exceeds a single embedded cabinet; and
- verifies the MSI through administrative extraction and a packaged-backend self-test.

The packaged-backend self-test requires migrations, implemented model providers, OpenAPI construction, and `cv2.aruco`. A package that drops the contrib marker runtime must fail verification rather than silently shipping a disabled ArUco/ChArUco Scale Assistant.

## Installer location and checksum

After a successful Windows build, the expected installer directory is:

```text
apps/web/src-tauri/target/x86_64-pc-windows-msvc/release/bundle/msi/
```

Generate a SHA-256 checksum with:

```powershell
Get-FileHash `
  apps\web\src-tauri\target\x86_64-pc-windows-msvc\release\bundle\msi\*.msi `
  -Algorithm SHA256
```

Record the installer filename, version, and checksum in the milestone report or release notes.

## Upgrade testing

Before claiming upgrade safety:

1. Install the previous ReefVision desktop version.
2. Create or open a project using isolated test data.
3. Confirm projects, managed images, models, dataset versions, QC runs, and review queues exist.
4. Install the new MSI package over the old version.
5. Reopen the application and verify the same data is intact.

Never run upgrade or uninstall acceptance against a personal ReefVision installation or real user data. The installer should preserve user data because ReefVision stores active data in the Tauri per-user application-data directory rather than the installation directory.

Administrative extraction proves package readability, required-file presence, migration startup, and packaged-backend self-test behavior. It is not a substitute for clean-machine evidence. Before ReefVision 1.0 release, record a safe VM or disposable-machine test covering clean install, first launch, restart, upgrade over the previous release, uninstall, and preservation of an isolated project/data directory.

Use the guarded clean-install harness on that disposable machine:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\acceptance-windows-clean-install.ps1 `
  -InstallerPath .\apps\web\src-tauri\target\x86_64-pc-windows-msvc\release\bundle\msi\ReefVision_1.0.2_x64_en-US.msi `
  -AcceptanceRoot C:\reefvision-disposable-acceptance `
  -DisposableTest
```

The harness refuses to run without the explicit disposable-test switch, refuses normal ReefVision app-data and repository paths, refuses machines with an existing ReefVision registration, and only removes its own marked run directory. Supply `-PreviousInstallerPath` and `-PreviousInstallerSupportsIsolatedAcceptance` for an older MSI that implements the same marker-gated data-root contract; otherwise upgrade is recorded as `SKIPPED — previous installer not supplied`. See `docs/REEFVISION_1_0_RELEASE_EVIDENCE.md` for the evidence matrix.

## Common Windows packaging issues

### Conflicting OpenCV distributions

Do not manually install `opencv-python` alongside the pinned `opencv-contrib-python`. Both distributions provide the `cv2` package, so overlapping installs can leave an incomplete or inconsistent runtime. Re-run `scripts/bootstrap.ps1` to remove conflicting base/headless distributions and reinstall the supported provider stack.

A quick development-environment check is:

```powershell
.\.venv\Scripts\python.exe -c "import cv2; assert hasattr(cv2, 'aruco'); print(cv2.__version__, 'aruco OK')"
```

The production package must also pass the built-in sidecar `--self-test`; a development-environment check alone is not release evidence.

### Installer staging failures

Large scientific runtimes can fail MSI extraction when unnecessary dependency test/cache trees create excessive file counts and deeply nested paths. The backend staging script removes `tests`, `test`, `__pycache__`, `.pyc`, `.pyo`, and development cache directories after PyInstaller collection. It does not remove PyTorch/CUDA or other implemented-provider runtime libraries.

An older NSIS build can fail with a message similar to:

```text
failed creating mmap of "...\\reefvision-api-x86_64-pc-windows-msvc.exe"
```

This usually means the staged sidecar executable is still locked by another process. Before rebuilding:

- close any running packaged ReefVision window;
- close any smoke-install copy; and
- confirm no old `reefvision-api.exe` process is still running from a previous install or test directory.

Do not force-delete a staged binary while the process is still in use.

### Sidecar readiness failures

If the packaged app opens to a fetch error or startup failure:

- inspect the desktop logs;
- confirm the sidecar executable exists for the active architecture;
- confirm migrations can run against the user-data directory;
- confirm `cv2.aruco` passed the packaged self-test;
- confirm no local security tool quarantined the sidecar.

## Installation notes for researchers

The desktop installer bundles the frontend and backend together. Researchers should be able to:

- install ReefVision without Node.js or a Python development environment;
- launch the app from the Start menu or desktop shortcut;
- keep user data across upgrades;
- uninstall the app without removing user data by default.

Clean-machine verification is still required before those claims are treated as fully release-ready.
