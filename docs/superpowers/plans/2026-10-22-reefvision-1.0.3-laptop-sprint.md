# ReefVision 1.0.3 Laptop Sprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn draft PR #81 into the most complete laptop-validated ReefVision 1.0.3 candidate possible, with RTX 3090-only acceptance explicitly deferred.

**Architecture:** Preserve the consolidated 1.0.3 branch and existing provider-neutral service boundaries. Validate each already-implemented roadmap slice before changing it, then fix only reproduced gaps at the owning backend adapter/service or frontend workspace boundary. Keep detector and segmenter tracking passes independent and fuse their persisted observations after model-native tracking.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Ultralytics 8.3.228, React 19, TypeScript, Vitest, Playwright, Tauri 2, PyInstaller, WiX/MSI.

**Spec:** `docs/roadmap/REEFVISION_1_0_3_CONSOLIDATED.md`

## Global Constraints

- Work only on `fix/reefvision-training-architecture-picker-20261022`, the head of draft PR #81; do not merge, tag, publish, or delete branches.
- Preserve original image bytes and canonical source-pixel coordinates; keep predictions separate from verified annotations.
- Use CPU-compatible, tiny synthetic fixtures and one-epoch smoke training; do not download large pretrained weights.
- RTX 3090 training, CUDA inference, memory/performance, detection/segmentation benchmarks, hybrid throughput, and desktop-driver validation are `DEFERRED — DESKTOP GPU VALIDATION`.
- Existing passing behavior is evidence to record, not code to rewrite.

## Review Focus

- A packaged runtime that has Ultralytics metadata but lacks architecture YAML data must report an actionable provider/runtime failure, not an empty selector.
- Switching detection/segmentation task or architecture family must not silently lose an explicit size/checkpoint selection.
- Hybrid tracking must not merge incompatible classes or invent masks when objects cross or occlude one another.
- Browser-safe display conversion must not modify imported originals or alter source-pixel dimensions/orientation.
- The PowerShell monitor must validate the run ID, remain read-only, and never launch a second training process.

---

### Task 1: Training architecture and initialization lifecycle

**Files:**
- Modify: `apps/api/reefvision/services/training.py`
- Modify: `apps/api/reefvision/services/segmentation_training.py`
- Modify: `apps/api/reefvision/services/model_catalog.py`
- Modify: `apps/web/src/features/training/TrainingWorkspace.tsx`
- Test: `apps/api/reefvision/tests/test_training_architecture_validation.py`
- Test: `apps/api/reefvision/tests/test_training_initialization_policy.py`
- Test: `apps/api/reefvision/tests/test_training_workspace.py`
- Test: `apps/web/src/features/training/TrainingWorkspace.test.tsx`
- Test: `scripts/acceptance_training_lifecycle.py`

**Interfaces:**
- Consumes: `TrainingWorkspaceBootstrapResponse`, weight-free `builtin_architecture` catalog entries, provider preflight, immutable dataset versions.
- Produces: persisted explicit detection/segmentation architecture or registered-checkpoint selection; actionable preflight; registered output checkpoint.

- [ ] **Step 1: Reproduce real discovery and selection against the installed pinned provider**

Run the focused backend/frontend suites plus an unmocked architecture inventory. Expected: five YOLO11 detection sizes and five YOLO11 segmentation sizes are selectable; any gap is captured by a failing behavior test before production changes.

- [ ] **Step 2: Add the smallest failing regression for each reproduced gap**

Cover provider-required vs empty catalog, explicit selection persistence, scratch initialization, compatible registered checkpoints, and packaged YAML absence.

- [ ] **Step 3: Fix the owning discovery, validation, or UI state boundary**

Do not bypass preflight. Catalog visibility and provider readiness remain separate facts.

- [ ] **Step 4: Run CPU lifecycle verification**

Run the focused suites and the smallest feasible detection and instance-segmentation lifecycle: dataset → draft → one epoch → checkpoint → registration → inference. Record any infeasible real-training step as `UNVERIFIED`, not PASS.

- [ ] **Step 5: Commit the training slice**

Commit production changes and their red-green tests together.

### Task 2: Detection, segmentation, and hybrid video tracking stabilization

**Files:**
- Modify: `apps/api/reefvision/api/routes/videos.py`
- Modify: `apps/api/reefvision/jobs/video_tracking.py`
- Modify: `apps/api/reefvision/ml/video_tracking.py`
- Modify: `apps/api/reefvision/ml/video_tracking_fusion.py`
- Modify: `apps/api/reefvision/services/video_tracks.py`
- Modify: `apps/web/src/features/video/VideoTrackingWorkspace.tsx`
- Test: `apps/api/reefvision/tests/test_video_tracking_fusion.py`
- Test: `apps/api/reefvision/tests/test_video_tracking_phase6.py`
- Test: `apps/web/src/features/video/VideoTrackingWorkspace.test.tsx`

