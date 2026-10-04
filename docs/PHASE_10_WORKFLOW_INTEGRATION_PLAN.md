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


## Phase 10A-2 — Production runtime adapters

Implemented workflow adapters over the canonical production services for:

- pose inference through the production video pose provider path
- explicit temporal landmark association
- deterministic behavior dynamics
- explainable pose Active Learning
- scientist-verified immutable pose dataset freezing
- native and external pose-training export

The workflow layer does not duplicate any pose association, Active Learning,
behavior, dataset hashing, or export science logic.

### Temporal-association ownership

Normal standalone pose video jobs preserve their existing behavior and
automatically build temporal pose associations.

The workflow `pose_inference` node explicitly sets
`build_pose_temporal_associations=false`, allowing the dedicated
`pose_temporal_association` node to own that workflow stage. The default
outside workflows remains `true`, preserving backward compatibility.

### Deferred to Phase 10A-3

The following scientist boundaries remain intentionally non-executable:

- `pose_review_gate`
- `pose_active_learning_review_gate`

Phase 10A-3 will implement persisted pause/resume semantics and will verify
that completed upstream nodes are not rerun after scientist review.


## Phase 10A-3 — Scientist review and persisted resume

Both pose review boundaries now use ReefVision's existing persisted workflow
pause/resume system.

### Pose review gate

`pose_review_gate` pauses after temporal association and records the exact
source artifact. Resume is refused while any of the following remain:

- temporal source track changed after association, making it stale
- an observation has no association decision
- an unresolved identity remains machine-only/unreviewed
- an identity-break association remains machine-only/unreviewed
- a tracker-created identity break has not been explicitly human verified

Low-confidence and other QC flags remain visible in the readiness snapshot,
but a scientist may approve them globally after inspection. An explicitly
unresolved identity is acceptable only after the scientist records that
decision through the normal correction path.

The resulting `reviewed_pose_tracks` artifact stores the exact source
artifact checksum, reviewed track revisions, review approval, and readiness
snapshot.

### Pose Active Learning review gate

`pose_active_learning_review_gate` pauses until the canonical Active Learning
manifest is retraining-ready:

- every candidate is verified or skipped
- at least one candidate is scientist verified
- every verified candidate has a verified pose checksum
- the round has reached complete status

The gate emits `verified_pose_active_learning_round`; only that type can feed
the immutable pose-training freeze node.

### Resume invariant

On resume, workflow nodes already marked `succeeded` are skipped. Pose
inference, temporal association, and Active Learning are therefore not rerun
after scientist review. Their existing artifact IDs and checksums remain the
inputs to downstream scientific outputs.

## Phase 10A status

Phase 10A is complete when 10A-3 validation passes:

- all eight pose/behavior workflow nodes executable
- both human-review nodes persist pause/resume state
- upstream pose computation is not repeated on resume
- only scientist-verified Active Learning truth can be frozen/exported


### Windows-safe workflow export storage

Pose-training workflow exports retain their full original export filename in
artifact provenance, but the physical managed-project filename is compact and
run-scoped.

This prevents deeply nested Windows data roots from exceeding the classic
MAX_PATH limit while preserving:

- original export filename
- media type
- immutable bundle SHA-256
- dataset identity
- workflow run identity
- workflow node-run identity
- managed relative path

The physical filename is an implementation/storage detail and does not change
the contents or scientific identity of the immutable training package.
