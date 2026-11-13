# ReefPose Phase 5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a durable, species-independent anatomical measurement and biological event-counting system over Phase 4 identity trajectories, with deterministic cycle detection, scientist review, GUI analysis, Workflow Builder execution, and reproducible export.

**Architecture:** Pure domain modules calculate measurement samples and cycle candidates; dedicated `0042` persistence binds immutable runs to exact Phase 4 identity revisions and source hashes. Cancellable background jobs atomically persist calculations, services expose append-only event review and verified packages, and existing Workflow Builder/Video Tracking Workspace surfaces execute the same contracts.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy/Alembic, deterministic standard-library numerical geometry, React 19, TypeScript, TanStack Query, SVG, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-12-reefpose-phase5-design.md`

## Global Constraints

- Remain on `feature/reefpose-core`, starting from `2e1ee52d`; create local commits only.
- Do not push, merge, tag, publish, install dependencies, download weights, or change Windows Application Control.
- Preserve all Phase 1–4 behavior, annotations, SLEAP/Ultralytics providers, verified datasets, and existing scientific measurement/behavior systems.
- Use stable anatomical landmark IDs and source-image coordinates; never silently infer 3D quantities or interpolate extended missing intervals.
- Keep automated/unreviewed/partial events distinct from scientist-confirmed complete events in persistence, UI, summaries, and exports.
- Use synthetic fixtures only for engineering correctness; do not claim manually reviewed agreement or biological validity without research data.
- Coordinate migration head before adding reversible migration `0042`; stop if a conflicting `0042` exists.
- Follow test-first RED→GREEN for every production behavior and commit each task only after its named focused suite passes.

## Review Focus

- A short missing gap inside a cycle must preserve state without interpolation, while a long gap yields one partial/reset; Task 3 tests both.
- A calibration or identity correction after submission must make queued/current results stale and prevent reviewed export; Tasks 4 and 5 test both boundaries.
- Multiple identities sharing frames must never contaminate each other's signals or events; Tasks 2–4 use overlapping multi-animal fixtures.
- Concurrent progress and cancellation must not expose partial measurement/event rows or acquire a blocking SQLite write lock; Task 4 includes a two-session threaded regression.
- Scientist boundary edits must recompute peak/amplitude/duration/confidence and never permit an invalid or cross-series event; Task 4 tests deterministic recomputation.

---

### Task 1: Reversible Phase 5 persistence and contracts

**Files:**
- Create: `apps/api/migrations/versions/0042_pose_biological_measurements.py`
- Create: `apps/api/reefvision/db/models/pose_biological_measurement.py`
- Create: `apps/api/reefvision/schemas/pose_biological_measurement.py`
- Modify: `apps/api/reefvision/db/models/__init__.py`
- Test: `apps/api/reefvision/tests/test_pose_biological_measurement_migration.py`

**Interfaces:**
- Consumes: Phase 4 `PoseIdentityAssociationRun`, `PoseAnimalIdentity`, `PoseIdentityObservation`, `Job`, `Project`, and `VideoAsset` IDs/revisions.
- Produces: ORM models `PoseMeasurementRun`, `PoseMeasurementSeries`, `PoseMeasurementSample`, `PoseEventDetectionRun`, and `PoseBiologicalEventRevision`; Pydantic create/response/correction/export contracts shared by later tasks.

- [ ] **Step 1: Write failing migration/model tests**

  Assert `0041 → 0042 → 0041 → 0042`, preservation of an existing identity run, all five new tables/indexes/foreign keys, append-only revision uniqueness, valid status/revision constraints, and successful Pydantic serialization.

- [ ] **Step 2: Verify RED**

  Run: `python -m pytest apps/api/reefvision/tests/test_pose_biological_measurement_migration.py -q`  
  Expected: FAIL because migration `0042` and models do not exist.

- [ ] **Step 3: Implement migration, ORM models, and schemas**

  Use JSON for immutable definitions/configuration/provenance/quality flags, normalized rows for series/samples/events, `RESTRICT` for scientific sources, owned-run cascades for derived rows, unique `(event_series_id, revision)`, and explicit current-revision indexing.

- [ ] **Step 4: Verify GREEN and compatibility**

  Run: `python -m pytest apps/api/reefvision/tests/test_pose_biological_measurement_migration.py apps/api/reefvision/tests/test_pose_identity_tracking_migration.py apps/api/reefvision/tests/test_mask_migration_lineage.py -q`  
  Expected: PASS.

- [ ] **Step 5: Commit**

  `git commit -m "feat(pose): add biological measurement persistence"`

### Task 2: Generic anatomical measurement engine

**Files:**
- Create: `apps/api/reefvision/domain/pose_anatomical_measurement.py`
- Test: `apps/api/reefvision/tests/test_pose_anatomical_measurement_domain.py`

**Interfaces:**
- Consumes: immutable `AnatomicalObservation`, `AnatomicalLandmark`, `MeasurementDefinition`, `MeasurementCalibration`, and actual observation/fallback timestamps defined in this module.
- Produces: deterministic `MeasurementSeriesResult`, `MeasurementSampleResult`, summary statistics, quality flags, formula versions, and hashes for Task 4 persistence.

- [ ] **Step 1: Write failing geometry/timebase tests**

  Cover hand-calculated distance, joint angle, source-axis orientation, displacement,
  velocity/direction with irregular time deltas, unwrapped angular velocity, ordered-chain
  curvature, relative movement, anatomical extension, calibrated and pixel-only units,
  nonpositive time, dropped frames, visibility/missing/confidence propagation, degenerate
  geometry, maximum gap, source-coordinate rejection, and two-identity isolation.

- [ ] **Step 2: Verify RED**

  Run: `python -m pytest apps/api/reefvision/tests/test_pose_anatomical_measurement_domain.py -q`  
  Expected: FAIL because the domain module does not exist.

- [ ] **Step 3: Implement pure measurement calculation**

  Implement finite-value validation, stable-ID lookup, conservative minimum confidence,
  actual-time derivatives, angle unwrapping, calibration conversion, explicit null samples,
  quality flags, deterministic ordering, and canonical JSON hashing without NumPy.

- [ ] **Step 4: Verify GREEN**

  Run: `python -m pytest apps/api/reefvision/tests/test_pose_anatomical_measurement_domain.py -q`  
  Expected: PASS.

- [ ] **Step 5: Commit**

  `git commit -m "feat(pose): calculate anatomical movement series"`

### Task 3: Deterministic biological event and cycle detector

**Files:**
- Create: `apps/api/reefvision/domain/pose_biological_events.py`
- Test: `apps/api/reefvision/tests/test_pose_biological_events_domain.py`

**Interfaces:**
- Consumes: scalar `EventSignalSample` sequences and immutable `CycleDefinition` with hysteresis, amplitude, duration, separation, refractory, confidence, gap, smoothing, and partial policies.
- Produces: deterministic `BiologicalEventCandidate` records plus per-series count/amplitude/frequency summaries and result/configuration hashes for Task 4.

- [ ] **Step 1: Write failing state-machine tests**

  Cover one cycle, consecutive variable-speed cycles, sustained open state counted once,
  start/end partials, below-threshold amplitude, duration/separation/refractory rejection,
  noisy signals with none/mean/median smoothing, short missing gap state preservation,
  long missing/occlusion partial reset, irregular timestamps, low confidence, identity
  separation, deterministic tie/peak behavior, and documented cycle definition validation.

- [ ] **Step 2: Verify RED**

  Run: `python -m pytest apps/api/reefvision/tests/test_pose_biological_events_domain.py -q`  
  Expected: FAIL because the event module does not exist.

- [ ] **Step 3: Implement deterministic smoothing and hysteresis state machine**

  Smooth only contiguous valid segments, preserve but never interpolate bounded gaps,
  track start/peak/end from observed samples, persist diagnostic rejections, count only
  qualifying complete candidates, and calculate frequency from valid evaluated duration.

- [ ] **Step 4: Verify GREEN**

  Run: `python -m pytest apps/api/reefvision/tests/test_pose_biological_events_domain.py -q`  
  Expected: PASS.

- [ ] **Step 5: Commit**

  `git commit -m "feat(pose): detect biological movement cycles"`

### Task 4: Provenance service, jobs, API, review, and exports

**Files:**
- Create: `apps/api/reefvision/services/pose_biological_measurement.py`
- Create: `apps/api/reefvision/jobs/pose_biological_measurement.py`
- Create: `apps/api/reefvision/api/routes/pose_biological_measurement.py`
- Modify: `apps/api/reefvision/api/router.py`
- Modify: `apps/api/reefvision/jobs/worker.py`
- Modify: `apps/api/reefvision/services/jobs.py`
- Test: `apps/api/reefvision/tests/test_pose_biological_measurement_api.py`
- Test: `apps/api/reefvision/tests/test_pose_biological_measurement_jobs.py`
- Test: `apps/api/reefvision/tests/test_pose_biological_measurement_export.py`

**Interfaces:**
- Consumes: Task 1 models/schemas, Task 2 engine, Task 3 detector, Phase 4 current observations/revisions, `VideoScienceService` calibration snapshots, and canonical Job lifecycle.
- Produces: REST/job contracts for submitting and reading measurement/event runs, retrieving series/samples/events/summaries, append-only corrections, stale/readiness status, and self-verifying managed JSON/CSV packages used by Tasks 5–6.

- [ ] **Step 1: Write failing vertical-service/API tests**

  Build a synthetic two-identity fish fixture and assert queued measurement execution,
  pixel-only/calibrated gape distance, timestamp provenance, event submission/counts,
  exploratory labeling, reviewed event history, boundary recomputation, manual add/remove,
  partial disposition, summaries, immutable source observations, and API errors.

- [ ] **Step 2: Write failing integrity/lifecycle tests**

  Assert queued manifest revalidation after identity/calibration/video changes, stale read
  reporting, reviewed-export refusal, failure/cancellation atomic rollback, externally
  visible progress with concurrent cancellation, startup recovery compatibility, no
  duplicate current revisions, cross-series correction rejection, and deterministic
  result/package hashes.

- [ ] **Step 3: Verify RED**

  Run: `python -m pytest apps/api/reefvision/tests/test_pose_biological_measurement_api.py apps/api/reefvision/tests/test_pose_biological_measurement_jobs.py apps/api/reefvision/tests/test_pose_biological_measurement_export.py -q`  
  Expected: FAIL because services/routes/jobs do not exist.

- [ ] **Step 4: Implement service, worker dispatch, API, corrections, and exports**

  Revalidate canonical manifests at submission/execution/export; assign IDs in memory;
  publish progress/cancellation through short transactions; commit scientific outputs
  atomically; deterministically recompute edited event metrics; expose audit history; and
  write JSON plus ZIP CSV package with per-file hashes and verification manifest.

- [ ] **Step 5: Verify GREEN plus Phase 4/job regressions**

  Run: `python -m pytest apps/api/reefvision/tests/test_pose_biological_measurement_api.py apps/api/reefvision/tests/test_pose_biological_measurement_jobs.py apps/api/reefvision/tests/test_pose_biological_measurement_export.py apps/api/reefvision/tests/test_pose_identity_tracking_api.py apps/api/reefvision/tests/test_pose_identity_tracking_job.py apps/api/reefvision/tests/test_worker_resilience.py -q`  
  Expected: PASS.

- [ ] **Step 6: Commit**

  `git commit -m "feat(pose): expose biological movement analysis"`

### Task 5: Executable Workflow Builder integration

**Files:**
- Modify: `apps/api/reefvision/schemas/workflow_graphs.py`
- Modify: `apps/api/reefvision/services/workflow_node_registry_v1.py`
- Modify: `apps/api/reefvision/services/workflow_pose.py`
- Modify: `apps/api/reefvision/services/workflow_review.py`
- Modify: `apps/web/src/features/workflow-graphs/workflowTemplates.ts`
- Modify: `apps/web/src/features/workflow-graphs/workflowTemplates.test.ts`
- Test: `apps/api/reefvision/tests/test_workflow_pose_biological_measurement_phase5.py`

**Interfaces:**
- Consumes: Task 4 real jobs/services and reviewed Phase 4 identity artifacts.
- Produces: executable typed nodes/artifacts `anatomical_measurement`, `biological_event_detection`, `biological_event_review_gate`, and `biological_movement_export`, with workflow child provenance/cancellation and saved replay.

- [ ] **Step 1: Write failing registry/runtime/replay tests**

  Assert typed ports and required parameters, real child-job execution, persisted workflow
  IDs, exact configuration hashes, review pause/readiness/resume, parent cancellation,
  failed-child reporting, stale artifact rejection, managed export, and saved replay.

- [ ] **Step 2: Verify RED**

  Run: `python -m pytest apps/api/reefvision/tests/test_workflow_pose_biological_measurement_phase5.py -q`  
  Expected: FAIL because Phase 5 nodes are unregistered.

- [ ] **Step 3: Implement adapters, review status, registry, and template**

  Invoke Task 4 jobs rather than duplicating calculations; require reviewed identity input
  in the scientific template; carry run/revision/hash/job/workflow provenance; pause until
  every retained candidate is disposed; and reject stale/unreviewed export.

- [ ] **Step 4: Verify GREEN plus preserved pose workflows**

  Run: `python -m pytest apps/api/reefvision/tests/test_workflow_pose_biological_measurement_phase5.py apps/api/reefvision/tests/test_workflow_pose_identity_phase4.py apps/api/reefvision/tests/test_workflow_pose_runtime_phase10.py apps/api/reefvision/tests/test_workflow_pose_review_resume_phase10.py -q`  
  Expected: PASS.

- [ ] **Step 5: Run frontend template test**

  Run: `npm test -- --run src/features/workflow-graphs/workflowTemplates.test.ts` in `apps/web`  
  Expected: PASS.

- [ ] **Step 6: Commit**

  `git commit -m "feat(workflow): add biological movement pipeline"`

### Task 6: Biological Movement Workspace GUI

**Files:**
- Create: `apps/web/src/features/video/biologicalMovementApi.ts`
- Create: `apps/web/src/features/video/BiologicalMovementPanel.tsx`
- Create: `apps/web/src/features/video/BiologicalMovementPanel.test.tsx`
- Modify: `apps/web/src/features/video/VideoTrackingWorkspace.tsx`
- Modify: `apps/web/src/features/video/VideoTrackingWorkspace.test.tsx`

**Interfaces:**
- Consumes: Task 4 APIs and existing Video Tracking Workspace project/video/frame/track context.
- Produces: real measurement/event configuration, polling/cancellation, identity-specific SVG time series, missing gaps, confidence/threshold/event markers, summaries, frame navigation, append-only review controls/history, reload persistence, and export actions.

- [ ] **Step 1: Write failing component/integration tests**

  Assert stable-ID landmark configuration, identity/run switching, distance and angle
  validation, pixel/calibrated labels, job progress/cancel/reload, chart gaps and markers,
  candidate versus confirmed labeling, event-to-frame navigation, accept/reject/boundary
  adjustment/manual add/remove, derived-value refresh, stale errors, correction history,
  summary counts/frequency, and Phase 4 panel compatibility.

- [ ] **Step 2: Verify RED**

  Run: `npm test -- --run src/features/video/BiologicalMovementPanel.test.tsx src/features/video/VideoTrackingWorkspace.test.tsx` in `apps/web`  
  Expected: FAIL because the panel and API do not exist.

- [ ] **Step 3: Implement API client, accessible SVG chart, and workspace integration**

  Reuse local styling/components; never connect invalid samples; bind cancellation to the
  selected active run; use persisted API state as authority; and keep all automated,
  partial, rejected, and scientist-confirmed labels explicit.

- [ ] **Step 4: Verify GREEN and frontend quality gates**

  Run: `npm test -- --run src/features/video/BiologicalMovementPanel.test.tsx src/features/video/VideoTrackingWorkspace.test.tsx`  
  Run: `npm run typecheck`  
  Run: `npm run format:check`  
  Expected: PASS.

- [ ] **Step 5: Commit**

  `git commit -m "feat(pose): add biological movement workspace"`

### Task 7: Live acceptance, regression validation, and roadmap

**Files:**
- Create: `apps/web/tests/e2e/reefpose-phase5-live.spec.ts`
- Create: `docs/reefpose/phase5-validation.md`
- Modify: `docs/reefpose/roadmap.md`

**Interfaces:**
- Consumes: Tasks 1–6 completed vertical slice.
- Produces: reproducible fish-gape acceptance evidence, final validation record, updated roadmap, and exact final-report facts.

- [ ] **Step 1: Write the guarded live acceptance test**

  Through the rendered GUI and production APIs: create/open a synthetic verified pose
  video, produce one identity with gape landmarks, configure distance, calculate a plotted
  time series, detect a known number of cycles including one partial, navigate to an event,
  adjust/accept it, reload and confirm revision history, export, replay, and verify hashes.

- [ ] **Step 2: Run focused backend and frontend suites**

  Run all Phase 5 backend tests plus Phase 4 identity/workflow tests.  
  Run: `npm test -- --run` in `apps/web`.  
  Expected: all applicable tests pass; opt-in/optional skips are documented.

- [ ] **Step 3: Run static, migration, build, and CPU checks**

  Run Ruff, strict mypy, TypeScript, Prettier, production Vite build, disposable Alembic
  `0041→0042→0041→0042`, and a CPU synthetic measurement/event benchmark. GPU is reported
  as not applicable to deterministic scalar analysis; verify upstream CUDA availability
  without rerunning or downloading a model unless an existing opt-in test requires it.

- [ ] **Step 4: Exercise live Chromium acceptance**

  Run the guarded Phase 5 Playwright test against isolated Vite/API/worker services and
  capture run IDs, event counts, correction revision, export hash, and timing. Do not claim
  GUI acceptance unless this real test passes.

- [ ] **Step 5: Run repository-wide backend regression**

  Run: `python -m pytest -q --basetemp <short-Windows-path>`  
  Expected: no introduced failures; known absent optional SLEAP runtime failures are
  distinguished by exact test name.

- [ ] **Step 6: Update validation and roadmap**

  Record computational/workflow evidence separately from unvalidated manual agreement and
  biological validity. Recommend the next milestone from observed limitations.

- [ ] **Step 7: Commit**

  `git commit -m "docs(pose): validate ReefPose Phase 5"`

