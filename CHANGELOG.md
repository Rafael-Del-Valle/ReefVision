# Changelog

All notable changes to ReefVision will be documented here.

## [Unreleased]

### Added

- Class-management support for descriptions, archive or restore, delete-unused checks, usage reporting, and mutable class merges that preserve immutable dataset and model history.
- Annotation-editor visibility controls for show all, hide all, invert, reset, and per-class solo without refetching the annotation session.
- A unified model-provider catalog with explicit capability matrices, runtime backend reporting, and honest availability states for implemented versus blocked provider families.
- Prompt Assist `Detect then segment` workflow support that sends a selected detector proposal into a registered assist model and preserves source-proposal provenance on accepted masks.
- Milestone 8 foundations for managed application backups with persisted backup history, deterministic manifests, completion markers, checksum verification, and app-scoped backup jobs.
- Milestone 8 managed restore jobs that verify backups first and then restore into new managed recovery locations without overwriting the active data directory.
- Redacted diagnostic-bundle export jobs plus a first-run onboarding or help surface in the frontend.
- Automated version-consistency coverage across the Python package, workspace metadata, frontend package metadata, Tauri configuration, and Rust desktop package metadata.
- Milestone 7 quality-control runs with deterministic rule versions, configurable thresholds, historical issue records, run comparison, and project- or dataset-version scope.
- Explainable review-queue generation with persisted formula metadata, per-image score breakdowns, queue-item workflow states, and direct annotation-editor navigation from ranked items.
- Quality-control and review-prioritization API routes, repositories, database models, and worker support for historical QC job execution.
- Documentation for quality-control workflows, rule reference, threshold reference, review prioritization, and desktop build or installation verification.
- Milestone 6 immutable dataset versions with frozen per-image annotation snapshots, manifest checksums, split previews, version comparison, and queued YOLO dataset exports.
- Milestone 5 backend support for trusted local model registration, queued detector inference jobs, prediction-proposal persistence, proposal review endpoints, SAM-style assist-session APIs, and annotation provenance capture.
- Pinned Windows provider dependency stack plus API and UI preflight reporting for the implemented Ultralytics and Segment Anything model providers.
- Project-level model management UI plus gallery-side detector job launch controls.
- Annotation-editor prediction overlays, filtering, single-review actions, and bulk visible review actions.
- Manual bounding-box annotation with persisted saves, revision conflict checks, undo/redo, and image-to-image navigation.
- Tauri 2 desktop packaging scaffold under `apps/web/src-tauri`.
- Desktop runtime bootstrap so the React frontend can discover a packaged local API endpoint at launch.
- PyInstaller-based FastAPI sidecar entrypoint and Windows desktop build scripts.
- NSIS-targeted Tauri bundling with offline WebView2 install mode.
- Public npm registry hardening through `apps/web/.npmrc`, lockfile validation, and bootstrap-time lockfile repair.
- Guided first-time setup that detects missing Node.js/npm before Python dependency installation.
- Optional automatic Node.js LTS installation through Windows Package Manager.
- Shared Node/npm discovery that refreshes PATH and prefers `npm.cmd` on Windows.
- `setup.bat`, `start-reefvision.bat`, and `check-reefvision.bat` for double-click setup, startup, and diagnostics.
- Visible setup stages so long-running npm and Playwright installation steps no longer appear frozen.
- Desktop-sidecar readiness publishing so the backend selects its own loopback port and the shell waits for it before rendering.
- Single-instance protection for the Tauri desktop shell on Windows.
- Retryable desktop startup error UI when the local backend does not become healthy in time.
- Windows second-launch behavior that surfaces the existing ReefVision window instead of silently competing.
- Milestone 2 image and persisted-job database models.
- Reversible `0003` image/job migration.
- Managed-copy imports for JPEG, PNG, TIFF, and WebP.
- SHA-256 duplicate detection, image metadata, dimensions, and source-relative paths.
- Atomic staging and managed-file publication.
- Background thumbnail processing, interruption recovery, and retry.
- Paginated image APIs with filename, status, and group-key filters.
- Responsive project gallery, file/folder selection, import reports, and metadata editing.
- Backend, component, and Playwright acceptance coverage.

### Fixed

- Applied class visibility to prediction-review rows and canvas overlays without forcing a fresh annotation-session request.
- Preserved annotation-editor return context when opening images from Quality Control or Review Queue workflows instead of always dropping back to the gallery.
- Served full-size annotation-editor images inline instead of as attachment downloads so browsers can render them reliably.
- Blocked implicit Ultralytics model downloads by requiring existing local checkpoints before inspection or inference.
- Preserved uploaded checkpoint extensions during staging so provider inspection sees `.pt` and `.pth` files instead of opaque temporary suffixes.
- Allowed leaving the annotation editor after a failed save by prompting to discard unsaved local edits.
- Limited class reassignment to select mode so changing the active class in box mode no longer mutates the latest selected annotation.
- Prevented `bootstrap.ps1` from completing Python installation and then failing with an unhandled `npm` command-not-found error.
- Allowed Node.js installed during the current setup session to be detected without requiring an immediate terminal restart.
- Prevented PowerShell execution-policy settings from selecting and blocking `npm.ps1` when `npm.cmd` is available.
- Fixed PyInstaller desktop builds that resolved Alembic files relative to the generated spec directory instead of the repository.
- Bundled the required Anaconda runtime DLLs explicitly for the PyInstaller sidecar build.
- Added a fail-fast desktop-build prerequisite check when Rust is installed but the MSVC `link.exe` toolchain is missing.
- Removed the unused `httpx2` test dependency and retained the supported HTTPX TestClient dependency.
- Corrected warning configuration so nonexistent Starlette warning classes are not imported.
- Closed SQLite engines after test schema cleanup, eliminating resource warnings.

### Changed

- Version line advanced to `1.6.0`.
- The Model Manager now exposes provider-catalog and runtime-status sections alongside the existing dependency preflight and pinned Ultralytics training registry.
- Assist sessions can now retain an originating prediction proposal so accepted prompt-assisted masks update the proposal-review lifecycle instead of bypassing it.
- The project UI now exposes dedicated `Quality Control` and `Review Queue` tabs beside the existing gallery, versions, models, and classes workflows.
- The project UI now exposes a dedicated `Versions` tab for snapshot previews, immutable version creation, comparison, and export download links.
- `setup.bat` and `bootstrap.ps1` now install the pinned provider stack during development setup, and desktop sidecar builds now fail fast when those dependencies are missing or incompatible.
- Desktop builds now use a Tauri app-data directory instead of the repository-local `.reefvision` default.
- Backend CORS defaults now include the local desktop shell origins used by Tauri.
- Frontend CI now uses Node.js 22 and explicitly rejects private-registry lockfile URLs before `npm ci`.
- ReefVision now starts a lightweight persisted thumbnail worker by default.
- Project detail navigation now separates Images and Classes.
- CI and Windows test scripts now include the Playwright workflow.
- Documentation now reflects Milestone 2 storage, jobs, gallery behavior, and desktop packaging.

## Milestone 0

### Added

- Repository foundation.
- FastAPI health endpoint.
- React/Vite health screen.
- SQLAlchemy and Alembic database foundation.
- Backend and frontend test scaffolding.
- Windows PowerShell development scripts.
