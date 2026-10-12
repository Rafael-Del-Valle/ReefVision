# Developing ReefVision from source

These notes are for contributors and researchers running ReefVision from the repository, rather than installing the packaged Windows desktop release. For most users, start with the [README installation steps](../README.md#installation).

## Repository layout

- `apps/api` — FastAPI, SQLAlchemy, Alembic, and pytest.
- `apps/web` — React, TypeScript, Vite, Vitest, and Tauri.
- `docs` — architecture, methods, release notes, and research documentation.
- `scripts` — setup, testing, and Windows packaging scripts.

## Development prerequisites

- Python 3.12.x for the pinned Windows provider stack.
- Node.js 22 or newer and npm 10 or newer.
- A Windows development environment for the supported desktop build.

The pinned Windows provider requirements are in `requirements/providers-windows-cu121-py312.txt`. The documented Ultralytics combination uses CUDA 12.1, `torch 2.5.1+cu121`, `torchvision 0.20.1+cu121`, and `ultralytics 8.3.228`. The pinned provider stack should be installed through the supported bootstrap workflow rather than assembled by hand.

For the current baseline, model checkpoints are registered as local assets; the application does not require a pretrained download just to use manual annotation tools.

## Windows setup

From a source checkout, the guided setup is:

1. Extract or clone ReefVision.
2. Double-click `setup.bat`.
3. Approve the guided Node.js LTS installation if prompted.
4. Double-click `start-reefvision.bat` after setup.

The setup checks Python, Node.js, and npm and uses `npm.cmd` to avoid PowerShell execution-policy conflicts. It can use `winget` to install Node.js. The pinned provider stack requires Python 3.12.x.

Alternatively, from PowerShell at the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
./scripts/bootstrap.ps1
```

Run `./scripts/check-prerequisites.ps1` or `check-reefvision.bat` to check the development toolchain. Copy `.env.example` to `.env` only if you need non-default settings.

## Running the application locally

The simplest option after setup is `start-reefvision.bat`.

For manual development, start the API and frontend in separate terminals.

**Terminal 1**

```powershell
./scripts/dev-api.ps1
```

**Terminal 2**

```powershell
./scripts/dev-web.ps1
```

Open `http://localhost:5173`. The API script applies pending Alembic migrations before starting the server.

To use the Tauri development shell instead:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-desktop.ps1
```

## Working with projects

- **Annotations:** Open a project, import an image from `Images`, and choose `Annotate` on its card.
- **Dataset versions:** Use `Versions` to preview and freeze a snapshot. Export from the version card so later project edits do not change the exported annotations.
- **Quality control:** Use `Quality Control` to run checks against a project or dataset version. Findings are diagnostic records and do not modify accepted annotations.
- **Review queues:** Generate a queue, optionally starting from a QC run, and open ranked images for review.
- **Backups:** Use `System status` to create, verify, and restore a backup or export redacted diagnostics.

## Windows desktop packaging

The Tauri 2 shell bundles the Vite frontend and launches a PyInstaller-frozen FastAPI sidecar. Windows builds produce an MSI and external `rv*.cab` payloads.

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-desktop.ps1
```

This validates the npm lockfile policy, builds the Python sidecar, bundles the desktop application, and writes the installer under `apps/web/src-tauri/target/<target-triple>/release/bundle/msi/`.

Building the installer requires Rust and the Visual Studio 2022 MSVC C++ build tools, including a Windows SDK. End users of a packaged MSI do not need these development tools.

See [Desktop Build and Installation](DESKTOP_BUILD_AND_INSTALL.md) for packaging, self-tests, clean-install acceptance, and upgrade testing. Close running ReefVision instances before rebuilding so staged binaries are not locked.

## Checks

The recommended full pull-request gate is:

```powershell
./scripts/validate-pr.ps1
```

Backend checks can also be run individually:

```powershell
.\.venv\Scripts\python.exe -m ruff check apps/api
.\.venv\Scripts\python.exe -m ruff format --check apps/api
.\.venv\Scripts\python.exe -m mypy apps/api/reefvision
.\.venv\Scripts\python.exe -m pytest apps/api/reefvision/tests
.\.venv\Scripts\alembic.exe -c apps/api/alembic.ini upgrade head
.\.venv\Scripts\alembic.exe -c apps/api/alembic.ini downgrade base
```

Frontend checks:

```powershell
npm --prefix apps/web run format:check
npm --prefix apps/web run typecheck
npm --prefix apps/web run test
npm --prefix apps/web run test:e2e
npm --prefix apps/web run build
```

## Data handling

- Project files live beneath `REEFVISION_DATA_DIR`; the packaged desktop build uses an OS application-data directory managed by Tauri.
- Original images are stored as managed copies; duplicate images are reported rather than silently overwritten.
- Stored project paths are validated against directory traversal.
- Archiving a project does not delete its managed files.
- Automated tests use temporary data locations rather than the configured research directory.
- Model files are treated as trusted local assets. Follow the provider's documented requirements before loading a checkpoint.

More background is in [Architecture](ARCHITECTURE.md), [Testing](TESTING.md), and [Contributing](../CONTRIBUTING.md).