**Interfaces:**
- Consumes: registered task-compatible detector/segmenter models and independent ByteTrack or BoT-SORT observations.
- Produces: persisted editable observations with stable IDs, source-pixel polygons, provenance, progress/cancellation, and export-compatible measurements.

- [ ] **Step 1: Run focused tracking tests and inspect every PR #81 tracking diff**

Expected: current tests expose no syntax/type/regression failure; missing acceptance behavior receives a failing test first.

- [ ] **Step 2: Harden class-aware one-to-one fusion edge cases**

Test detector fallback, unmatched segmentation IDs, duplicate suppression, crossing/occlusion ambiguity, mask retention, provenance, and invalid association thresholds.

- [ ] **Step 3: Verify UI selection, mask overlay/edit persistence, progress, cancellation, and exports**

Use deterministic fake providers and a tiny synthetic video; do not describe BoT-SORT as accepting two models simultaneously.

- [ ] **Step 4: Commit the tracking slice**

Commit only reproduced fixes and their red-green coverage.

### Task 3: Image display/import and live training monitor acceptance

**Files:**
- Modify: `apps/api/reefvision/storage/images.py`
- Modify: `apps/api/reefvision/services/images.py`
- Modify: `apps/web/src/features/annotation-editor/AnnotationEditor.tsx`
- Modify: `apps/web/src/components/layout/ProjectTrainingMonitor.tsx`
- Modify: `apps/web/src/features/training/TrainingRunDetail.tsx`
- Modify: `apps/web/src-tauri/src/main.rs`
- Test: `apps/api/reefvision/tests/test_images.py`
- Test: `apps/api/reefvision/tests/test_camera_jpeg_regression_103.py`
- Test: `apps/web/src/features/annotation-editor/AnnotationEditor.test.tsx`
- Test: `apps/web/src/features/training/TrainingRunDetail.test.tsx`
- Test: `apps/web/src/components/layout/ProjectTrainingMonitor.test.tsx`
- Test: `apps/web/tests/e2e/gallery-viewport-103.spec.ts`

**Interfaces:**
- Consumes: immutable originals, browser-safe display endpoints, persisted training metrics/log paths.
- Produces: stable first-open rendering/overlay alignment, full required format import behavior, and a read-only independently reopenable PowerShell monitor.

- [ ] **Step 1: Run the complete format and first-open regression matrix**

Cover all roadmap extensions (including uppercase), CMYK JPEG, EXIF orientation, corrupt/truncated files, duplicates, static/animated GIF handling, cold/warm cache, resize, zoom, and pan.

- [ ] **Step 2: Add a failing regression for any reproduced display/import gap, then fix minimally**

Verify original hashes and source-pixel geometry remain unchanged.

- [ ] **Step 3: Validate active/completed/failed training metrics and Windows console behavior**

Test epoch/stage/loss/validation/error display, invalid run IDs, duplicate-console independence, and unavailable desktop runtime.

- [ ] **Step 4: Commit the image/monitor slice**

Commit only reproduced fixes and their red-green coverage.

### Task 4: Regression, migration, and Windows installer validation

**Files:**
- Modify: `scripts/build-desktop-backend.ps1`
- Modify: `scripts/build-desktop.ps1`
- Modify: CI/build tests only when a reproduced packaging defect requires it.

**Interfaces:**
- Consumes: the exact committed source tree and pinned provider dependencies.
- Produces: test logs, migration evidence, production web build, MSI/CAB artifacts and checksums when supported.

- [ ] **Step 1: Run Ruff, mypy, Pytest, migration round-trip, Prettier, TypeScript, Vitest, Playwright, and production build**

Record every command and exact failure; do not weaken tests.

- [ ] **Step 2: Fix reproducible regressions test-first**

Use systematic debugging for each distinct failure and commit coherent fixes incrementally.

- [ ] **Step 3: Build and inspect the Windows 1.0.3 desktop installer**

Verify the packaged backend contains Ultralytics architecture YAML data and catalog resources. Preserve artifact hashes and build commit provenance; physical installation remains `UNVERIFIED` unless actually performed.

### Task 5: Roadmap evidence and PR handoff

**Files:**
- Modify: `docs/roadmap/REEFVISION_1_0_3_CONSOLIDATED.md`

**Interfaces:**
- Consumes: fresh local/CI command outputs, installer artifacts, and exact Git commit state.
- Produces: evidence-backed P0-P7 statuses and the owner-facing readiness report.

- [ ] **Step 1: Record PASS, FAIL, BLOCKED, UNVERIFIED, or DEFERRED evidence for every roadmap group**

Do not mark a roadmap checkbox complete from code presence alone.

- [ ] **Step 2: Review the full branch diff against the roadmap and AGENTS.md contracts**

Run an independent whole-branch review and fix Critical/Important findings test-first.

- [ ] **Step 3: Commit, push PR #81, and report final SHA and readiness**

Include detection/segmentation/hybrid readiness, CPU training, image loading, installer/physical installation, GPU deferrals, non-GPU blockers, and release-candidate status.
