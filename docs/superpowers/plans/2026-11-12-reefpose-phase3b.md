# ReefPose Phase 3B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver recoverable asynchronous, provider-neutral pose evaluation and comparison through Model Hub and Workflow Builder with reproducible scientific exports.

**Architecture:** The existing `Job` record is the durable comparison aggregate and each successfully evaluated model remains an immutable `PoseEvaluationRun`. A provider-normalization layer converts ReefPose and schema-bound Ultralytics output to stable-ID source-pixel poses, while unsupported optional SLEAP execution becomes a structured exclusion. The normal worker, job polling/cancellation, and Workflow runtime execute the same comparison service.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/Alembic, PyTorch/Ultralytics optional adapters, React 19, TypeScript, TanStack Query, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-11-12-reefpose-phase3b-design.md`

## Global Constraints

- Work only on `feature/reefpose-core` from `50ecd1b2fa5bb7c5bb1fa06f5d2a514cd45bd768`.
- Preserve Phase 2C/3A, synchronous evaluation, provider, dataset, annotation, and workflow contracts.
- No dependency installation, pretrained download, security-control change, push, merge, tag, or publish.
- Keep framework imports in ML adapters and source-image coordinates in pixels.
- Use immutable verified pose datasets and fail closed on leakage or integrity changes.
- Use TDD for every behavior and add migration `0040` rather than editing `0039`.
- Synthetic fixtures are engineering evidence, never biological validation.

## Review Focus

- Two simultaneous identical submissions must produce one active job; Task 1 tests the unique deduplication race path.
- A recovered job must not reuse a stale or tampered child run; Task 3 tests every reuse identity and result hash.
- Provider confidence must not be mislabeled as visibility; Task 2 tests Ultralytics metric availability and missing/multiple detections.
- Workflow cancellation must reach the active comparison child; Task 4 tests both workflow identity fields and cooperative cancellation.
- Reloaded Model Hub state must rediscover active/completed comparisons and render only persisted values; Task 5 tests polling hydration and chart inputs.

---

### Task 1: Durable asynchronous comparison submission

**Files:**
- Create: `apps/api/migrations/versions/0040_job_deduplication_key.py`
- Modify: `apps/api/reefvision/db/models/job.py`
- Modify: `apps/api/reefvision/schemas/pose_evaluation.py`
- Create: `apps/api/reefvision/services/pose_evaluation_comparison.py`
- Modify: `apps/api/reefvision/api/routes/pose_evaluation.py`
- Modify: `apps/api/reefvision/tests/test_mask_migration_lineage.py`
- Create: `apps/api/reefvision/tests/reefpose/test_evaluation_jobs.py`

**Interfaces:**
- Produces: `PoseEvaluationComparisonCreateRequest`, `PoseEvaluationComparisonResponse`, `PoseEvaluationComparisonService.submit/list/get`.
- Produces: nullable `Job.deduplication_key: str | None` with a unique index.
- Consumes later: job request schema `pose-evaluation-comparison-0001` and canonical `request_sha256`.

- [ ] **Step 1: Write failing API/service tests**

Test that valid one/multi-model submission returns `202 JobResponse`, records exact configuration/provenance, rejects duplicate IDs, foreign/non-pose/schema-mismatched/leaking models, paginates project jobs, and returns the same active job for the same order-independent request identity. Exercise a simulated unique-index collision and assert one job survives.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest apps/api/reefvision/tests/reefpose/test_evaluation_jobs.py -q`

Expected: failures because comparison schemas, routes, service, and deduplication column do not exist.

- [ ] **Step 3: Add migration and minimal submission/list/detail implementation**

Implement `Job.deduplication_key`, migration `0040`, bounded unique model IDs, bounded threshold arrays, compatibility/leakage preflight, canonical request hashing, active-job lookup, unique-race handling, `202` submission, and paginated list/detail routes. Preserve the synchronous route unchanged.

- [ ] **Step 4: Verify GREEN and migration round trip**

