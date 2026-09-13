# ReefVision

ReefVision is a local-first scientific annotation, computer-vision, and marine-imagery analysis platform. The current `1.0.1` release line combines manual and model-assisted annotation, detection and segmentation workflows, coral measurements, classification, active learning, model/provider management, video tracking and scientific video analysis, reproducible datasets, review and quality-control workflows, project interoperability, executable workflow graphs, and Windows desktop packaging.

The application uses a React/Tauri desktop interface with a FastAPI/SQLAlchemy backend and persisted background jobs. Research data, annotations, model outputs, provenance, immutable dataset versions, generated artifacts, and project-exchange records are managed locally rather than requiring a hosted ReefVision service.

## Available now

- Create blank projects or projects using the six-class octocoral template.
- Add, rename, reorder, recolor, deactivate, and manage visibility for annotation classes.
- Import JPEG, PNG, TIFF, and WebP images as protected managed copies, with SHA-256 duplicate detection and background thumbnail generation.
- Browse project imagery with filename, annotation-status, and leakage-prevention group filters.
- Annotate imagery with bounding boxes, rotated boxes, polygons, raster brush edits, deterministic Fill, and editable mask workflows.
- Draw and retain coral centerlines and use scale/calibration assistants for scientific measurements.
- Calculate mask- and calibration-aware coral measurements and measurement analytics.
- Register trusted local detection, segmentation, classification, assist, depth, and other supported model checkpoints through the Model Hub.
- Run detector inference and review model proposals separately from verified human annotations.
- Run segmentation inference and edit resulting polygon or raster-mask annotations before saving them as research annotations.
- Use Prompt Assist and supported advanced providers through guarded preflight and execution workflows, including provider families such as SAM2, Grounding DINO, Depth Anything, OCR, VLM, and other installed adapters where runtime support is available.
- Create immutable dataset versions with frozen annotation state, leakage-aware splitting, parent-version reuse, comparisons, manifests, and dataset exports.
- Train supported detection and segmentation models through reproducible persisted training runs with validation, tuning, recovery, results packages, and model registration.
- Assign image-level classification labels, create versioned whole-image or crop-based classification datasets, train Ultralytics classifiers, run inference, and accept or reject ranked predictions.
- Run explainable quality-control checks across projects or immutable dataset versions, compare historical runs, and acknowledge or dismiss findings.
- Generate deterministic review queues with score breakdowns and direct navigation into annotation mode.
- Create active-learning acquisition rounds using uncertainty, rare-class, quality-risk, or hybrid strategies and freeze reviewed feedback into subsequent dataset versions.
- Import videos, run persisted ByteTrack or BoT-SORT tracking jobs, retain independent run histories, inspect tracking outputs, and exchange track data.
- Export annotated tracking-review MP4s from persisted observations without rerunning the detector, with selectable boxes, track IDs, class labels, confidence, trails, timestamps, and counters.
- Analyze video activity and occupancy and use scientific 3D/depth workflows with calibration validation, previews, visualization, and reporting.
- Build typed workflow graphs visually, validate and plan execution, save revisions, run persisted workflows, pause at human-review gates, resume work, and inspect artifact lineage.
- Export versioned, checksummed ReefVision project-exchange ZIPs, safely inspect packages before import, and import them as new managed projects with record-ID remapping. Original media, model weights, and generated artifacts remain explicit opt-ins.
- Export and import supported video-track exchange formats independently of whole-project exchange packages.
- Create managed backups, verify them, restore them into new managed recovery locations, and export redacted diagnostics bundles from the `System status` view.
- Reopen the first-run onboarding guide from the top bar or `System status`.
- Archive projects without deleting their records or managed files.
- Build a Windows MSI desktop installer that bundles the React frontend and PyInstaller-frozen FastAPI sidecar.

## Repository layout

- `apps/api`: FastAPI, SQLAlchemy, Alembic, and pytest.
- `apps/web`: React, TypeScript, Vite, Vitest, and the Tauri desktop shell.
- `docs`: product, architecture, data-model, and milestone reports.
- `scripts`: PowerShell workflows for Windows development and desktop packaging.

## Prerequisites

- Python 3.11 or newer
- Node.js 22 or newer (an active LTS release is recommended)
- npm 10 or newer

### Provider stack

- `setup.bat` installs the pinned Windows provider stack from `requirements/providers-windows-cu121-py312.txt`.
- The tested Ultralytics combination is Python `3.12.x`, CUDA `12.1`, `torch 2.5.1+cu121`, `torchvision 0.20.1+cu121`, and `ultralytics 8.3.228`.
- ReefVision does not download pretrained checkpoints automatically. Register local `.pt` or `.pth` files explicitly.

## Windows setup

### Easiest setup

1. Extract the ReefVision folder.
2. Double-click `setup.bat`.
3. When Node.js/npm are missing, approve the guided Node.js LTS installation.
4. After setup succeeds, double-click `start-reefvision.bat` to launch the API, web app, and browser.

The setup checks Node.js, npm, and Python before installing ReefVision dependencies. On Windows, it can install Node.js LTS through Windows Package Manager (`winget`) and refresh the current process PATH automatically. It also prefers `npm.cmd`, avoiding PowerShell execution-policy failures caused by `npm.ps1`. The pinned provider stack currently requires Python `3.12.x`; setup stops early with a clear error when a different interpreter is selected.

### Terminal setup

