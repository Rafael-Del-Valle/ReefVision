# ReefPose Phase 2A Native Training Integration Design

## Goal

Make the existing ReefVision pose-training workflow execute the native ReefPose-S trainer from immutable scientist-verified pose datasets, register only completed checkpoints in Model Hub, and preserve the existing Ultralytics path without rebuilding Phase 1.

## Existing system and compatibility constraints

- `PoseTrainingDataset` already provides immutable dataset identity, manifest hash, exact pose-schema ID/revision/content hash, and verified-truth status.
- `PoseTrainingExportService` already creates integrity-checked `ultralytics_pose` ZIP bundles. Phase 1's `load_reefvision_pose_export` consumes that bundle without introducing a second dataset representation.
- `TrainingRun`, `Job`, `ExperimentRecord`, workflow artifacts, and `register_trained_model` already persist progress, provenance, replay identity, and registration outcomes.
- `pose_model_training` is already an executable Workflow Builder node. It must be extended, not duplicated.
- The Ultralytics job path and its existing configuration defaults remain the default when no provider is supplied.
- ReefPose-S checkpoints already have an atomic, versioned format containing model configuration, anatomy schema, optimizer/scaler state, metrics, reproducibility metadata, and historical-best state.

## Architecture

The existing workflow service becomes provider-neutral by accepting `provider_id` (`ultralytics` by default, `reefpose` additionally), selecting provider-specific defaults and validation, and persisting the provider in the same `TrainingRun`. The public pose job processor dispatches by the persisted provider: Ultralytics continues through the existing implementation, while a focused native ReefPose job adapter exports and validates immutable truth, builds Phase 1 datasets/loaders, runs `ReefPoseTrainer`, and persists the same run/job contract.

ReefPose uses the existing `ultralytics_pose` interoperability bundle only as a verified frozen transport. At execution time the native adapter revalidates dataset manifest hash and exact schema ID/revision/content hash against the database record. A separate frozen validation dataset is optional; when absent, no training data is reported as independent validation.

The existing `register_trained_model` node remains the only registration step. Pose registration is generalized from Ultralytics-only to the provider stored on the completed run, while retaining all current dataset, split-manifest, schema, checkpoint, and checksum checks. Failed or cancelled runs remain ineligible because registration requires a completed run with a finalized checkpoint.

## Provider-specific contract

### Ultralytics

- Default provider when `provider_id` is omitted.
- Existing YOLO11 architecture validation, training configuration, retraining seed behavior, callbacks, and artifacts remain unchanged.

### ReefPose

- Architecture is exactly `reefpose-s`.
- Random initialization is supported without a seed checkpoint.
- Registered initialization accepts only a ReefPose pose model bound to the dataset's exact schema revision/hash and whose managed checkpoint still matches its registered SHA-256.
- Native configuration fields: `epochs`, `batch`, `input_height`, `input_width`, `base_channels`, `fpn_channels`, `learning_rate`, `weight_decay`, `heatmap_sigma`, `workers`, `gradient_clip_norm`, and `deterministic`.
- AMP is enabled only when workflow precision is `amp`; device resolution is delegated to the Phase 1 native trainer.
- Every completed epoch reports progress and metrics to `TrainingRun` and `Job`.
- Cooperative cancellation is checked between batches. Cancellation persists an resumable checkpoint but does not set a result checkpoint or completed status.
- Retry/resume is represented by a ReefPose resume checkpoint recorded in the run artifact manifest; the native processor accepts queued failed/cancelled work only after the run is explicitly returned to queued state by its caller. Historical-best behavior remains the Phase 1 trainer's responsibility.

## Workflow and replay

The Workflow Builder chain remains:

`Frozen Pose Dataset -> Train Pose Model -> Register Trained Model`

The training node's existing typed input/output ports remain stable. `provider_id` is an optional parameter with a backward-compatible `ultralytics` default. Saved-workflow recovery includes provider identity in its exact-run comparison so a replay cannot silently reuse a checkpoint from another provider.

## Persistence and rollback

- Successful native training records configuration, per-epoch metrics, logs, immutable dataset/export checksums, schema provenance, reproducibility metadata, best/last checkpoint paths, and the finalized best checkpoint SHA-256.
- Completion creates or updates the same experiment record expected by registration and workflow artifacts.
- Failure/cancellation updates job and run status atomically and never exposes `result_checkpoint_path`.
- Exported source datasets are read-only inputs; all extraction, logs, and checkpoints live under the run's managed training directory.

## Validation

Engineering tests use synthetic verified datasets and explicitly do not establish biological/scientific accuracy. Coverage must include native workflow execution, registration and inference, exact schema mismatch rejection, cancellation/resume and historical best, failed-run non-registration, saved-workflow replay/provider identity, immutable dataset preservation, and unchanged Ultralytics defaults. Final validation includes CPU tests plus a short CUDA run on the RTX 3090 with a registered checkpoint used for inference.

## Non-goals

- No pretrained weights or automatic downloads.
- No new annotation, dataset, workflow-node, or Model Hub subsystem.
- No scientific accuracy claim.
- No Phase 1 architecture redesign, transformer backbone, graph refinement, or temporal model.
