# ReefPose Scientific Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Deliver a coherent native ReefPose held-out evaluation slice with defensible metrics, persisted provenance, exports, and Model Hub access.

**Architecture:** Keep mathematical scoring in a framework-free domain module. The service validates immutable dataset/model/schema provenance, extracts exact frozen frames, invokes the native predictor, persists immutable results, and exposes typed API responses. The frontend consumes only those persisted results.

**Tech Stack:** Python 3.11+, Pydantic, SQLAlchemy/Alembic, FastAPI, PyTorch/OpenCV, React/TypeScript, TanStack Query, Vitest/pytest.

---

### Task 1: Scientific pose metrics

**Files:**
- Create: `apps/api/reefvision/domain/pose_evaluation.py`
- Test: `apps/api/reefvision/tests/reefpose/test_evaluation_metrics.py`

1. Write independently calculable failing tests for exact Euclidean errors, PCK thresholds, NME, per-landmark aggregation, missing/occluded landmarks, visibility metrics, Brier/ECE/threshold curves, and valid/invalid OKS.
2. Run the focused test and confirm RED due to the missing module.
3. Implement immutable metric input/output dataclasses and scoring functions with finite-value validation.
4. Run the focused test GREEN and commit.

### Task 2: Persisted held-out evaluation API

**Files:**
- Create: `apps/api/reefvision/db/models/pose_evaluation.py`
- Create: `apps/api/migrations/versions/0039_pose_evaluation_runs.py`
- Create: `apps/api/reefvision/schemas/pose_evaluation.py`
- Create: `apps/api/reefvision/services/pose_evaluation.py`
- Create: `apps/api/reefvision/api/routes/pose_evaluation.py`
- Modify: model exports and API router
- Test: `apps/api/reefvision/tests/reefpose/test_evaluation_service.py`

1. Write failing API/service tests for a completed synthetic run, exact persisted provenance, schema mismatch, training/evaluation leakage, JSON/CSV export, and failed inference rollback.
2. Add the evaluation-run model and migration without changing applied migrations.
3. Implement exact-frame loading and native ReefPose evaluation with injectable predictor/frame loader seams for engineering tests.
4. Persist only complete results transactionally and expose create/list/detail/export routes.
5. Run focused tests and migration upgrade/downgrade checks GREEN; commit.

### Task 3: Model Hub evaluation controls

**Files:**
- Modify: `apps/web/src/api/client.ts`
- Modify: `apps/web/src/features/models/ModelManager.tsx`
- Modify: `apps/web/src/features/models/ModelManager.test.tsx`

1. Write failing frontend tests for ReefPose-only evaluation action, held-out dataset selection, configuration validation, run result metrics/warnings, and export links.
2. Add typed API methods and a compact evaluation panel reusing Model Hub cards.
3. Run focused tests, full frontend tests/typecheck/build, and commit.

### Task 4: Phase validation and documentation

**Files:**
- Create: `docs/reefpose/phase3-scientific-evaluation-validation.md`

1. Run Ruff format/check, mypy, focused and repository backend suites (classifying optional dependency failures), frontend formatting/typecheck/tests/build, and relevant migration checks.
2. Run CPU and RTX 3090 synthetic evaluation evidence without claiming scientific accuracy.
3. Exercise the browser Model Hub flow against actual local services when feasible and record the exact boundary of acceptance.
4. Request independent branch review, fix Important findings with regression tests, commit final validated milestone, and report remaining Phase 3 work.

## Review Focus

- Missing predictions must not be silently excluded from PCK/calibration.
- Normalization and OKS assumptions must be explicit and validated.
- Stable landmark identity, schema revision, and content hashes must remain exact.
- A model must not evaluate against its own recorded training dataset/manifest.
- Failed or partial runs must not appear as completed scientific results.
- Synthetic fixtures must remain labeled engineering validation only.