```powershell
Set-ExecutionPolicy -Scope Process Bypass
./scripts/bootstrap.ps1
```

Use `./scripts/check-prerequisites.ps1` or double-click `check-reefvision.bat` to verify Node.js, npm, and Python independently.

Copy `.env.example` to `.env` when custom settings are needed. Defaults work without an `.env` file.

## Run locally

The easiest launch method is to double-click `start-reefvision.bat`.

For terminal-based development, open two PowerShell terminals.

Terminal 1:

```powershell
./scripts/dev-api.ps1
```

Terminal 2:

```powershell
./scripts/dev-web.ps1
```

Then open `http://localhost:5173`.

The API development script applies pending Alembic migrations before starting the server.

To annotate an image, select a project, stay on the `Images` tab, import at least one image, and click `Annotate` on that image card.

To create a dataset version, switch to the `Versions` tab, choose the eligible image statuses and split method, preview the snapshot, and then create the immutable version. Exports run from the selected version card so later project edits do not alter the emitted dataset.

To run quality control, open a project, switch to the `Quality Control` tab, choose a project or dataset-version scope, adjust thresholds if needed, and start a run. Findings are historical diagnostic records only; they do not modify verified annotations.

To prioritize human review, switch to the `Review Queue` tab, optionally seed from a completed QC run, generate a queue, inspect the score breakdown, and open ranked images in the annotation editor. Returning from annotation mode keeps the user in the QC or queue workflow that launched the image.

To create a managed backup, verify one, restore into a new recovery folder, or export a redacted diagnostics bundle, open the `System status` workspace from the dashboard sidebar.

## Desktop packaging

ReefVision uses a Tauri 2 desktop shell in `apps/web/src-tauri` that bundles the existing Vite frontend and launches the FastAPI backend as a PyInstaller sidecar executable. The Windows distribution target is an MSI installer with external cabinet payloads. The desktop shell uses a per-user application-data directory, surfaces a retryable startup error when the backend does not come up cleanly, prevents competing desktop instances, focuses the existing window on a second launch, and waits for a loopback-only backend health check before rendering the dashboard.

### Desktop development shell

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-desktop.ps1
```

This launches the Vite development server in Tauri and starts the backend from `.venv` automatically, using the desktop runtime bootstrap instead of the browser-only `VITE_API_BASE_URL` default.

### Desktop installer build

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-desktop.ps1
```

The desktop build script:

- checks the public npm lockfile policy;
- builds the backend sidecar with PyInstaller;
- bundles the desktop app with Tauri; and
- emits an MSI plus its required `rv*.cab` payload files under `apps/web/src-tauri/target/<target-triple>/release/bundle/msi/`.

Close any running packaged ReefVision app, smoke-install copy, or sidecar executable before rebuilding the installer so staged binaries are not locked by a running process.

Building the installer requires a local Rust toolchain plus the Visual Studio 2022 MSVC C++ toolchain (`Desktop development with C++`, `MSVC v143 - VS 2022 C++ x64/x86 build tools`, and a Windows SDK). End users of the finished installer do not need Python, Node.js, Rust, or a terminal.

Desktop build, installer, and upgrade notes now live in [docs/DESKTOP_BUILD_AND_INSTALL.md](docs/DESKTOP_BUILD_AND_INSTALL.md).

## Milestone 7 docs

- [Quality Control Guide](docs/QUALITY_CONTROL_GUIDE.md)
- [Quality Control Rule Reference](docs/QUALITY_CONTROL_RULE_REFERENCE.md)
- [Quality Control Threshold Reference](docs/QUALITY_CONTROL_THRESHOLDS.md)
- [Review Queue Guide](docs/REVIEW_QUEUE_GUIDE.md)
- [Review Prioritization Formula](docs/REVIEW_PRIORITIZATION_FORMULA.md)
- [Prioritization vs Calibrated Uncertainty](docs/PRIORITIZATION_VS_CALIBRATED_UNCERTAINTY.md)
- [Desktop Build and Installation](docs/DESKTOP_BUILD_AND_INSTALL.md)

## Backend checks

```powershell
.\.venv\Scripts\python.exe -m ruff check apps/api
.\.venv\Scripts\python.exe -m ruff format --check apps/api
.\.venv\Scripts\python.exe -m mypy apps/api/reefvision
.\.venv\Scripts\python.exe -m pytest apps/api/reefvision/tests
.\.venv\Scripts\alembic.exe -c apps/api/alembic.ini upgrade head
.\.venv\Scripts\alembic.exe -c apps/api/alembic.ini downgrade base
```

## Frontend checks

```powershell
npm --prefix apps/web run format:check
npm --prefix apps/web run typecheck
npm --prefix apps/web run test
npm --prefix apps/web run test:e2e
npm --prefix apps/web run build
```

## Data safety

- Project directories are managed beneath `REEFVISION_DATA_DIR`.
- Model checkpoints are treated as trusted local files only; ReefVision does not silently download or execute adjacent code from a checkpoint directory.
- The desktop build stores managed data in the OS application-data directory chosen by Tauri and passes that path into the packaged backend.
- Stored project paths are relative and checked against path traversal.
- Archiving does not delete files.
- Tests always use temporary paths and never write to the configured user data directory.
- Imported originals use UUID filenames and are never overwritten by thumbnails or metadata edits.
- Exact duplicates are reported rather than silently copied.
- Thumbnail failures remain retryable and do not invalidate originals.
