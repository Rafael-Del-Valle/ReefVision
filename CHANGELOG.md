# Changelog

All notable changes to ReefVision will be documented here.

## [1.0.3] - Release candidate

### Added

- Direct deployment of trained or imported project detector models such as `best.pt` on the currently open annotation image.
- Batch model deployment from Gallery for selected images with model, confidence threshold, and device controls.
- Raster-mask class reassignment without repainting the underlying mask.

### Fixed

- Allow Delete and Backspace to remove the selected polygon instead of being intercepted by the enhanced annotation editor.
- Preserve polygon creation, whole-polygon movement, vertex movement, vertex insertion, and vertex deletion behavior with regression coverage.
- Keep annotation-editor onboarding E2E setup tied to the package version instead of a stale hard-coded version key.
- Correct range-control styling and annotation/mask workflow regressions found during 1.0.2 smoke testing.
- Use package-mode mypy invocation and pin AnyIO below 4.15 for the validated backend test environment.

### Release validation

- Final hosted CI, Windows MSI build, and clean-machine lifecycle acceptance must pass before this candidate is published as the downloadable 1.0.3 installer.

## [1.0.2] - In development

### Planned

- Restore the most recently selected project image and reliably choose the first eligible image for new projects.
- Add paginated Arrow, Home, and End navigation with an optional persisted wrap preference.
- Add temporary Alt-drag and middle-button panning, cursor-centered zoom, Fit, Actual Size, and Reset View controls.
- Add safe internal annotation copy, paste, duplicate, undo, and redo operations across compatible annotation workspaces.
- Add an in-app shortcut reference and exact-head performance, scientific-integrity, and Windows package evidence.

This section records development intent. Release publication remains gated on final exact-head validation and maintainer approval.

## [1.0.1] - Release candidate

### October 2026 — assisted annotation and clean Windows install

- Add user-selected automatic SAM 2.1 Hiera Tiny, Small, Base+, and Large
  checkpoint acquisition with local caching, provenance, integrity checks,
  retry handling, and no pretrained weights bundled in the installer.
- Assign **Shift+1** to box-prompted SAM segmentation and **Shift+2** to
  running selected locally registered detector predictions over an image.
- Create project classes from detector metadata, retain imported class names,
  and persist explicitly accepted model proposals as verified annotations.
- Support COCO JSON boxes, polygons and RLE masks, YOLO detection and
  segmentation files with data.yaml class names, and associated provenance.
- Provide the floating confidence review dialog; the default review cutoff
  includes predictions at or below 50% and excludes those above 50%.
- Repair frozen Windows scientific-library initialization by preloading SciPy
  BLAS and ARPACK before the desktop shutdown reader begins.
- Validate the 1.0.1 MSI on an isolated Windows machine with successful
  SAM inference, verified mask review, project persistence, restart, project
  exchange, uninstall, and preserved user data. See
  docs/RELEASE_1.0.1.md for exact acceptance evidence and remaining manual QA.


### Fixed

- Recover interrupted detection training as completed when the full configured
  epoch history and intact final checkpoint prove completion; preserve artifacts,
  metrics, timestamps and one experiment record without rerunning training.
- Finalize incomplete interrupted runs as failed and pending cancellations as
  cancelled. Preserve completed runs across restarts and ignore duplicate final
  Ultralytics epoch callbacks.
- Retain Windows single-process data loading and headless plotting. Preserve
  cancellation status when a provider raises while stopping.
- Accept installed scaled/P6 architecture aliases during preflight. Refresh
  training results and stop polling after terminal states; wait for draft saves
  before launching with fresh server-side preflight.
- Use the current package version in onboarding and verify MSI, desktop and API
  version metadata during production package verification.
- Recover the desktop UI after Windows sleep or resume without discarding the
  selected project or annotation state.
- Prevent duplicate isolated video workers from acquiring the same queued job.
- Finalize interrupted cancellation requests as cancelled on startup instead of
  silently requeueing work the user explicitly cancelled.
- Reject cancellation requests for running job types that do not implement
  cooperative cancellation while retaining cancellation for queued work.

### Added

- Polygon Fill: local connected flood fill with tolerance control, exact pixel
  boundary contours and conservative simplification. Results use ordinary
  editable polygons, classes, undo/redo and persistence. Holes, touching boundaries
  and overly complex outlines are rejected rather than silently changing geometry.
- Isolated real CPU/CUDA training lifecycle acceptance harness, including AMP,
  FP32, cancellation and process interruption at the final commit boundary.
- Isolated persisted video tracking with live progress, cancellation, retry and
  conservative restart recovery.
- Annotated tracking-video exports generated from persisted observations without
  rerunning the detector, including Clean Tracking and Full Review overlays.
- Project-level interoperability navigation for versioned, checksummed project
  exchange package export, inspection and safe import.
- Deterministic packaged self-test evidence for release acceptance.

No database migration is required. The existing 1.0.0 release/tag is unchanged.

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