Run the focused test, then upgrade `0039 -> 0040`, downgrade `0040 -> 0039`, and upgrade again against an isolated SQLite database.

- [ ] **Step 5: Commit**

Commit message: `feat: queue pose evaluation comparisons`

### Task 2: Provider-neutral normalized inference and scientific distributions

**Files:**
- Create: `apps/api/reefvision/ml/pose_evaluation.py`
- Modify: `apps/api/reefvision/domain/pose_evaluation.py`
- Modify: `apps/api/reefvision/services/pose_evaluation.py`
- Modify: `apps/api/reefvision/tests/reefpose/test_evaluation_metrics.py`
- Create: `apps/api/reefvision/tests/reefpose/test_evaluation_providers.py`
- Modify: `apps/api/reefvision/tests/reefpose/test_evaluation_service.py`

**Interfaces:**
- Produces: `NormalizedPosePrediction`, `NormalizedLandmarkPrediction`, `PoseEvaluationRuntime`, and `create_pose_evaluation_runtime(model, checkpoint_path, schema, device)`.
- Produces: deterministic normalized-error distribution bins/quantiles and structured metric availability.
- Consumes: exact `PoseModelSchemaBinding`/revision for external providers and ReefPose native integrity metadata.

- [ ] **Step 1: Write failing hand-calculated metric/distribution tests**

Assert literal bin counts, overflow, sample count, min/quartiles/median/max, empty-distribution behavior, and stable per-landmark values. Assert availability objects mark OKS and visibility unavailable with reasons when prerequisites/semantics are absent.

- [ ] **Step 2: Run metric tests and verify RED**

Run: `python -m pytest apps/api/reefvision/tests/reefpose/test_evaluation_metrics.py -q`

- [ ] **Step 3: Implement deterministic distribution and availability output**

Add fixed normalized-error edges and hand-defined quantile interpolation without framework dependencies. Keep existing metric fields backward compatible.

- [ ] **Step 4: Write failing provider tests**

Use fake framework objects at the import boundary to assert ReefPose stable IDs/native hash, Ultralytics exact schema-order mapping/source coordinates, zero-detection misses, multiple-animal incompatibility, landmark-count mismatch, unavailable visibility semantics, and `sleap_nn` structured runtime exclusion without importing SLEAP.

- [ ] **Step 5: Run provider tests and verify RED**

Run: `python -m pytest apps/api/reefvision/tests/reefpose/test_evaluation_providers.py -q`

- [ ] **Step 6: Implement the minimal adapters and refactor evaluator consumption**

Move framework-specific prediction conversion behind `PoseEvaluationRuntime`. Add optional cancellation/progress callbacks to `PoseEvaluationService.create`, retain lazy imports, and preserve the synchronous ReefPose API behavior.

- [ ] **Step 7: Verify GREEN and existing synchronous regressions**

Run provider, metric, and service tests together.

- [ ] **Step 8: Commit**

Commit message: `feat: normalize pose evaluation providers`

### Task 3: Worker lifecycle, recovery, comparison aggregation, and exports

**Files:**
- Create: `apps/api/reefvision/jobs/pose_evaluation.py`
- Modify: `apps/api/reefvision/jobs/worker.py`
- Modify: `apps/api/reefvision/services/jobs.py`
- Modify: `apps/api/reefvision/services/models.py`
- Modify: `apps/api/reefvision/services/pose_evaluation_comparison.py`
- Modify: `apps/api/reefvision/api/routes/pose_evaluation.py`
- Modify: `apps/api/reefvision/schemas/pose_evaluation.py`
- Modify: `apps/api/reefvision/tests/reefpose/test_evaluation_jobs.py`
- Modify: `apps/api/reefvision/tests/reefpose/test_evaluation_service.py`
- Test: `apps/api/reefvision/tests/test_models.py`

