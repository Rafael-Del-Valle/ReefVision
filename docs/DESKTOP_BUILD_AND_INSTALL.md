# Desktop Build and Installation

## Scope

This guide covers the current ReefVision desktop shell, sidecar build, NSIS packaging path, checksum verification, and common Windows-specific build pitfalls.

## Prerequisites

Development and packaging require:

- Python with the ReefVision pinned dependencies installed;
- Node.js and npm;
- a Rust toolchain;
- Visual Studio 2022 build tools with the MSVC C++ toolchain and Windows SDK.

End users of the finished installer do not need the development toolchain.

## Development shell

Use the desktop development workflow when validating the shell against the live repository:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-desktop.ps1
```

This starts the Vite frontend in Tauri, launches the FastAPI backend from `.venv`, and waits for sidecar readiness before rendering the application UI.

The development script sets `REEFVISION_DESKTOP_DATA_DIR` to `.desktop/dev-data` in the repository so desktop development can still start when the platform app-data directory is unavailable or blocked in a restricted environment.

## Production build

Build the packaged app and NSIS installer with:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-desktop.ps1
```

The build script:

- checks the public npm lockfile policy;
- builds the PyInstaller sidecar;
- stages the sidecar into `apps/web/src-tauri/binaries`;
- runs `tauri build --bundles nsis`; and
- writes the installer beneath `apps/web/src-tauri/target/<target-triple>/release/bundle/nsis/`.

## Installer location and checksum

After a successful Windows build, the expected installer directory is:

```text
apps/web/src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/
```

Generate a SHA-256 checksum with:

```powershell
Get-FileHash `
  apps\web\src-tauri\target\x86_64-pc-windows-msvc\release\bundle\nsis\*.exe `
  -Algorithm SHA256
```

Record the installer filename, version, and checksum in the milestone report or release notes.

## Upgrade testing

Before claiming upgrade safety:

1. Install the previous ReefVision desktop version.
2. Create or open a real project.
3. Confirm projects, managed images, models, dataset versions, QC runs, and review queues exist.
4. Install the new NSIS package over the old version.
5. Reopen the application and verify the same data is intact.

The installer should preserve user data because ReefVision stores active data in the Tauri per-user application-data directory rather than the installation directory.

## Common Windows packaging issues

### `failed creating mmap`

NSIS can fail with a message similar to:

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
- confirm no local security tool quarantined the sidecar.

## Installation notes for researchers

The desktop installer bundles the frontend and backend together. Researchers should be able to:

- install ReefVision without Node.js or a Python development environment;
- launch the app from the Start menu or desktop shortcut;
- keep user data across upgrades;
- uninstall the app without removing user data by default.

Clean-machine verification is still required before those claims are treated as fully release-ready.
