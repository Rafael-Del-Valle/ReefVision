# ReefPose Phase 2B GUI Implementation Plan

**Spec:** `docs/superpowers/specs/2026-11-07-reefpose-phase2b-design.md`

## Global constraints

- Work only on `feature/reefpose-core`; preserve Phase 1/2A and Ultralytics behavior.
- Reuse existing Workflow Builder, training, Model Hub, video inference, and annotation-review systems.
- Use TDD for every behavior change and commit validated milestones locally.
- Do not download pretrained weights or modify the lockfile unnecessarily.

## Task 1 — Runtime and registered-model GUI contracts

**Files:** `apps/api/reefvision/ml/provider_hub.py`, `apps/api/reefvision/schemas/models.py`, `apps/api/reefvision/services/semantic_models.py`, corresponding backend tests, `apps/web/src/api/client.ts`.

1. Add failing backend tests for explicit PyTorch CUDA availability/device metadata and ReefPose registration metadata containing schema name, training configuration, device/precision, and checkpoint integrity.
2. Implement the minimal typed contract extensions.
3. Run focused backend tests, Ruff, and mypy.
4. Commit `feat: expose ReefPose GUI metadata`.

## Task 2 — Typed Workflow Builder pose controls

**Files:** `WorkflowGraphWorkspace.tsx`, `WorkflowVisualEditor.tsx`, `workflowTemplates.ts`, their tests, and focused CSS if required.

1. Add failing component tests for ReefPose/Ultralytics switching, provider-specific configuration, dataset schema display, CUDA rejection, and compatible checkpoint filtering.
2. Pass frozen datasets, registered pose models, and runtime status into the existing visual editor.
3. Implement typed pose controls and provider normalization while retaining advanced JSON editing.
4. Add a native ReefPose template/default without changing existing saved graphs.
5. Run focused Vitest, TypeScript, and formatting checks.
6. Commit `feat: configure ReefPose in workflow builder`.

## Task 3 — Live progress, cancellation, and recovery

**Files:** `TrainingRunDetail.tsx`, `ProjectTrainingMonitor.tsx`, `TrainingWorkspace.tsx`, related tests.

1. Add failing tests for ReefPose losses, device/best checkpoint state, cancellation, and resumable failed/cancelled runs.
2. Use the existing retry endpoint and query invalidation; do not synthesize progress.
3. Run focused frontend tests and checks.
4. Commit `feat: monitor and resume ReefPose training`.

## Task 4 — Model Hub provenance and inference handoff

**Files:** `ModelManager.tsx`, `App.tsx`, `videoWorkspaceBridge.ts`, `VideoTrackingWorkspace.tsx`, related tests.

1. Add failing tests for ReefPose anatomy/provenance/checkpoint metadata and the Pose Tracking action.
2. Render structured registered-model metadata with schema compatibility facts.
3. Extend the existing video workspace command with model selection and wire Model Hub to it.
4. Run focused tests and checks.
5. Commit `feat: inspect and use ReefPose models`.

## Task 5 — End-to-end GUI acceptance and regression validation

**Files:** focused Playwright fixture/spec and `docs/reefpose/phase2b-validation.md`.

1. Install the locked frontend dependencies with `npm ci` and verify the lockfile is unchanged.
2. Add or adapt an end-to-end test for dataset selection → ReefPose configuration → workflow execution → progress → registration → Model Hub → Pose Tracking inference/review.
3. Start the local API/UI with synthetic data and exercise the actual workflow through the browser using Windows computer control; capture concrete run/model/job evidence.
4. Run Prettier, TypeScript, Vitest, production build, relevant Playwright, focused backend integration tests, and the previously failing backend tests under available dependencies.
5. Document results, limitations, and the non-scientific nature of synthetic fixtures.
6. Commit `test: validate ReefPose Phase 2B GUI`.

## Review focus

- Saved graph replay and omitted-provider Ultralytics defaults.
- Provider switches leaving stale incompatible architecture/configuration.
- Schema filtering using exact ID/revision/hash, including repeated landmarks.
- CUDA capability versus actual availability.
- Resume visibility only for backend-resumable native jobs.
- Model metadata rendering defensively when older registrations omit new fields.
- Inference handoff selects the intended registered model and does not mark predictions verified.
