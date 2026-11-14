# ReefPose Phase 2A Native Training Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute native ReefPose-S training from ReefVision's immutable pose datasets through the existing Workflow Builder and register the completed checkpoint for inference.

**Architecture:** Extend the existing pose workflow contract with a backward-compatible provider selector, dispatch the existing job to an isolated native adapter for ReefPose, and generalize the existing trained-pose registration path. Reuse the frozen export, run/job, workflow artifact, and Model Hub systems.

**Tech Stack:** Python 3.12, SQLAlchemy, PyTorch 2.11/CUDA 12.8, FastAPI services, pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-reefpose-phase2a-design.md`

## Global Constraints

- Work only on `feature/reefpose-core`; commit locally and do not push, merge, tag, or publish.
- Preserve Phase 1, SLEAP, Ultralytics, annotations, and immutable verified datasets.
- Do not download pretrained weights or silently install dependencies.
- Synthetic fixtures validate engineering behavior only, not scientific accuracy.
- Use the existing `pose_model_training` and `register_trained_model` nodes and existing persistence models.

## Review Focus

- Provider omitted in an old saved workflow must still execute Ultralytics with byte-for-byte compatible defaults; Task 1 tests this registry/service path.
- A provider change during saved-workflow replay must not reuse another provider's completed run; Task 1 tests recovery identity.
- Dataset or schema mutation between queue and execution must fail before training; Task 2 tests execution-time revalidation.
- Cancelled/failed native training must retain resume evidence but expose no registrable result checkpoint; Task 2 and Task 3 test this boundary.
- A registered ReefPose best checkpoint must load through the provider and restore source-image coordinates; Task 3 tests registration plus inference.

---

### Task 1: Provider-neutral workflow contract

**Files:**
- Modify: `apps/api/reefvision/services/workflow_pose_training.py`
- Modify: `apps/api/reefvision/services/workflow_node_registry_v1.py`
- Modify: `apps/api/reefvision/services/workflow_graphs.py`
- Test: `apps/api/reefvision/tests/test_workflow_reefpose_training_phase2a.py`
- Test: `apps/api/reefvision/tests/test_workflow_pose_training_phase10.py`

**Interfaces:**
- Consumes: existing `PoseTrainingDataset`, `TrainingRun`, `process_pose_training_job`, and workflow artifact contracts.
- Produces: provider-specific validated `TrainingRun` records with `provider_id in {"ultralytics", "reefpose"}` and replay identity including provider.

- [ ] Write failing tests for ReefPose random initialization, exact architecture/config validation, provider-matched registered seeds, replay provider identity, and unchanged omitted-provider Ultralytics defaults.
- [ ] Run the focused tests and verify they fail because ReefPose is rejected or hardcoded to Ultralytics.
- [ ] Add provider-specific defaults/validation and persist provider provenance while retaining the existing ports and Ultralytics behavior.
- [ ] Run the focused tests and verify they pass.
- [ ] Commit the provider-neutral contract milestone.

### Task 2: Native ReefPose execution adapter

**Files:**
- Create: `apps/api/reefvision/jobs/reefpose_training.py`
- Modify: `apps/api/reefvision/jobs/pose_training.py`
- Modify: `apps/api/reefvision/ml/reefpose/training.py`
- Test: `apps/api/reefvision/tests/test_workflow_reefpose_training_phase2a.py`
- Test: `apps/api/reefvision/tests/reefpose/test_training_inference.py`

**Interfaces:**
- Consumes: Task 1's persisted provider/config contract, `PoseTrainingExportService`, `load_reefvision_pose_export`, `ReefPoseDataset`, `ReefPoseTrainer`, and managed project storage.
- Produces: `process_reefpose_training_job(settings, factory, job_id) -> bool`, per-epoch progress callbacks, resumable cancellation state, and successful run/job artifacts compatible with workflow registration.

- [ ] Write failing tests for native execution, execution-time dataset/schema validation, progress, cancellation without finalization, resume/historical-best preservation, failure rollback, and immutable source preservation.
- [ ] Run the focused tests and verify the public processor cannot execute ReefPose.
- [ ] Add an epoch callback to the Phase 1 trainer without changing its checkpoint semantics.
- [ ] Implement the native adapter and provider dispatch, including frozen export validation, loaders, progress/cancellation, resume, metrics, logs, provenance, and final best checkpoint.
- [ ] Run the native and Phase 1 training tests and verify they pass.
- [ ] Commit the native execution milestone.

### Task 3: Model Hub registration, inference, and workflow replay

**Files:**
- Modify: `apps/api/reefvision/services/semantic_models.py`
- Modify: `apps/api/reefvision/services/workflow_training.py` if shared registration metadata requires provider-neutral wording only.
- Test: `apps/api/reefvision/tests/test_workflow_reefpose_training_phase2a.py`
- Test: `apps/api/reefvision/tests/reefpose/test_provider.py`

**Interfaces:**
- Consumes: completed Task 2 run artifacts and the existing registration/inference provider hub.
- Produces: a schema-bound ReefPose `ModelRegistration` returned as a `model_reference`, loadable by the existing native provider for inference.

- [ ] Write failing tests for successful ReefPose registration/inference, failed/cancelled registration rejection, exact checkpoint/schema provenance, and saved-workflow replay through registration.
- [ ] Run the focused tests and verify registration rejects the ReefPose provider.
- [ ] Generalize pose registration to the completed run's supported provider while preserving all existing immutable provenance checks.
- [ ] Run ReefPose, registration, workflow replay, and Ultralytics compatibility tests.
- [ ] Commit the Model Hub/workflow vertical-slice milestone.

### Task 4: Regression, CUDA validation, and operational documentation

**Files:**
- Create: `docs/reefpose/phase2a-validation.md`
- Modify: `README.md` or existing ReefPose integration documentation only if it already owns Workflow Builder guidance.
- Test: focused backend suites and executable CUDA validation command.

**Interfaces:**
- Consumes: completed native vertical slice.
- Produces: reproducible test/GPU evidence and documented optional-dependency versus regression classification.

- [ ] Run formatting, type checks, focused backend/Phase 1 tests, and existing Ultralytics workflow tests; fix introduced regressions via RED-GREEN cycles.
- [ ] Run a short synthetic CUDA workflow on the RTX 3090, register its best checkpoint, and run provider inference; record device, versions, peak memory, status IDs, checkpoint hash, and inference output shape.
- [ ] Run the broader repository checks and classify remaining failures as optional-environment gaps or actual regressions.
- [ ] Write validation documentation clearly stating that biological accuracy is unvalidated.
- [ ] Commit the validation/documentation milestone.
