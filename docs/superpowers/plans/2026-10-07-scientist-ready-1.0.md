# Scientist-Ready 1.0 release implementation plan

**Goal:** Deliver the user's architecture-first, no-pretrained ReefVision 1.0.0 release with evidence for every acceptance claim.

**Architecture:** Preserve canonical scientific data and existing model registrations. Catalog entries describe weight-free architectures or capabilities requiring researcher models; all checkpoint execution requires an existing local file. Training explicitly chooses random initialization or a registered model.

**Tech stack:** FastAPI/Pydantic/SQLAlchemy, pinned Ultralytics 8.3.228, React/TypeScript, Tauri, PyInstaller and WiX.

**Spec:** `docs/superpowers/specs/2026-10-07-scientist-ready-1.0-policy.md` (verbatim user request).

## Constraints and decisions

- Continue the clean Phase 12 branch at 8e4be364 in the requested checkout; preserve the validated typing checkpoint.
- No weights bundled, fetched automatically, or silently substituted. Preserve original user files and registrations.
- No 1.1 functionality. Do not rewrite applied migrations or historical releases.
- User explicitly requests execution, commits, pushes and eventual tagging; tag only after all required acceptance passes.
- Independent training and packaging domains can proceed in parallel with explicit file ownership. Catalog/UI integration remains sequential.

## Review focus

- Legacy queued downloads must fail safely, including after upgrades.
- Missing local checkpoints and provider defaults must never become network downloads.
- Existing user registrations retain task/schema/provenance and remain executable.
- Empty profiles show capabilities without implying architecture weights are installed.
- The packaged runtime must train offline without reaching for framework helper weights.

## Checkpoints

### 1. Catalog and model policy

Files: config/model_catalog.json; schemas/model_catalog.py; services/model_catalog.py, model_install.py, segmentation_catalog.py; jobs/model_install.py; ml/optional_transformers_runtime.py; related tests.

- [ ] Add failing tests for all YOLO11 detect/segment/pose sizes, no weight manifests, and disabled download requests.
- [ ] Convert definitions and schema to architecture/provider taxonomy; preserve registration-backed entries.
- [ ] Reject acquisition at service/worker/runtime boundaries and preserve local registration.
- [ ] Run focused tests, Ruff and mypy, then commit validated checkpoint.

### 2. Explicit training initialization

Files: jobs/*training.py; services/workflow_pose_training.py; training schemas/services; ml training adapters; relevant tests.

- [ ] Add failing tests for random pose training without a seed model and continuation with a registered seed.
- [ ] Implement explicit architecture selection, initialization provenance, no-download provider construction and training arguments.
- [ ] Verify detect/segment/classify/pose training, schema binding, workflow propagation and real tiny offline training.
- [ ] Run focused regression tests and commit validated checkpoint.

### 3. Model Manager and training UI

Files: apps/web/src/features/models/ModelManager.tsx, features/training, workflow pose controls, api types and relevant tests.

- [ ] Test architecture vs registration states and actions.
- [ ] Remove acquisition controls; surface training, registration, provenance and missing-model instructions.
- [ ] Expose random pose architecture selection and registered continuation without ambiguity.
- [ ] Run TypeScript, Vitest and production build.

### 4. Packaging and version policy

Files: scripts/stage-bundled-models.py, build-desktop.ps1, legacy acquisition scripts, runtime bundling, current version sources and release tests.

- [ ] Add failing release checks for prohibited model assets and version disagreement.
- [ ] Make staging weight-free; retire acquisition scripts; inspect bundled contents against manifest.
- [ ] Normalize public versions to 1.0.0 without rewriting history.
- [ ] Build backend, frontend, Tauri and MSI; generate verified checksums.

### 5. Release acceptance and closeout

Files: final acceptance report and model-policy documentation.

- [ ] Full backend Ruff/format/mypy/pytest and frontend TypeScript/Vitest/build.
- [ ] Packaged self-test, clean-profile execution, tiny detection/pose training and local inference with blocked networking.
- [ ] Phase 12 desktop, layout, workflow, review and pose acceptance; record unavailable physical-monitor checks honestly.
- [ ] Review whole change, repair defects, commit/push validated work and verify clean status.
- [ ] Create v1.0.0 only if all applicable release gates pass; otherwise list precise blockers.

## Progress

- Preflight passed: clean expected branch, exact validated HEAD, commit in history.
- Initial audit confirms legacy catalog downloads, build-time weight staging and mandatory pose seed checkpoint; these require policy conversion.