**Interfaces:**
- Produces: `process_pose_evaluation_job(settings, factory, job_id) -> bool`.
- Produces: consolidated report schema `reefvision-pose-comparison-0001`, JSON export, and CSV row types `aggregate|landmark|exclusion`.
- Produces: cooperative frame/model cancellation and exact completed-child reuse validation.

- [ ] **Step 1: Write failing lifecycle tests**

Assert queued-to-running-to-succeeded progress, cancellation between frames, queued cancellation, interruption recovery/re-entry, partial results on later-model failure, explicit provider exclusion, and deduplication-key clearing only at terminal status.

- [ ] **Step 2: Run lifecycle tests and verify RED**

Run: `python -m pytest apps/api/reefvision/tests/reefpose/test_evaluation_jobs.py -q`

- [ ] **Step 3: Implement worker dispatch and cooperative lifecycle**

Register `pose_evaluation` in the worker and cancellable job set. Persist stage/progress/result after every frame/model, preserve completed child IDs, clear the active key transactionally at terminal status, and use generic startup requeue recovery.

- [ ] **Step 4: Write failing recovery/reuse and export tests**

Assert reuse only for exact completed child identity/configuration/result hash; altered checkpoint, dataset, schema, config, status, or result prevents reuse. Assert JSON canonical hash and literal CSV columns/row types for completed, excluded, cancelled-partial, and failed-partial reports.

- [ ] **Step 5: Implement aggregation and exports**

Build structured availability cells, denominator mismatch warnings, model/provider/checkpoint identities, configuration, runtime/software/hardware provenance, exclusions, integrity metadata, and canonical report SHA.

- [ ] **Step 6: Add model deletion conflict test and fix**

Prove deleting a model referenced by `PoseEvaluationRun` returns a structured conflict instead of a database integrity error, then add the minimal service guard.

- [ ] **Step 7: Verify GREEN plus worker/job/model regressions**

Run the full ReefPose directory plus focused job/worker/model tests.

- [ ] **Step 8: Commit**

Commit message: `feat: execute recoverable pose comparisons`

### Task 4: Executable Workflow Builder evaluation node

**Files:**
- Modify: `apps/api/reefvision/services/workflow_node_registry_v1.py`
- Modify: `apps/api/reefvision/services/workflow_graphs.py`
- Create: `apps/api/reefvision/services/workflow_pose_evaluation.py`
- Modify: `apps/api/reefvision/services/workflow_v1_install.py`
- Modify: `apps/api/reefvision/jobs/workflow.py`
- Create: `apps/api/reefvision/tests/test_workflow_pose_evaluation_phase3b.py`
- Modify: `apps/web/src/features/workflow-graphs/WorkflowVisualEditor.tsx`
- Modify: `apps/web/src/features/workflow-graphs/workflowTemplates.ts`
- Modify: `apps/web/src/features/workflow-graphs/WorkflowVisualEditor.test.tsx`
- Modify: `apps/web/src/features/workflow-graphs/workflowTemplates.test.ts`

**Interfaces:**
- Produces: node type `pose_model_evaluation` with dataset input, multiple model input, and comparison output.
- Produces: runtime adapter emitting `pose_evaluation_comparison` with job/run IDs, report hash, metrics, exclusions, warnings, and provenance.

- [ ] **Step 1: Write failing registry/graph/execution tests**

Assert typed ports and `multiple=True`, configuration persistence, schema/checksum replay rejection, real child worker execution, artifact provenance, cancellation propagation with both workflow IDs, failure reporting, and saved-workflow replay.

- [ ] **Step 2: Run workflow tests and verify RED**

Run: `python -m pytest apps/api/reefvision/tests/test_workflow_pose_evaluation_phase3b.py -q`

- [ ] **Step 3: Implement registry and runtime adapter**

Install the adapter through the existing V1 extension mechanism, create/process one child comparison job through production code, and emit a typed immutable workflow artifact.

- [ ] **Step 4: Write failing frontend node-editor/template tests**

Assert dataset/model bindings, multiple model selection, thresholds/device controls, saved graph serialization, and replayed configuration.

