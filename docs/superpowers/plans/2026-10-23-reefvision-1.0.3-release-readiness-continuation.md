# ReefVision 1.0.3 Release-Readiness Continuation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Continue draft PR #81 from its current head, integrate the advanced 1.0.3 base, fix any reproduced release blockers, and produce evidence-backed CPU/Windows readiness without merging or releasing.

**Architecture:** Preserve the existing source-pixel annotation contracts and provider-neutral training/tracking boundaries. Treat functionality already present on the PR or its base as validation work, add behavior only for reproduced gaps, and keep representative scientific acceptance separate from synthetic technical execution.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/Alembic, Pillow, React 19, TypeScript, Vitest, Playwright, Tauri 2, PowerShell, WiX/MSI.

**Spec:** `docs/roadmap/REEFVISION_1_0_3_CONSOLIDATED.md`

## Global Constraints

- Continue `fix/reefvision-training-architecture-picker-20261022`, the head branch for draft PR #81; do not merge the PR, tag, publish, or delete branches.
- Preserve original image bytes, source-pixel coordinates, prediction/review separation, immutable dataset versions, and leakage-aware splits.
- Use CPU-compatible tests and mocked device selection; RTX 3090/CUDA/TensorRT acceptance is `DEFERRED — HARDWARE`.
- Do not claim representative biological segmentation acceptance from synthetic fixtures.
- Add a failing behavior test before each production-code fix and commit verified logical groups separately.

## Review Focus

- WebView2/browser decode stalls must not prevent first-open display or leave stale pixels after rapid image switching.
- EXIF-oriented, CMYK/grayscale, uppercase-extension, truncated, TIFF, BMP, WebP, GIF, PNG, and JPEG-family inputs must preserve originals and source-coordinate overlays.
- Training consoles must read the actual persisted trainer output, remain read-only, and never start a duplicate training process.
- Held-out evaluation must prove split disjointness, valid source-pixel polygons, class mapping, persistence, and round-trip geometry without overstating representativeness.
- Installer checks must distinguish artifact/build validation, fresh install, explicit 1.0.2-to-1.0.3 upgrade, and interactive GUI acceptance.

---

### Task 1: Integrate the current 1.0.3 base

**Files:**
- Merge: `origin/develop/reefvision-1.0.3-consolidated`
- Review overlaps: `apps/web/src/features/gallery/Gallery.tsx`, `apps/web/src/features/annotation-editor/AnnotationEditor.tsx`, `apps/api/reefvision/storage/images.py`, training monitor routes/UI, Windows workflows.

**Interfaces:**
- Consumes: PR #81 head `c207a270` and the current base head.
- Produces: one non-rewritten PR branch containing both lines of 1.0.3 work.

- [ ] Merge the current base without rebasing or force-pushing.
- [ ] Resolve conflicts by preserving both tested behaviors and inspect the full merge diff.
- [ ] Run focused image, training-monitor, installer, tracking, and segmentation tests.
- [ ] Commit only if Git does not create the merge commit automatically; push after verification.

### Task 2: Close reproduced image, annotation, and console defects

**Files:**
- Modify only when a failing test proves a gap: image storage/service, Gallery, AnnotationEditor, review UI, training routes/monitor/Tauri console.
- Test: existing camera/image/editor/gallery/training suites and `gallery-viewport-103.spec.ts`.

**Interfaces:**
- Consumes: immutable originals, browser display renditions, image revisions, persisted job metrics/logs.
- Produces: stable first-open/rapid-switch rendering, aligned overlays, explicit decode errors, and read-only live training output.

- [ ] Run format/decode/EXIF and initial-mount/rapid-switch/viewport regressions.
- [ ] Run Shift+1, Shift+2, Alt-drag, paint/erase, undo/redo, review threshold, navigation, and persistence coverage.
- [ ] Run active/completed/failed training state, real metric, cancellation, console, invalid-run-ID, and unavailable-runtime coverage.
- [ ] For each reproduced gap, perform red-green TDD, run affected suites, and commit the logical fix.

### Task 3: Revalidate segmentation and scientific contracts

**Files:**
- Modify only when a failing test proves a gap: segmentation inference/evaluation/promotion/import/export services and acceptance harness.
- Evidence: disposable output outside tracked source files; roadmap status after final verification.

**Interfaces:**
- Consumes: disjoint dataset versions, registered CPU-compatible checkpoint, reviewed/unreviewed predictions, COCO/YOLO geometry.
- Produces: valid held-out source-pixel polygons, persistence/round-trip evidence, promotion/rollback results, and an explicit representative-data gate.

- [ ] Run the bounded CPU segmentation lifecycle and held-out proposal harness.
- [ ] Run leakage, transform/alignment, promotion/rollback, reviewed-state, COCO/YOLO import/export, and round-trip suites.
- [ ] Search only for legitimate local/approved representative data; if absent, leave scientific acceptance `UNVERIFIED` with the exact missing dataset/ground-truth requirement.
- [ ] Fix reproduced software failures test-first and commit separately.

### Task 4: Complete feasible Windows deployment automation

**Files:**
- Modify only if required: `.github/workflows/build-desktop.yml`, installer acceptance scripts/tests, executable Windows procedure.

**Interfaces:**
- Consumes: exact clean source SHA, MSI/CAB/provenance artifacts, isolated data roots, released 1.0.2 installer when legitimately obtainable.
- Produces: explicit fresh-install and upgrade evidence, preserved user data, relaunch/uninstall/log results, or a precise physical-host procedure.

- [ ] Audit existing fresh-install and upgrade coverage after base integration.
- [ ] Add or repair safe automated 1.0.2-to-1.0.3 upgrade validation when feasible without publishing artifacts or altering the user's installed application.
- [ ] Validate packaging, migrations, paths with spaces, startup/shutdown, first launch, relaunch, persistence, uninstall, and diagnostics at the strongest available layer.
- [ ] Keep any unexecuted physical or interactive observations `UNVERIFIED`.

### Task 5: Full verification and PR handoff

**Files:**
- Modify: `docs/roadmap/REEFVISION_1_0_3_CONSOLIDATED.md` only for fresh evidence/status changes.

**Interfaces:**
- Consumes: exact final tree and all command/CI output.
- Produces: commits on PR #81, remote-SHA confirmation, CI status, blocker classification, and separate development/release-acceptance estimates.

- [ ] Run Ruff format/lint, mypy, full Pytest, Alembic round-trip, Prettier, TypeScript, full Vitest, Playwright, production build, and feasible installer checks.
- [ ] Review the branch diff against this plan, the roadmap, and `AGENTS.md`; address Critical/Important findings.
- [ ] Commit and push each verified logical group; confirm the remote branch and inspect CI.
- [ ] Keep PR #81 open and draft; report exact passes, skips, failures, blockers, readiness percentages, and release actions.
