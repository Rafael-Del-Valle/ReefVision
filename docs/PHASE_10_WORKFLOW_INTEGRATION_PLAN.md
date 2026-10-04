# ReefVision Scientist-Ready Phase 10 — Workflow Integration

## Goal

Connect ReefVision's validated scientific modules into one typed,
reproducible, resumable workflow system without replacing the existing GUI
or duplicating scientific algorithms.

## Phase 10A — Pose and behavior workflow integration

### 10A-1 — Typed contracts

Define workflow artifacts and node contracts for:

1. Pose inference
2. Temporal landmark association
3. Scientist pose review
4. Behavior dynamics
5. Pose Active Learning
6. Scientist Active Learning review
7. Immutable pose-training dataset freeze
8. Pose-training export

10A-1 is intentionally contract-only. Nodes MUST NOT claim executable status
until their adapters call the production services.

### 10A-2 — Production runtime adapters

Bind the contracts to existing production implementations:

- video/pose tracking provider execution
- PoseTemporalTrackingService
- BehaviorDynamicsService
- PoseActiveLearningService
- PoseTrainingDatasetService
- PoseTrainingExportService

No duplicate scientific logic is permitted in the workflow layer.

### 10A-3 — Review/resume semantics

Add persisted pause/resume behavior for:

- pose review
- Active Learning review

Completed upstream nodes must not rerun after scientist review.

## Phase 10B — Retraining and results integration

Connect immutable pose-training truth to retraining/export and Results Package
provenance.

## Phase 10C — End-to-end closeout

Validate:

video
→ pose inference
→ temporal association
→ scientist review
→ behavior analysis / Active Learning
→ scientist verification
→ frozen training truth
→ export/retraining
→ reproducible result/project package

## Scientific invariants

- Machine predictions are never silently promoted to scientist truth.
- Repeated landmarks retain shared semantic labels and persistent identities.
- Identity breaks, occlusion, uncertainty, and corrections remain explicit.
- Frozen Phase 9 dataset hashes remain authoritative.
- Behavior outputs identify exact source track and ethogram revisions.
- Workflow retries are idempotent.
- Workflow artifacts preserve model, provider, checkpoint, dataset/video,
  graph-revision, and node-run provenance.