- [ ] **Step 5: Implement the minimal editor controls and template**

Reuse existing node parameter components and add a Dataset → Pose Evaluation/Comparison template path without placeholder execution.

- [ ] **Step 6: Verify GREEN and existing workflow suites**

Run backend pose workflow suites and focused frontend workflow tests.

- [ ] **Step 7: Commit**

Commit message: `feat: add pose comparison workflow node`

### Task 5: Model Hub comparison workspace

**Files:**
- Create: `apps/web/src/features/models/PoseEvaluationComparisonPanel.tsx`
- Create: `apps/web/src/features/models/PoseEvaluationComparisonPanel.test.tsx`
- Modify: `apps/web/src/features/models/ModelManager.tsx`
- Modify: `apps/web/src/features/models/ModelManager.test.tsx`
- Modify: `apps/web/src/api/client.ts`
- Modify: `apps/web/src/styles.css`

**Interfaces:**
- Consumes: paginated comparison jobs, `JobRecord` polling, comparison detail/report, cancel, and export URLs.
- Produces: accessible multi-model selection, dataset selection, progress, cancellation, metric table, persisted charts, exclusions, warnings, and exports.

- [ ] **Step 1: Write failing API-client and panel tests**

Assert multi-model/dataset payload, active-job rediscovery after mount, polling until terminal, cancel, exact schema/leakage filtering, comparative metrics, `Not available` reasons, persisted per-landmark/distribution/calibration chart values, scientific limitations, and JSON/CSV links.

- [ ] **Step 2: Run focused frontend tests and verify RED**

Run: `npm test -- PoseEvaluationComparisonPanel.test.tsx ModelManager.test.tsx`

- [ ] **Step 3: Implement typed client and comparison panel**

Use TanStack Query and existing job polling/cancellation. Use accessible HTML/SVG/CSS only; do not add a chart dependency. Replace the per-card synchronous-only interaction with the dedicated comparison panel while retaining historical single-run display compatibility.

- [ ] **Step 4: Verify GREEN, typecheck, and build**

Run focused tests, `npm run format:check`, `npm run typecheck`, and `npm run build`.

- [ ] **Step 5: Commit**

Commit message: `feat: add Model Hub pose comparison`

### Task 6: Validation, GPU evidence, roadmap, and Phase 4 design

**Files:**
- Create: `docs/reefpose/phase3b-validation.md`
- Create: `docs/superpowers/specs/2026-11-12-reefpose-phase4-multi-animal-design.md`
- Modify: relevant ReefPose roadmap/readme if one exists after audit.

**Interfaces:**
- Consumes: all Phase 3B APIs, UI, workflow artifacts, reports, and test evidence.
- Produces: auditable validation record and design-only Phase 4 handoff.

- [ ] **Step 1: Run backend formatting, linting, typing, migration, focused, and full suites**

Use a short Windows temp root and worktree-pinned `PYTHONPATH`; run optional runtime suites only when their pinned dependencies are present. Record unrelated pre-existing findings separately.

- [ ] **Step 2: Run frontend format, type, full Vitest, production build, and relevant Playwright tests**

Exercise the actual comparison workflow in the GUI when a runnable desktop/browser fixture exists; otherwise distinguish component evidence from manual GUI acceptance.

- [ ] **Step 3: Run RTX 3090 synthetic engineering validation**

Evaluate at least two compatible synthetic registered models asynchronously on CUDA when possible, capture progress, report hash, latency/throughput/peak memory, and inference from a registered result. Do not modify the blocked PyTorch 2.11+cu128 environment.

- [ ] **Step 4: Write validation and Phase 4 design documents**

Record commands/counts/failures, provider exclusions, GUI evidence, limitations, roadmap status, and a non-implementation design for pose-aware association, stable IDs, gap/occlusion handling, manual correction, IDF1, and identity-switch analysis.

- [ ] **Step 5: Run final diff/integrity review and commit**

Commit message: `docs: validate ReefPose Phase 3B`
