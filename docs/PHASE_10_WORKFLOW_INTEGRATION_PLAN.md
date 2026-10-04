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


## Phase 10B — Retraining and Results Package integration

### 10B-1 — Workflow Results Package

Completed training results can now terminate in a normal ReefVision scientific
Results Package workflow artifact.

The node:

`training_result -> training_results_package -> results_package`

delegates to the existing `ResultsPackageService` and does not reproduce
package-building logic.

Before a package is emitted, ReefVision checks:

- project identity
- persisted training-run identity
- immutable dataset manifest identity
- immutable split manifest identity
- trained checkpoint SHA-256, when present
- Results Package self-verification

The workflow artifact records the exact upstream training artifact checksum,
training-run identity, archive SHA-256, package verification result, dataset
and split hashes, checkpoint hash, package options, and managed paths.

### Pose retraining boundary

Phase 10A already produces immutable, scientist-verified pose-training
datasets and exports.

ReefVision does not yet have a production local pose-training runner.
SLEAP-NN is currently a validated registration/inference backend, not a
training backend.

Phase 10B-2 therefore adds a real pose-training execution path rather than
misrepresenting dataset export as retraining. Ultralytics pose is the first
local target because the existing validated pose export already produces its
dataset layout.


### Results Package Windows path safety

Phase 10B-1 exposed a Windows path-length failure in the existing shared
Results Package builder when the ReefVision data root is deeply nested.

The shared builder now:

- avoids repeating the descriptive final package stem inside its temporary
  staging directory
- reserves path headroom for nested package files
- constrains generated workbook names using the same path budget
- constrains copied native artifact filenames using the same path budget
- keeps the package's run identity and scientific provenance inside the
  package metadata even when a filesystem component must be shortened

This is a storage-safety correction used by both normal Training workspace
Results Packages and workflow-generated Results Packages; it does not alter
training metrics, dataset hashes, checkpoint hashes, or package verification.


### 10B-2A — Actual Ultralytics pose retraining

ReefVision now has a production `pose_model_training` workflow node.

This is actual model training, not an export alias.

The node requires:

- an immutable scientist-verified `pose_training_dataset`
- a registered Ultralytics `task=pose` seed checkpoint
- an exact matching ReefVision landmark-schema content hash

A second frozen pose dataset may optionally be connected as validation truth.

Validation policy is fail-explicit:

- with a separate frozen validation dataset, Ultralytics receives
  `images/train` and `images/val`
- without a separate validation dataset, the runner forces `val=false`
- the training frames are never silently reused and reported as independent
  validation evidence
- runs without validation carry an explicit scientific warning

Pose runs use ReefVision's normal persisted `TrainingRun`, `Job`,
`ExperimentRecord`, checkpoint hashing, metrics collection, cancellation,
workflow provenance, and `training_result` artifact type.

The pose training split identity is represented by a canonical SHA-256 over
the exact training dataset, optional validation dataset, schema identity, and
validation mode.

### 10B-2B remaining

The next slice binds the newly trained Ultralytics pose checkpoint back to the
exact frozen ReefVision landmark-schema revision during model registration and
validates the complete:

pose_training_dataset
→ pose_model_training
→ register_trained_model
→ training_results_package

chain.


### 10B-2B — Trained pose registration and exact schema binding

Completed Ultralytics pose-training runs now enter ReefVision's normal model
registry without losing pose truth identity.

Registration verifies:

- the run is a completed Ultralytics `task=pose` run
- the persisted pose split-manifest SHA-256 is unchanged
- the frozen training dataset still matches the run dataset hash
- the recorded pose schema ID, revision, and content hash still match the
  immutable frozen dataset
- any frozen validation dataset remains compatible with the same schema
- the produced checkpoint identifies itself as `task=pose`
- the checkpoint keypoint count exactly matches the frozen landmark-schema
  revision

After validation, ReefVision registers the checkpoint through the normal model
registry and creates a `PoseModelSchemaBinding` pointing to the exact existing
schema ID and revision used for training.

No replacement schema is created.

The registered model metadata retains:

- training-run and experiment identity
- frozen training dataset ID and SHA-256
- optional frozen validation dataset ID and SHA-256
- split-manifest SHA-256
- initial pose-model identity/checksum
- pose schema ID/revision/content hash
- repeated semantic landmark labels
- validation mode
- checkpoint and metric provenance

The standard workflow model reference surfaces this pose lineage, and the
standard Results Package workflow artifact carries the pose dataset/schema
identity alongside the training/checkpoint hashes.

Phase 10B now supports the defensible chain:

`scientist-reviewed pose truth`
→ `immutable pose training dataset`
→ `actual Ultralytics pose retraining`
→ `trained checkpoint`
→ `registered pose model`
→ `exact frozen schema binding`
→ `verified Results Package`


## Phase 10C — End-to-end resumability, provenance, and final closeout

Phase 10C hardens workflow persistence around the completed scientist-ready
pose/retraining path.

### Restart and resume semantics

Interrupted workflow runs are requeued at startup.

- already-succeeded nodes remain succeeded
- their artifact IDs remain unchanged
- only a node that was actively `running` is reset to `pending`
- recovery events are retained in `recovery_history`
- human-review pauses remain durable and are not treated as failures

Before a succeeded node can be skipped during resume, every persisted input and
output artifact is rehashed. Checksum failure blocks the workflow instead of
silently rerunning or propagating corrupted scientific state.

### Idempotent side-effect recovery

The production pose path now closes the important crash windows:

- Pose Inference reuses a succeeded child video-tracking job created by the
  same workflow run/node.
- Pose Model Training reuses a completed TrainingRun/Job created by the same
  workflow run/node when dataset, split, seed model, architecture, device,
  precision, random seed, and training configuration are unchanged.
- Frozen pose datasets remain idempotent by source Active Learning round.
- Pose Active Learning rounds remain idempotent by selection SHA-256.
- Trained model registration remains idempotent through model-checkpoint
  identity/checksum.
- Workflow artifact persistence itself reuses an identical previously
  persisted node/port/type payload and fails closed on conflicting output.

### Canonical terminal provenance

Every successful workflow run now stores:

- `provenance_schema_version`
- `provenance_sha256`
- a canonical `provenance_manifest`

The manifest records:

- exact saved graph revision and graph SHA-256
- workflow run/project/job identity
- node order/type/parameters and parameter SHA-256
- every input and output artifact ID/type/port/SHA-256
- scientist review approvals
- terminal artifact identities
- restart/recovery history
- execution timestamps

The provenance manifest itself is canonical-JSON SHA-256 hashed and remains
inspectable through the existing Workflow Run detail endpoint after reopening
ReefVision.

### Scientist-ready end-to-end acceptance scenario

Phase 10C validates one saved graph across the complete loop:

`registered pose model`
→ `pose inference`
→ `temporal association`
→ `scientist pose review`
→ `pose Active Learning`
→ `scientist candidate verification`
→ `immutable frozen pose dataset`
→ `native pose-training export`
→ `actual Ultralytics pose retraining`
→ `trained pose registration`
→ `exact frozen schema binding`
→ `verified Results Package`

The final graph is reopened after completion and must expose the identical
terminal provenance SHA-256.

## Phase 10 status: COMPLETE

Phase 10 now provides executable workflow integration for pose inference,
temporal identities, human review, behavior-ready reviewed pose state, pose
Active Learning, verified immutable retraining truth, training/export,
Ultralytics pose retraining, exact trained-model schema binding, Results
Packages, restart-safe reuse, and inspectable end-to-end provenance.
