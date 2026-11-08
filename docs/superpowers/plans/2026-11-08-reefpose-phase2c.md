# ReefPose Phase 2C Anatomical Skeleton Designer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a graphical, revision-safe anatomical skeleton designer connected to ReefVision pose annotation, immutable dataset freezing, ReefPose training, and inference.

**Architecture:** Extend canonical pose schema revisions with normalized stable-ID definitions and project APIs. Render and edit those definitions in the existing React/video workspace, then carry stable IDs through existing pose observations and frozen provenance without creating parallel annotation or dataset systems.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, Pydantic, React, TypeScript, TanStack Query, SVG, Vitest, Playwright, PyTorch/CUDA.

**Spec:** `docs/superpowers/specs/2026-11-08-reefpose-phase2c-design.md`

## Global Constraints

- Work only on `feature/reefpose-core`; do not push, merge, tag, or publish.
- Preserve Phase 1/2A/2B, SLEAP, Ultralytics, annotations, and verified datasets.
- No automatic pretrained downloads or silent dependency rewrites.
- Test first and commit complete validated increments locally.
- Synthetic results are not biological validation.

## Review Focus

- Renaming/reordering a landmark must preserve stable identity without changing an old revision.
- Duplicate IDs, dangling edges, asymmetric partner declarations, and malformed repeats must be rejected.
- Legacy revisions/observations must remain readable and trainable.
- Exact source coordinates and visibility must survive editor save/reopen and zoom/pan.
- Frozen datasets and checkpoints must reject schema identity/hash mismatch.

---

### Task 1: Canonical anatomy revision API

**Files:** create migration, schemas, service, route and backend tests; modify pose schema models/router exports.

**Interfaces:** project list/create endpoints and schema detail/revision endpoints returning normalized immutable definitions.

- [ ] Write failing API tests for arbitrary anatomy, repeats/groups/edges/symmetry, revision history, canonical hash, invalid references, and legacy serialization.
- [ ] Run tests and confirm feature-missing failures.
- [ ] Add the revision definition column/migration, Pydantic contracts, normalization/validation service, and routes.
- [ ] Run focused backend tests and commit.

### Task 2: Graphical skeleton designer

**Files:** create anatomy API/component/tests; integrate into `VideoTrackingWorkspace`.

**Interfaces:** consumes Task 1 responses; emits explicit create/revision requests and selected exact schema revision.

- [ ] Write failing component tests for create, rename/reorder, repeats, groups, symmetry, edge editing, preview, save state, and errors.
- [ ] Run tests and confirm missing component behavior.
- [ ] Implement accessible form controls, SVG graph preview, revision history, and query invalidation.
- [ ] Run focused frontend tests and commit.

### Task 3: Stable-ID pose annotation integration

**Files:** modify pose editor types/state/component, video schemas/services/adapters, and tests.

**Interfaces:** observations carry `landmark_id`; legacy label/occurrence remains a compatibility projection.

- [ ] Write failing frontend/backend tests for stable IDs, repeated instances, drag/delete/status, revision pinning, reopen, and coordinate restoration.
- [ ] Run tests and confirm stable IDs are currently absent.
- [ ] Implement stable slot resolution and persistence without rewriting legacy observations.
- [ ] Run pose/video suites and commit.

### Task 4: Freeze, train, register, and infer with custom anatomy

**Files:** modify pose dataset snapshots/training metadata as needed; add integration tests.

**Interfaces:** frozen schema snapshot contains normalized definition; trainer/checkpoint preserves exact identity/order/hash.

- [ ] Write failing integration tests for verified custom anatomy freeze, unreviewed exclusion, ReefPose training/registration/inference, and incompatible checkpoint rejection.
- [ ] Run tests and confirm missing definition provenance.
- [ ] Implement minimal provenance propagation and validation.
- [ ] Run backend integration plus Ultralytics/SLEAP compatibility tests and commit.

### Task 5: Live GUI and RTX 3090 acceptance

**Files:** add guarded Playwright scenario and Phase 2C validation report.

**Interfaces:** actual rendered designer → annotation review → verified frozen dataset → workflow training → Model Hub → inference.

- [ ] Add a guarded live E2E test using synthetic arbitrary anatomy.
- [ ] Run TypeScript, formatting, Vitest, build, Ruff, mypy, relevant/full backend tests.
- [ ] Run guarded browser workflow and explicit RTX 3090 training/inference.
- [ ] Record evidence, limitations, failures, and final review; commit.

