# ReefPose Phase 4 Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with test-driven development.

**Goal:** Deliver a complete, auditable multi-animal pose identity workflow from persisted pose detections through deterministic association, scientist correction, identity evaluation, workflow execution, GUI review, and export.

**Architecture:** Treat existing `VideoTrack` pose keyframes as immutable provider output. Add a separate identity-association layer whose runs, individuals, observation assignments, candidate decisions, occlusions, corrections, truth manifests, and evaluations are revisioned and provenance-bearing. Keep the pure association and metric algorithms dependency-light and deterministic; persistence/services adapt canonical ReefVision records to those algorithms. Extend existing workflow and Video Tracking Workspace surfaces rather than creating parallel applications.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/Alembic, Pydantic, pytest; React 19, TypeScript, TanStack Query, Vitest/Testing Library, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-12-reefpose-phase4-multi-animal-design.md`

**Global constraints:** Work only on `feature/reefpose-core`; preserve Phase 1–3B and existing annotations/providers; no dependency installation, pretrained downloads, push/merge/tag/publish; coordinates remain source-image coordinates; model identities never become scientist-verified without an explicit correction/review event; migrations are reversible and do not rewrite `video_tracks`; synthetic validation is engineering evidence, not biological validation.

---

### Task 1: Canonical identity persistence and reversible migration

**Files:**
- Create: `apps/api/reefvision/db/models/pose_identity_tracking.py`
- Modify: `apps/api/reefvision/db/models/__init__.py`
- Create: `apps/api/migrations/versions/0041_pose_identity_tracking.py`
- Create: `apps/api/reefvision/schemas/pose_identity_tracking.py`
- Test: `apps/api/reefvision/tests/test_pose_identity_tracking_migration.py`

**Interfaces:** Produce SQLAlchemy/Pydantic contracts for association runs, stable individuals, immutable observation revisions, scored association decisions, occlusion intervals, append-only corrections, immutable truth datasets, and evaluation runs. Every record carries source video/schema/run provenance as applicable. Task 3 consumes these models; Task 4 consumes truth/evaluation records; Task 5 serializes run IDs into workflow artifacts.

1. Write migration/model contract tests that assert table creation, foreign keys, uniqueness, revision fields, source-coordinate metadata, and downgrade removal without modifying existing `video_tracks` rows.
2. Run the focused test and confirm RED because revision `0041` and models do not exist.
3. Implement the minimal models, schemas, exports, and reversible migration.
4. Run focused migration/model tests and the existing migration smoke tests; confirm GREEN.
5. Commit: `feat(pose): add identity tracking persistence`.

### Task 2: Pure deterministic pose-aware association

**Files:**
- Create: `apps/api/reefvision/domain/pose_identity_tracking.py`
- Test: `apps/api/reefvision/tests/test_pose_identity_tracking_domain.py`

**Interfaces:** Consume normalized source-coordinate detections (`detection_id`, frame, bbox, landmarks, visibility/confidence, schema identity). Produce stable track IDs, assignments, full candidate score components, selected/gated decisions, confidence, gaps/occlusions, lifecycle events, algorithm version and parameter hash. Task 3 persists this result unchanged.

1. Add hand-calculated synthetic tests for deterministic ordering, two-animal crossing with motion history, temporary occlusion/reappearance, missing landmarks, low-confidence gating, initiation/termination, and parameter hashing.
2. Run the focused domain tests and confirm RED on the missing module/API.
3. Implement deterministic global assignment without new dependencies, using motion prediction, normalized centroid distance, bbox IoU, landmark similarity, confidence penalties, configurable gates, and lexical tie-breaking.
4. Run focused tests; mutate tie ordering/gap gates mentally and ensure tests would fail; confirm GREEN.
5. Commit: `feat(pose): implement deterministic identity association`.

### Task 3: Persistence service, API, corrections, jobs, and export

**Files:**
- Create: `apps/api/reefvision/services/pose_identity_tracking.py`
- Create: `apps/api/reefvision/api/routes/pose_identity_tracking.py`
- Modify: `apps/api/reefvision/api/router.py`
- Modify: `apps/api/reefvision/schemas/jobs.py`
- Modify: `apps/api/reefvision/jobs/worker.py`
- Create: `apps/api/reefvision/jobs/pose_identity_tracking.py`
- Test: `apps/api/reefvision/tests/test_pose_identity_tracking_api.py`
- Test: `apps/api/reefvision/tests/test_pose_identity_tracking_job.py`

**Interfaces:** Consume existing pose `VideoTrack` keyframes and Task 2 outputs. Persist Task 1 records transactionally. Expose create/list/detail/status, frame observations, low-confidence queue, cancel, split/merge/reassign/swap/accept/reject, correction history, replay/reopen, and JSON/CSV export. Corrections append revisions and never overwrite model assignments. Task 5 calls the service/job; Task 6 calls the API.

1. Write integration tests for association creation, cross-video/schema rejection, cancellation rollback, persisted scores, low-confidence review, append-only reassign/split/merge, historical revision integrity, reopen, and provenance-complete export.
2. Run focused tests and confirm RED on missing endpoints/service.
3. Implement service, routes, worker dispatch, cancellation checkpoints, and export with structured validation errors.
4. Run focused tests plus existing pose/video job regressions; confirm GREEN.
5. Commit: `feat(pose): expose identity tracking and correction APIs`.

### Task 4: Verified truth and scientific identity evaluation

**Files:**
- Create: `apps/api/reefvision/domain/pose_identity_evaluation.py`
- Modify: `apps/api/reefvision/services/pose_identity_tracking.py`
- Modify: `apps/api/reefvision/api/routes/pose_identity_tracking.py`
- Modify: `apps/api/reefvision/schemas/pose_identity_tracking.py`
- Test: `apps/api/reefvision/tests/test_pose_identity_evaluation.py`
- Test: `apps/api/reefvision/tests/test_pose_identity_evaluation_api.py`

**Interfaces:** Consume immutable scientist-verified identity truth plus one association run/revision. Produce IDTP/IDFP/IDFN, ID precision/recall/F1, switch count, fragmentation, per-identity coverage, association summaries, thresholds, warnings, and a report compatible with Phase 3B provenance/report conventions. Never mix landmark localization metrics into identity metrics.

1. Add independently calculated fixtures for perfect tracking, one identity switch, fragmentation/misses, false positives, and absent/unverified truth warnings/rejection.
2. Run focused tests and confirm RED.
3. Implement deterministic frame matching and global truth/predicted identity mapping, persist immutable reports and truth manifest hashes, and expose API endpoints.
4. Run focused tests plus Phase 3B evaluation regressions; confirm GREEN.
5. Commit: `feat(pose): add identity tracking evaluation`.

### Task 5: Executable Workflow Builder vertical slice

**Files:**
- Modify: `apps/api/reefvision/schemas/workflow_graphs.py`
- Modify: `apps/api/reefvision/services/workflow_graphs.py`
- Modify: `apps/api/reefvision/services/workflow_node_registry_v1.py`
- Modify: `apps/api/reefvision/services/workflow_pose.py`
- Modify: `apps/api/reefvision/services/workflow_review.py`
- Test: `apps/api/reefvision/tests/test_workflow_pose_identity_phase4.py`

**Interfaces:** Add typed executable nodes/artifacts for `pose_identity_association`, `pose_identity_review_gate`, `pose_identity_evaluation`, and `pose_identity_export`. Consume existing `pose_tracks`; emit `pose_identity_tracks`, `reviewed_pose_identity_tracks`, `pose_identity_evaluation`, and export package. Persist settings/run IDs/hashes, support review pause/resume and saved-workflow replay.

1. Write registry/runtime tests for graph type safety, real service execution, progress/cancellation propagation, review pause/resume, evaluation, export, and deterministic saved replay.
2. Run focused tests and confirm RED.
3. Implement definitions, adapters, review readiness, and workflow metadata without changing existing temporal-landmark nodes.
4. Run focused tests plus existing pose workflow suites; confirm GREEN.
5. Commit: `feat(workflow): add multi-animal identity workflow`.

### Task 6: Video Tracking Workspace identity review UI and acceptance

**Files:**
- Create: `apps/web/src/features/video/poseIdentityTrackingApi.ts`
- Create: `apps/web/src/features/video/PoseIdentityReviewPanel.tsx`
- Create: `apps/web/src/features/video/PoseIdentityReviewPanel.test.tsx`
- Modify: `apps/web/src/features/video/VideoTrackingWorkspace.tsx`
- Modify: `apps/web/src/features/video/VideoTrackingWorkspace.test.tsx`
- Modify: `apps/web/src/features/workflows/WorkflowBuilderWorkspace.tsx`
- Test: `apps/web/tests/e2e/pose-identity-tracking.spec.ts`
- Modify: `docs/REEFPOSE_ROADMAP.md`
- Create: `docs/validation/REEFPOSE_PHASE4_VALIDATION.md`

**Interfaces:** Consume Task 3 APIs and Task 5 registry. Display simultaneous skeleton identity labels, run/revision/provenance, per-individual history, low-confidence candidates and score explanations; execute reassign/split/merge/swap/accept/reject and reload persisted correction history. Add Workflow Builder editors for thresholds and evaluation/export inputs.

1. Write component tests for run selection, stable IDs, low-confidence review, correction validation, split/merge/reassign persistence/reload, scientist status, error/cancel states, and retained Ultralytics/legacy tracking behavior.
2. Run focused frontend tests and confirm RED.
3. Implement typed API hooks, review panel, workspace integration, and workflow parameter editors using existing design components/polling.
4. Run focused tests, TypeScript check, lint, build, and Playwright acceptance against the real local API; capture exact evidence and limitations.
5. Run backend focused/full tests, Ruff, mypy, Alembic upgrade/downgrade/upgrade on a disposable database, frontend full tests/build, and compatible CUDA capability/inference smoke tests without bypassing security policy.
6. Update roadmap and validation document with synthetic-vs-biological caveat, GUI evidence, GPU evidence, failures, and remaining work.
7. Commit: `docs(pose): validate ReefPose Phase 4`.

## Review Focus

- Identity switches during visually ambiguous crossings and after gaps must be deterministic and honestly confidence-qualified.
- Corrections must be append-only; no endpoint may silently mutate provider pose output or erase prior revisions.
- Scientist-confirmed state must require an explicit human action and verified truth datasets must be immutable/hash-addressed.
- Evaluation formulas must use independent expected fixtures and must not conflate identity association with landmark localization.
- Workflow nodes must execute backend services, pause/resume correctly, and replay from persisted configuration rather than only advertise types.
- Existing single-animal, Ultralytics, SLEAP, temporal-landmark, Phase 3B evaluation, and video tracking behavior must remain compatible.
